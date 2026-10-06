"""Non-sequential baselines.

An LSTM is only the right answer if it beats models that cannot remember.
These three run on exactly the same splits, scaler and threshold policy:

``logreg_last_step``
    Logistic regression on the feature vector at time ``t`` only.  This is
    the "rainfall now -> flood" model the brief warns against, included so
    its ceiling is visible rather than asserted.

``gbm_last_step``
    Gradient boosting on the same single-step vector.  Separates "the
    features carry the signal" from "the sequence carries the signal": if
    this matches the LSTM, the recurrence is not earning its keep.

``gbm_window_summary``
    Gradient boosting on per-channel last/mean/max/slope over the whole
    window - a deliberately strong non-recurrent competitor that still sees
    the history, just without learning how to weight it.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from .config import Config
from .metrics import compute_report, threshold_for_recall
from .pipeline import Prepared


def last_step_matrix(prepared: Prepared, index: np.ndarray) -> np.ndarray:
    """``(N, F)`` features at the sample's own timestep."""
    return prepared.dynamic_scaled[index[:, 0], index[:, 1], :]


def window_summary_matrix(
    prepared: Prepared, index: np.ndarray, sequence_steps: int, chunk: int = 20_000
) -> np.ndarray:
    """``(N, 4F)``: last, mean, max and end-to-end slope per channel.

    Built through a strided view over the time axis and gathered in chunks.
    A per-sample Python loop here is the single slowest thing in an
    evaluation run - there are hundreds of thousands of samples - while the
    view costs nothing and each chunk is a few tens of MB.
    """
    from numpy.lib.stride_tricks import sliding_window_view

    n = len(index)
    f = prepared.dynamic_scaled.shape[2]
    out = np.empty((n, 4 * f), dtype=np.float32)
    if n == 0:
        return out

    # (T - L + 1, S, F, L); the last axis is the trailing window.
    view = sliding_window_view(prepared.dynamic_scaled, sequence_steps, axis=0)
    starts = index[:, 0].astype(np.int64) - sequence_steps + 1
    stations = index[:, 1].astype(np.int64)
    denominator = max(sequence_steps - 1, 1)

    for lo in range(0, n, chunk):
        hi = min(lo + chunk, n)
        window = view[starts[lo:hi], stations[lo:hi]]      # (m, F, L)
        out[lo:hi, 0:f] = window[..., -1]
        out[lo:hi, f : 2 * f] = window.mean(axis=-1)
        out[lo:hi, 2 * f : 3 * f] = window.max(axis=-1)
        out[lo:hi, 3 * f : 4 * f] = (
            window[..., -1] - window[..., 0]
        ) / denominator
    return out


def static_matrix(prepared: Prepared, index: np.ndarray) -> np.ndarray:
    return prepared.static_scaled[index[:, 1], :]


def labels_for(prepared: Prepared, index: np.ndarray) -> np.ndarray:
    return prepared.labels.labels[index[:, 0], index[:, 1]].astype(np.int8)


def run_baselines(
    prepared: Prepared, cfg: Config, threshold_target: float = 0.95
) -> dict:
    """Fit every baseline and report it at the same target recall."""
    seq = cfg.windows.sequence_steps
    splits = prepared.splits
    results: dict = {}

    y_train = labels_for(prepared, splits.train)
    y_val = labels_for(prepared, splits.val)
    y_test = labels_for(prepared, splits.test)
    if y_train.sum() == 0 or y_val.sum() == 0:
        return {"skipped": "no positive samples in train or validation"}

    feature_sets = {
        "last_step": lambda idx: np.hstack(
            [last_step_matrix(prepared, idx), static_matrix(prepared, idx)]
        ),
        "window_summary": lambda idx: np.hstack(
            [window_summary_matrix(prepared, idx, seq), static_matrix(prepared, idx)]
        ),
    }

    models = {
        "logreg_last_step": (
            "last_step",
            LogisticRegression(
                max_iter=2000, class_weight="balanced", n_jobs=None, C=1.0
            ),
        ),
        "gbm_last_step": (
            "last_step",
            HistGradientBoostingClassifier(
                max_iter=250,
                learning_rate=0.08,
                max_leaf_nodes=31,
                l2_regularization=1.0,
                class_weight="balanced",
                random_state=cfg.train.seed,
            ),
        ),
        "gbm_window_summary": (
            "window_summary",
            HistGradientBoostingClassifier(
                max_iter=300,
                learning_rate=0.08,
                max_leaf_nodes=31,
                l2_regularization=1.0,
                class_weight="balanced",
                random_state=cfg.train.seed,
            ),
        ),
    }

    cache: dict[str, dict[str, np.ndarray]] = {}
    for name in feature_sets:
        cache[name] = {
            "train": feature_sets[name](splits.train),
            "val": feature_sets[name](splits.val),
            "test": feature_sets[name](splits.test)
            if len(splits.test)
            else np.zeros((0, 1), dtype=np.float32),
        }

    for label, (fs, estimator) in models.items():
        x = cache[fs]
        estimator.fit(x["train"], y_train)

        val_prob = estimator.predict_proba(x["val"])[:, 1]
        threshold, _, _ = threshold_for_recall(y_val, val_prob, threshold_target)
        val_report = compute_report(y_val, val_prob, threshold)

        if len(y_test):
            test_prob = estimator.predict_proba(x["test"])[:, 1]
            test_report = compute_report(y_test, test_prob, threshold)
        else:
            test_report = val_report

        results[label] = {
            "features": fs,
            "threshold": threshold,
            "val": val_report.to_dict(),
            "test": test_report.to_dict(),
        }

    return results


def comparison_table(result_dict: dict, lstm_test: dict) -> str:
    """Markdown table comparing the LSTM against the baselines on test."""
    rows = [
        "| model | PR-AUC | ROC-AUC | recall | precision | F1 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    def fmt(name: str, d: dict) -> str:
        return (
            f"| {name} | {d['pr_auc']:.4f} | {d['roc_auc']:.4f} | "
            f"{d['recall']:.3f} | {d['precision']:.3f} | {d['f1']:.3f} |"
        )

    rows.append(fmt("**FloodSense LSTM**", lstm_test))
    for name, payload in result_dict.items():
        if isinstance(payload, dict) and "test" in payload:
            rows.append(fmt(name, payload["test"]))
    return "\n".join(rows)
