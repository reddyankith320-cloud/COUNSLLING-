"""Training loop.

Model selection is on **validation PR-AUC**, never on loss or accuracy.  The
decision threshold is then chosen on the validation split to reach
``Config.target_recall``, and only after that is the test split touched -
once - with that frozen threshold.  Test data never influences the
threshold, the architecture or the stopping epoch.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from .config import Config
from .events import (
    EventReport,
    event_level_report,
    event_operating_curve,
    threshold_for_event_recall,
)
from .losses import build_loss
from .metrics import (
    ClassificationReport,
    compute_report,
    lift_over_base_rate,
    precision_at_recall_table,
    threshold_for_recall,
)
from .model import FloodSenseLSTM
from .pipeline import Prepared


@dataclass
class EpochRecord:
    epoch: int
    train_loss: float
    val_loss: float
    val_pr_auc: float
    val_roc_auc: float
    seconds: float
    learning_rate: float


@dataclass
class TrainResult:
    """Everything a run produced, serialised next to the checkpoint."""

    best_epoch: int
    best_val_pr_auc: float
    threshold: float
    val_report: ClassificationReport
    test_report: ClassificationReport
    operating_points: list[dict[str, float]]
    val_event_report: EventReport
    test_event_report: EventReport
    interval_threshold: float
    event_curve: list[dict[str, float]]
    history: list[EpochRecord]
    model_path: str
    n_parameters: int
    data_report: dict = field(default_factory=dict)
    baselines: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "best_epoch": self.best_epoch,
            "best_val_pr_auc": self.best_val_pr_auc,
            "threshold": self.threshold,
            "val": self.val_report.to_dict(),
            "test": self.test_report.to_dict(),
            "test_lift_over_base_rate": lift_over_base_rate(self.test_report),
            "operating_points_val": self.operating_points,
            "val_events": self.val_event_report.to_dict(),
            "test_events": self.test_event_report.to_dict(),
            "interval_threshold": self.interval_threshold,
            "event_operating_curve_val": self.event_curve,
            "history": [asdict(h) for h in self.history],
            "model_path": self.model_path,
            "n_parameters": self.n_parameters,
            "data": self.data_report,
            "baselines": self.baselines,
        }


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def resolve_device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


@torch.no_grad()
def predict(
    model: FloodSenseLSTM, loader: DataLoader, device: torch.device
) -> tuple[np.ndarray, np.ndarray, float]:
    """Return ``(probabilities, labels, mean_bce)`` over a loader."""
    model.eval()
    probs: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    loss_sum, n = 0.0, 0
    bce = torch.nn.BCEWithLogitsLoss(reduction="sum")

    for seq, static, y in loader:
        seq = seq.to(device, non_blocking=True)
        static = static.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)
        logits = model(seq, static)
        loss_sum += float(bce(logits, y))
        n += y.numel()
        probs.append(torch.sigmoid(logits).detach().cpu().numpy())
        labels.append(y.detach().cpu().numpy())

    if not probs:
        return np.zeros(0), np.zeros(0), 0.0
    return (
        np.concatenate(probs),
        np.concatenate(labels),
        loss_sum / max(n, 1),
    )


def train(
    prepared: Prepared,
    cfg: Config,
    outdir: str | Path,
    *,
    run_baselines: bool = True,
    verbose: bool = True,
) -> TrainResult:
    """Fit the LSTM, select a threshold, evaluate once on the test split."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    seed_everything(cfg.train.seed)
    device = resolve_device(cfg.train.device)

    train_ds = prepared.dataset("train")
    val_ds = prepared.dataset("val")
    test_ds = prepared.dataset("test")
    if len(train_ds) == 0 or len(val_ds) == 0:
        raise ValueError("empty train or validation split; widen the data period")

    loader_args = dict(num_workers=cfg.train.num_workers, pin_memory=False)
    train_loader = DataLoader(
        train_ds, batch_size=cfg.train.batch_size, shuffle=True,
        drop_last=False, **loader_args,
    )
    eval_batch = max(cfg.train.batch_size * 4, 1024)
    val_loader = DataLoader(val_ds, batch_size=eval_batch, shuffle=False, **loader_args)
    test_loader = DataLoader(
        test_ds, batch_size=eval_batch, shuffle=False, **loader_args
    )

    model = FloodSenseLSTM(
        n_dynamic=prepared.dynamic_scaled.shape[2],
        n_static=prepared.static_scaled.shape[1],
        cfg=cfg.model,
        feature_names=prepared.features.names,
        static_names=prepared.statics.names,
    ).to(device)

    criterion = build_loss(
        cfg.train.loss,
        pos_weight=train_ds.positive_weight(cfg.train.max_pos_weight),
        gamma=cfg.train.focal_gamma,
        alpha=cfg.train.focal_alpha,
    ).to(device)

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=cfg.train.learning_rate,
        weight_decay=cfg.train.weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=2, min_lr=1e-5
    )

    if verbose:
        print(
            f"[floodsense] device={device} params={model.n_parameters():,} "
            f"train={len(train_ds):,} val={len(val_ds):,} test={len(test_ds):,} "
            f"train_pos={int(train_ds.label_vector().sum()):,}"
        )

    history: list[EpochRecord] = []
    best_score = -np.inf
    best_epoch = -1
    best_state: dict | None = None
    stale = 0
    model_path = outdir / "floodsense_lstm.pt"

    mlflow_run = _start_mlflow(cfg, prepared) if cfg.train.use_mlflow else None

    for epoch in range(1, cfg.train.epochs + 1):
        t0 = time.time()
        model.train()
        running, seen = 0.0, 0

        for seq, static, y in train_loader:
            seq = seq.to(device, non_blocking=True)
            static = static.to(device, non_blocking=True)
            y = y.to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)
            logits = model(seq, static)
            loss = criterion(logits, y)
            loss.backward()
            if cfg.train.grad_clip > 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.train.grad_clip)
            optimizer.step()

            running += loss.detach().item() * y.numel()
            seen += y.numel()

        val_prob, val_y, val_loss = predict(model, val_loader, device)
        val_report = compute_report(val_y, val_prob, threshold=0.5)
        score = val_report.pr_auc if np.isfinite(val_report.pr_auc) else -np.inf
        scheduler.step(score)

        record = EpochRecord(
            epoch=epoch,
            train_loss=running / max(seen, 1),
            val_loss=val_loss,
            val_pr_auc=float(val_report.pr_auc),
            val_roc_auc=float(val_report.roc_auc),
            seconds=time.time() - t0,
            learning_rate=float(optimizer.param_groups[0]["lr"]),
        )
        history.append(record)

        if verbose:
            print(
                f"  epoch {epoch:3d} | train {record.train_loss:.5f} | "
                f"val BCE {val_loss:.5f} | val PR-AUC {record.val_pr_auc:.4f} | "
                f"val ROC-AUC {record.val_roc_auc:.4f} | {record.seconds:.1f}s"
            )
        if mlflow_run is not None:
            _log_mlflow_epoch(record)

        if score > best_score + cfg.train.min_delta:
            best_score, best_epoch = score, epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= cfg.train.patience:
                if verbose:
                    print(f"  early stop at epoch {epoch} (best {best_epoch})")
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    model.save(model_path)

    # Thresholds are chosen on validation; test is touched once, after.
    val_prob, val_y, _ = predict(model, val_loader, device)

    n_steps = prepared.grid.n_steps
    n_stations = prepared.grid.n_stations
    event_kwargs = dict(
        horizon_max_minutes=cfg.labels.horizon_max_minutes,
        merge_gap_minutes=cfg.labels.post_alert_blackout_minutes,
    )

    # Secondary, reported for completeness: the per-interval operating point.
    interval_threshold, achieved_recall, achieved_precision = threshold_for_recall(
        val_y, val_prob, cfg.target_recall
    )
    if verbose and achieved_recall < cfg.target_recall:
        print(
            f"  note: no threshold reaches per-interval recall "
            f"{cfg.target_recall:.2f} on validation; best achievable is "
            f"{achieved_recall:.3f} (precision {achieved_precision:.3f})"
        )

    # Primary operating point: event-level recall is the decision-relevant
    # target - catching the flood episode, not every 5-minute cell in it.
    threshold, val_event_report = threshold_for_event_recall(
        prepared.splits.val,
        val_y,
        val_prob,
        cfg.target_recall,
        n_steps,
        n_stations,
        **event_kwargs,
    )

    val_report = compute_report(val_y, val_prob, threshold)
    operating_points = precision_at_recall_table(val_y, val_prob)
    event_curve = event_operating_curve(
        prepared.splits.val,
        val_y,
        val_prob,
        thresholds=np.quantile(
            val_prob[val_y > 0] if (val_y > 0).any() else val_prob,
            np.linspace(0.02, 0.98, 12),
        ),
        n_steps=n_steps,
        n_stations=n_stations,
        **event_kwargs,
    )

    test_prob, test_y, _ = predict(model, test_loader, device)
    if len(test_y):
        test_report = compute_report(test_y, test_prob, threshold)
        test_event_report = event_level_report(
            prepared.splits.test,
            test_y,
            test_prob,
            threshold,
            n_steps,
            n_stations,
            **event_kwargs,
        )
    else:
        test_report, test_event_report = val_report, val_event_report

    baselines: dict = {}
    if run_baselines:
        from .baselines import run_baselines as _run

        baselines = _run(prepared, cfg, threshold_target=cfg.target_recall)

    result = TrainResult(
        best_epoch=best_epoch,
        best_val_pr_auc=float(best_score),
        threshold=threshold,
        val_report=val_report,
        test_report=test_report,
        operating_points=operating_points,
        val_event_report=val_event_report,
        test_event_report=test_event_report,
        interval_threshold=interval_threshold,
        event_curve=event_curve,
        history=history,
        model_path=str(model_path),
        n_parameters=model.n_parameters(),
        data_report=prepared.report(),
        baselines=baselines,
    )

    cfg.to_json(outdir / "config.json")
    (outdir / "scaler.json").write_text(json.dumps(prepared.scaler.to_dict(), indent=2))
    (outdir / "metrics.json").write_text(json.dumps(result.to_dict(), indent=2))

    # Serving artifacts: the static feature table and the risk-score
    # normalisation references are part of the fitted model, not something
    # an inference job may recompute for itself (see infer.py).
    from .infer import StaticTable
    from .risk import RiskScorer

    (outdir / "statics.json").write_text(
        json.dumps(
            StaticTable(
                station_ids=prepared.statics.station_ids,
                names=list(prepared.statics.names),
                values=prepared.statics.values,
            ).to_dict(),
            indent=2,
        )
    )
    (outdir / "risk_scorer.json").write_text(
        json.dumps(RiskScorer.from_prepared(prepared, cfg.risk).to_dict(), indent=2)
    )

    if mlflow_run is not None:
        _log_mlflow_final(result, outdir)

    if verbose:
        print(f"\n[floodsense] validation : {val_report.summary_line()}")
        print(f"[floodsense] test       : {test_report.summary_line()}")
        print(f"[floodsense] val events : {val_event_report.summary_line()}")
        print(f"[floodsense] test events: {test_event_report.summary_line()}")
        print(
            f"[floodsense] test precision is {lift_over_base_rate(test_report):.1f}x "
            f"the base rate of {test_report.base_rate:.5f}"
        )
        print(f"[floodsense] artifacts  : {outdir}")

    return result


# --------------------------------------------------------------------------
# MLflow is optional: the same script runs locally and on Databricks.
# --------------------------------------------------------------------------


def _start_mlflow(cfg: Config, prepared: Prepared):
    try:
        import mlflow
    except ImportError:
        return None
    try:
        mlflow.set_experiment(cfg.train.mlflow_experiment)
        run = mlflow.start_run()
        mlflow.log_params(
            {
                "hidden_size": cfg.model.hidden_size,
                "num_layers": cfg.model.num_layers,
                "dropout": cfg.model.dropout,
                "attention": cfg.model.attention,
                "sequence_steps": cfg.windows.sequence_steps,
                "loss": cfg.train.loss,
                "learning_rate": cfg.train.learning_rate,
                "batch_size": cfg.train.batch_size,
                "horizon_min": cfg.labels.horizon_min_minutes,
                "horizon_max": cfg.labels.horizon_max_minutes,
                "radius_km": cfg.labels.radius_km,
                "target_recall": cfg.target_recall,
                "n_dynamic_features": len(prepared.features.names),
                "n_static_features": len(prepared.statics.names),
                "positive_rate": prepared.labels.positive_rate,
            }
        )
        return run
    except Exception:  # a broken tracking URI must not kill training
        return None


def _log_mlflow_epoch(record: EpochRecord) -> None:
    try:
        import mlflow

        mlflow.log_metrics(
            {
                "train_loss": record.train_loss,
                "val_loss": record.val_loss,
                "val_pr_auc": record.val_pr_auc,
                "val_roc_auc": record.val_roc_auc,
            },
            step=record.epoch,
        )
    except Exception:
        pass


def _log_mlflow_final(result: TrainResult, outdir: Path) -> None:
    try:
        import mlflow

        mlflow.log_metrics(
            {
                "best_val_pr_auc": result.best_val_pr_auc,
                "threshold": result.threshold,
                "test_pr_auc": result.test_report.pr_auc,
                "test_roc_auc": result.test_report.roc_auc,
                "test_recall": result.test_report.recall,
                "test_precision": result.test_report.precision,
                "test_f1": result.test_report.f1,
                "test_brier": result.test_report.brier,
            }
        )
        mlflow.log_artifacts(str(outdir))
        mlflow.end_run()
    except Exception:
        pass
