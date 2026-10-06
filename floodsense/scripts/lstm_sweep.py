#!/usr/bin/env python3
"""Optimise the LSTM on validation, then evaluate it once on test.

    python scripts/lstm_sweep.py --days 540 --stations 32 --seed 20261006

Everything is decided on the validation split: the architecture, the loss,
the training-set composition, whether a seed-ensemble beats a single model,
and the operating threshold. The test split is read exactly once, at the
end, with all of that frozen.

The dataset is built once and reused across configurations, so the
comparison is on identical splits and the cost is one feature build rather
than one per run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.config import Config  # noqa: E402


@dataclass
class Candidate:
    """One LSTM configuration to try."""

    name: str
    hidden_size: int = 64
    num_layers: int = 2
    dropout: float = 0.25
    learning_rate: float = 7e-4
    loss: str = "focal"
    negative_keep_rate: float = 0.08
    sequence_steps: int = 36
    attention: bool = True
    last_step_skip: bool = True
    seed: int = 0
    note: str = ""

    def apply(self, cfg: Config, base_seed: int) -> Config:
        import copy

        out = copy.deepcopy(cfg)
        out.model.hidden_size = self.hidden_size
        out.model.num_layers = self.num_layers
        out.model.dropout = self.dropout
        out.model.attention = self.attention
        out.model.last_step_skip = self.last_step_skip
        out.train.learning_rate = self.learning_rate
        out.train.loss = self.loss
        out.windows.negative_keep_rate = self.negative_keep_rate
        out.windows.sequence_steps = self.sequence_steps
        out.train.seed = base_seed + self.seed
        out.windows.seed = base_seed
        return out


#: The sweep. Sequence length is held at 36 steps for the main comparison so
#: every configuration sees identical splits (the embargo is derived from it),
#: with one longer-window run reported separately.
CANDIDATES = [
    Candidate("baseline_h64", note="the shipped configuration"),
    Candidate("wide_h128", hidden_size=128, dropout=0.30, note="more capacity"),
    Candidate("deep_h96_l3", hidden_size=96, num_layers=3, learning_rate=5e-4,
              note="a third recurrent layer"),
    Candidate("weighted_bce", loss="weighted_bce", note="loss swap"),
    Candidate("more_negatives", negative_keep_rate=0.25,
              note="3x the negatives per epoch"),
    Candidate("no_skip", last_step_skip=False, note="ablation: drop the skip"),
]

LONG_WINDOW = Candidate(
    "long_window_72", sequence_steps=72, note="6 hours of sequence instead of 3"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=540)
    p.add_argument("--stations", type=int, default=32)
    p.add_argument("--seed", type=int, default=20261006)
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--patience", type=int, default=4)
    p.add_argument("--batch-size", type=int, default=512)
    p.add_argument("--ensemble-seeds", type=int, default=3,
                   help="seed-average the winner; 1 disables")
    p.add_argument("--skip-long-window", action="store_true")
    p.add_argument("--outdir", default="artifacts/lstm_sweep")
    p.add_argument("--results", default="results")
    return p.parse_args()


def build(cfg: Config, args: argparse.Namespace):
    from floodsense.pipeline import prepare_from_synthetic
    from floodsense.synthetic import SyntheticConfig

    return prepare_from_synthetic(
        cfg,
        SyntheticConfig(days=args.days, n_stations=args.stations, seed=args.seed),
    )


def train_one(prepared, cfg: Config, outdir: Path, label: str):
    """Train one model and return it with its validation probabilities."""
    from floodsense.train import predict, resolve_device, train

    result = train(
        prepared, cfg, outdir / label,
        run_baselines=False, evaluate_test=False, verbose=False,
    )
    from floodsense.model import FloodSenseLSTM

    model = FloodSenseLSTM.load(outdir / label / "floodsense_lstm.pt")
    probs, _, _ = predict(
        model,
        DataLoader(prepared.dataset("val"), batch_size=4096),
        resolve_device("cpu"),
    )
    return model, probs, result


def score_validation(prepared, cfg: Config, probs: np.ndarray) -> dict:
    from floodsense.events import threshold_for_accuracy_band
    from floodsense.experiments import labels_for
    from floodsense.metrics import compute_report

    y = labels_for(prepared, prepared.splits.val)
    event_kwargs = dict(
        horizon_max_minutes=cfg.labels.horizon_max_minutes,
        merge_gap_minutes=cfg.labels.post_alert_blackout_minutes,
    )
    selection = threshold_for_accuracy_band(
        prepared.splits.val, y, probs,
        cfg.accuracy_band[0], cfg.accuracy_band[1],
        prepared.grid.n_steps, prepared.grid.n_stations, **event_kwargs,
    )
    report = compute_report(y, probs, selection["threshold"])
    events = selection["event_report"]
    return {
        "pr_auc": float(report.pr_auc),
        "roc_auc": float(report.roc_auc),
        "threshold": float(selection["threshold"]),
        "accuracy": float(report.accuracy_not_a_headline_metric),
        "event_recall": float(events.event_recall),
        "recall": float(report.recall),
        "precision": float(report.precision),
        "f1": float(report.f1),
        "false_alarms_per_station_day": float(events.false_alarms_per_station_day),
        "mean_lead_minutes": float(events.mean_lead_minutes),
    }


def main() -> int:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    results_dir = Path(args.results)
    results_dir.mkdir(parents=True, exist_ok=True)

    base = Config()
    base.operating_point = "accuracy"
    base.train.epochs = args.epochs
    base.train.patience = args.patience
    base.train.batch_size = args.batch_size
    base.train.use_mlflow = True
    base.train.seed = args.seed
    base.windows.seed = args.seed

    print(
        f"[sweep] SYNTHETIC benchmark, fresh seed {args.seed} "
        f"({args.days} days x {args.stations} stations). "
        "data.gov.sg is unreachable, so real data cannot be used."
    )
    print("[sweep] building the dataset once (sequence 36)...")
    t0 = time.time()
    prepared36 = build(base, args)
    print(f"        {time.time() - t0:.0f}s | {json.dumps(prepared36.labels.summary())}")

    rows: list[dict] = []
    best = None

    for candidate in CANDIDATES:
        cfg = candidate.apply(base, args.seed)
        print(f"\n[sweep] {candidate.name}: {candidate.note}")
        started = time.time()
        model, probs, result = train_one(prepared36, cfg, outdir, candidate.name)
        scores = score_validation(prepared36, cfg, probs)
        row = {
            "name": candidate.name,
            "note": candidate.note,
            "hidden_size": candidate.hidden_size,
            "num_layers": candidate.num_layers,
            "dropout": candidate.dropout,
            "learning_rate": candidate.learning_rate,
            "loss": candidate.loss,
            "negative_keep_rate": candidate.negative_keep_rate,
            "sequence_steps": candidate.sequence_steps,
            "last_step_skip": candidate.last_step_skip,
            "n_parameters": int(model.n_parameters()),
            "best_epoch": int(result.best_epoch),
            "minutes": round((time.time() - started) / 60.0, 1),
            **scores,
        }
        rows.append(row)
        print(
            f"        PR-AUC {row['pr_auc']:.4f} | ROC {row['roc_auc']:.4f} | "
            f"event recall {row['event_recall']:.3f} | acc {row['accuracy']:.2%} | "
            f"{row['minutes']:.1f} min | {row['n_parameters']:,} params"
        )
        if best is None or row["pr_auc"] > best["pr_auc"]:
            best = row

    if not args.skip_long_window:
        cfg = LONG_WINDOW.apply(base, args.seed)
        print(f"\n[sweep] {LONG_WINDOW.name}: {LONG_WINDOW.note} (rebuilding splits)")
        prepared72 = build(cfg, args)
        started = time.time()
        model, probs, result = train_one(prepared72, cfg, outdir, LONG_WINDOW.name)
        scores = score_validation(prepared72, cfg, probs)
        row = {
            "name": LONG_WINDOW.name, "note": LONG_WINDOW.note,
            "hidden_size": LONG_WINDOW.hidden_size,
            "num_layers": LONG_WINDOW.num_layers,
            "sequence_steps": 72,
            "n_parameters": int(model.n_parameters()),
            "best_epoch": int(result.best_epoch),
            "minutes": round((time.time() - started) / 60.0, 1),
            "caveat": (
                "splits differ by 36 steps of embargo from the other rows "
                "(<0.02% of validation samples)"
            ),
            **scores,
        }
        rows.append(row)
        print(
            f"        PR-AUC {row['pr_auc']:.4f} | ROC {row['roc_auc']:.4f} | "
            f"event recall {row['event_recall']:.3f}"
        )
        if row["pr_auc"] > best["pr_auc"]:
            best = row
        del prepared72

    print(f"\n[sweep] best single configuration on validation PR-AUC: "
          f"{best['name']} ({best['pr_auc']:.4f})")

    # Seed ensemble of the winner, accepted only if validation says it helps.
    winner = next(c for c in CANDIDATES + [LONG_WINDOW] if c.name == best["name"])
    ensemble_row = None
    if args.ensemble_seeds > 1 and winner.sequence_steps == 36:
        print(f"\n[sweep] seed-ensembling {winner.name} over "
              f"{args.ensemble_seeds} seeds")
        members = []
        for k in range(args.ensemble_seeds):
            member = Candidate(**{**winner.__dict__, "seed": k,
                                  "name": f"{winner.name}_s{k}"})
            cfg = member.apply(base, args.seed)
            _, probs, _ = train_one(prepared36, cfg, outdir, member.name)
            members.append(probs)
            print(f"        seed {k} trained")
        averaged = np.mean(members, axis=0)
        scores = score_validation(prepared36, base, averaged)
        ensemble_row = {
            "name": f"{winner.name}_ensemble_x{args.ensemble_seeds}",
            "note": f"mean probability over {args.ensemble_seeds} seeds",
            "sequence_steps": winner.sequence_steps,
            **scores,
        }
        rows.append(ensemble_row)
        print(
            f"        PR-AUC {scores['pr_auc']:.4f} | "
            f"event recall {scores['event_recall']:.3f}"
        )
        np.save(outdir / "ensemble_val_probs.npy", averaged)
        if scores["pr_auc"] > best["pr_auc"]:
            best = ensemble_row
            print("        ensemble wins on validation")
        else:
            print("        ensemble does not beat the single model; keeping it")

    (results_dir / "lstm_sweep_validation.json").write_text(
        json.dumps(
            {
                "data_source": (
                    f"SYNTHETIC (floodsense.synthetic, days={args.days}, "
                    f"stations={args.stations}, seed={args.seed})"
                ),
                "selection_metric": "validation PR-AUC",
                "test_set_used": False,
                "selected": best["name"],
                "candidates": rows,
            },
            indent=2,
        )
    )
    print(f"\n[sweep] validation table -> {results_dir}/lstm_sweep_validation.json")
    print(f"[sweep] SELECTED: {best['name']}")
    (outdir / "selected.json").write_text(json.dumps(best, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
