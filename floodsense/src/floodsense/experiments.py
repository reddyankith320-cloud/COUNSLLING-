"""Model comparison on validation data only.

Every model here is fitted on the training split and scored on validation.
**The test split is never read by anything in this module.** Model choice,
feature-set choice and threshold choice all happen here; the test set is
opened once, afterwards, by ``scripts/final_evaluation.py``.

Selection is on **validation PR-AUC**, with event recall and F1 as
secondary. Accuracy is not a selection metric — at a sub-1% base rate it
ranks "predict nothing" first — it is an operating-point constraint applied
after a model is chosen.

Each model is additionally reported at *its own* 95-99% accuracy operating
point, chosen on validation, so the comparison table is decision-relevant
rather than abstract: it says what each candidate would actually do if
deployed under the accuracy requirement.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .config import Config
from .events import threshold_for_accuracy_band
from .metrics import compute_report
from .pipeline import Prepared

#: Feature representations offered to the tabular models.
#:
#: ``last_step`` is not the handicap it looks like. The engineered channels
#: are already multi-timescale aggregates - accumulations from 10 minutes to
#: 3 days, four exponentially weighted states, lags, rolling statistics - so
#: the vector at time t carries the history. ``window_summary`` adds
#: last/mean/max/slope of each channel over the sequence window, which is
#: mostly redundant with that; it is included so validation decides rather
#: than assumption.
FEATURE_KINDS = ("last_step", "window_summary")


@dataclass
class ExperimentResult:
    """One fitted candidate, scored on validation only."""

    name: str
    family: str
    feature_kind: str
    val_pr_auc: float
    val_roc_auc: float
    val_brier: float
    val_threshold: float
    val_accuracy: float
    val_recall: float
    val_precision: float
    val_f1: float
    val_event_recall: float
    val_false_alarms_per_station_day: float
    val_mean_lead_minutes: float
    n_features: int
    fit_seconds: float
    params: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def static_for(prepared: Prepared, index: np.ndarray) -> np.ndarray:
    return prepared.static_scaled[index[:, 1], :]


def last_step_features(prepared: Prepared, index: np.ndarray) -> np.ndarray:
    return np.hstack(
        [
            prepared.dynamic_scaled[index[:, 0], index[:, 1], :],
            static_for(prepared, index),
        ]
    )


def window_summary_features(
    prepared: Prepared, index: np.ndarray, sequence_steps: int
) -> np.ndarray:
    from .baselines import window_summary_matrix

    return np.hstack(
        [
            window_summary_matrix(prepared, index, sequence_steps),
            static_for(prepared, index),
        ]
    )


def feature_names(prepared: Prepared, kind: str) -> list[str]:
    dynamic = list(prepared.features.names)
    static = list(prepared.statics.names)
    if kind == "last_step":
        return dynamic + static
    return (
        [f"{n}_last" for n in dynamic]
        + [f"{n}_mean" for n in dynamic]
        + [f"{n}_max" for n in dynamic]
        + [f"{n}_slope" for n in dynamic]
        + static
    )


def build_matrices(
    prepared: Prepared, cfg: Config, kind: str
) -> dict[str, np.ndarray]:
    """Feature matrices for train and val. Test is deliberately absent."""
    if kind == "last_step":
        builder: Callable[[np.ndarray], np.ndarray] = lambda idx: last_step_features(
            prepared, idx
        )
    elif kind == "window_summary":
        builder = lambda idx: window_summary_features(  # noqa: E731
            prepared, idx, cfg.windows.sequence_steps
        )
    else:
        raise ValueError(f"unknown feature kind {kind!r}")

    return {
        "train": builder(prepared.splits.train),
        "val": builder(prepared.splits.val),
    }


def labels_for(prepared: Prepared, index: np.ndarray) -> np.ndarray:
    return prepared.labels.labels[index[:, 0], index[:, 1]].astype(np.int8)


# --------------------------------------------------------------------------
# The zoo
# --------------------------------------------------------------------------


def available_families() -> dict[str, bool]:
    """Which optional libraries are importable in this environment."""
    out = {"sklearn": True}
    for module in ("xgboost", "lightgbm"):
        try:
            __import__(module)
            out[module] = True
        except ImportError:
            out[module] = False
    try:
        import torch  # noqa: F401

        out["torch"] = True
    except ImportError:
        out["torch"] = False
    return out


def build_tabular_models(seed: int, pos_weight: float) -> dict[str, tuple[str, object]]:
    """Instantiate every available tabular model.

    Every one is given the class imbalance explicitly, by weight rather than
    by resampling: resampling would change the training distribution's base
    rate, and the probabilities would then need a correction before the risk
    score could consume them.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression

    models: dict[str, tuple[str, object]] = {
        "logistic_regression": (
            "sklearn",
            LogisticRegression(
                max_iter=3000, class_weight="balanced", C=1.0, n_jobs=None
            ),
        ),
        "random_forest": (
            "sklearn",
            RandomForestClassifier(
                n_estimators=200,
                max_depth=14,
                min_samples_leaf=20,
                class_weight="balanced_subsample",
                n_jobs=-1,
                random_state=seed,
            ),
        ),
        "hist_gradient_boosting": (
            "sklearn",
            HistGradientBoostingClassifier(
                max_iter=400,
                learning_rate=0.06,
                max_leaf_nodes=31,
                min_samples_leaf=40,
                l2_regularization=1.0,
                early_stopping=True,
                validation_fraction=0.15,
                class_weight="balanced",
                random_state=seed,
            ),
        ),
    }

    try:
        from xgboost import XGBClassifier

        models["xgboost"] = (
            "xgboost",
            XGBClassifier(
                n_estimators=500,
                learning_rate=0.06,
                max_depth=6,
                subsample=0.85,
                colsample_bytree=0.8,
                min_child_weight=5,
                reg_lambda=1.0,
                scale_pos_weight=pos_weight,
                eval_metric="aucpr",
                tree_method="hist",
                n_jobs=-1,
                random_state=seed,
            ),
        )
    except ImportError:
        pass

    try:
        from lightgbm import LGBMClassifier

        models["lightgbm"] = (
            "lightgbm",
            LGBMClassifier(
                n_estimators=500,
                learning_rate=0.06,
                num_leaves=31,
                min_child_samples=40,
                subsample=0.85,
                subsample_freq=1,
                colsample_bytree=0.8,
                reg_lambda=1.0,
                scale_pos_weight=pos_weight,
                n_jobs=-1,
                random_state=seed,
                verbose=-1,
            ),
        )
    except ImportError:
        pass

    return models


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


def evaluate_on_validation(
    prepared: Prepared,
    cfg: Config,
    probabilities: np.ndarray,
    *,
    name: str,
    family: str,
    feature_kind: str,
    n_features: int,
    fit_seconds: float,
    params: dict,
    note: str = "",
) -> ExperimentResult:
    """Score validation probabilities and find this model's operating point."""
    y_val = labels_for(prepared, prepared.splits.val)
    event_kwargs = dict(
        horizon_max_minutes=cfg.labels.horizon_max_minutes,
        merge_gap_minutes=cfg.labels.post_alert_blackout_minutes,
    )

    selection = threshold_for_accuracy_band(
        prepared.splits.val,
        y_val,
        probabilities,
        cfg.accuracy_band[0],
        cfg.accuracy_band[1],
        prepared.grid.n_steps,
        prepared.grid.n_stations,
        **event_kwargs,
    )
    threshold = selection["threshold"]
    report = compute_report(y_val, probabilities, threshold)
    events = selection["event_report"]

    return ExperimentResult(
        name=name,
        family=family,
        feature_kind=feature_kind,
        val_pr_auc=float(report.pr_auc),
        val_roc_auc=float(report.roc_auc),
        val_brier=float(report.brier),
        val_threshold=float(threshold),
        val_accuracy=float(report.accuracy_not_a_headline_metric),
        val_recall=float(report.recall),
        val_precision=float(report.precision),
        val_f1=float(report.f1),
        val_event_recall=float(events.event_recall),
        val_false_alarms_per_station_day=float(events.false_alarms_per_station_day),
        val_mean_lead_minutes=float(events.mean_lead_minutes),
        n_features=int(n_features),
        fit_seconds=float(fit_seconds),
        params=params,
        note=note,
    )


def run_tabular_experiments(
    prepared: Prepared,
    cfg: Config,
    *,
    feature_kinds: tuple[str, ...] = ("last_step",),
    use_mlflow: bool = True,
    verbose: bool = True,
    save_dir: str | Path | None = None,
) -> list[ExperimentResult]:
    """Fit and score every available tabular model on each feature set.

    Args:
        save_dir: when given, each fitted model is written there immediately
            after scoring and then released. Persisting at that moment avoids
            both refitting later and holding every fitted forest in memory at
            once, which is what pushes this phase into swap.
    """
    y_train = labels_for(prepared, prepared.splits.train)
    positives = float(y_train.sum())
    pos_weight = float((len(y_train) - positives) / positives) if positives else 1.0

    results: list[ExperimentResult] = []
    for kind in feature_kinds:
        matrices = build_matrices(prepared, cfg, kind)
        x_train, x_val = matrices["train"], matrices["val"]
        if verbose:
            print(
                f"\n[{kind}] train {x_train.shape} val {x_val.shape} "
                f"pos_weight {pos_weight:.1f}"
            )

        for name, (family, model) in build_tabular_models(
            cfg.train.seed, pos_weight
        ).items():
            started = time.time()
            try:
                model.fit(x_train, y_train)
                probabilities = model.predict_proba(x_val)[:, 1]
            except Exception as exc:  # a broken optional dep must not stop the sweep
                if verbose:
                    print(f"  {name:24s} FAILED: {exc}")
                continue
            elapsed = time.time() - started

            result = evaluate_on_validation(
                prepared,
                cfg,
                probabilities,
                name=f"{name}:{kind}",
                family=family,
                feature_kind=kind,
                n_features=x_train.shape[1],
                fit_seconds=elapsed,
                params=_safe_params(model),
            )
            results.append(result)
            if verbose:
                print(
                    f"  {name:24s} PR-AUC {result.val_pr_auc:.4f} "
                    f"ROC {result.val_roc_auc:.4f} "
                    f"event-recall {result.val_event_recall:.3f} "
                    f"F1 {result.val_f1:.3f} ({elapsed:.0f}s)"
                )
            if use_mlflow:
                _log_mlflow(result, cfg)

            if save_dir is not None:
                path = Path(save_dir)
                path.mkdir(parents=True, exist_ok=True)
                target = path / f"{name}__{kind}.joblib"
                try:
                    import joblib

                    joblib.dump(model, target, compress=3)
                    if verbose:
                        print(
                            f"    saved {target.name} "
                            f"({target.stat().st_size / 1e6:.1f} MB)"
                        )
                except Exception as exc:
                    if verbose:
                        print(f"    could not save {target.name}: {exc}")
            del model

        del matrices, x_train, x_val

    return results


def _safe_params(model: object) -> dict:
    try:
        params = model.get_params()  # type: ignore[attr-defined]
    except Exception:
        return {}
    return {
        k: v
        for k, v in params.items()
        if isinstance(v, (int, float, str, bool, type(None)))
    }


def _log_mlflow(result: ExperimentResult, cfg: Config) -> None:
    try:
        import mlflow
    except ImportError:
        return
    try:
        mlflow.set_experiment(cfg.train.mlflow_experiment)
        with mlflow.start_run(run_name=result.name):
            mlflow.log_params(
                {
                    "model": result.name,
                    "family": result.family,
                    "feature_kind": result.feature_kind,
                    "n_features": result.n_features,
                    **{f"p_{k}": v for k, v in list(result.params.items())[:40]},
                }
            )
            mlflow.log_metrics(
                {
                    "val_pr_auc": result.val_pr_auc,
                    "val_roc_auc": result.val_roc_auc,
                    "val_brier": result.val_brier,
                    "val_accuracy": result.val_accuracy,
                    "val_recall": result.val_recall,
                    "val_f1": result.val_f1,
                    "val_event_recall": result.val_event_recall,
                    "val_threshold": result.val_threshold,
                    "fit_seconds": result.fit_seconds,
                }
            )
    except Exception:
        pass


def select_best(results: list[ExperimentResult]) -> ExperimentResult:
    """Best validation PR-AUC, ties broken by event recall then F1.

    PR-AUC leads because it is the metric that reflects ranking quality on a
    rare positive class. Event recall breaks ties because, between two models
    that rank equally well, the one that catches more floods is the one worth
    deploying.
    """
    if not results:
        raise ValueError("no experiment results to choose from")
    return max(
        results,
        key=lambda r: (
            r.val_pr_auc if np.isfinite(r.val_pr_auc) else -1.0,
            r.val_event_recall,
            r.val_f1,
        ),
    )


def comparison_markdown(results: list[ExperimentResult]) -> str:
    rows = [
        "| Model | PR-AUC | ROC-AUC | Val event recall | Val recall | Val F1 | Val accuracy | Threshold |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in sorted(results, key=lambda r: -r.val_pr_auc):
        rows.append(
            f"| {r.name} | {r.val_pr_auc:.4f} | {r.val_roc_auc:.4f} | "
            f"{r.val_event_recall:.3f} | {r.val_recall:.3f} | {r.val_f1:.3f} | "
            f"{r.val_accuracy * 100:.2f}% | {r.val_threshold:.4f} |"
        )
    return "\n".join(rows)


def write_comparison(
    results: list[ExperimentResult], path: str | Path, extra: dict | None = None
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "selection_metric": "validation PR-AUC (ties: event recall, then F1)",
        "accuracy_is_not_a_selection_metric": (
            "At this base rate a constant negative prediction maximises "
            "accuracy. Accuracy is applied afterwards as an operating-point "
            "constraint, never to choose a model."
        ),
        "test_set_used": False,
        "available_families": available_families(),
        "models": [r.to_dict() for r in results],
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, indent=2))
