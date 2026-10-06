"""Evaluation for a rare-event forecaster.

**Accuracy is not reported as a headline metric, by design.** At the base
rate in this problem (order 1 in 500 station-intervals), a model that
answers "no flood" every time scores 99.8% accuracy and is worthless.  The
metrics that separate a useful model from that constant are:

* **PR-AUC** (average precision) - the primary model-selection metric.
* **Recall** at the chosen operating point - the share of real flood events
  caught, which is what a responder cares about.
* **Precision** at that point - how much false-alarm load the operator
  carries.
* **ROC-AUC** - ranking quality, reported for comparability; it is
  optimistic under heavy imbalance.
* **Brier score** - calibration, which matters because the Flood Risk Score
  consumes the probability, not just the ranking.

The operating point is chosen explicitly: ``threshold_for_recall`` finds the
highest threshold that still reaches a target recall on the validation
split, so the recall/precision trade-off is a documented decision rather
than an accident of ``p > 0.5``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
)


@dataclass
class ClassificationReport:
    """Metrics at one operating point, plus threshold-free scores."""

    threshold: float
    n_samples: int
    n_positive: int
    base_rate: float

    precision: float
    recall: float
    f1: float
    specificity: float

    pr_auc: float
    roc_auc: float
    brier: float

    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int

    #: Reported last and explicitly flagged: at this base rate, accuracy is
    #: dominated by the negative class and must not be read as skill.
    accuracy_not_a_headline_metric: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_line(self) -> str:
        return (
            f"PR-AUC {self.pr_auc:.4f} | ROC-AUC {self.roc_auc:.4f} | "
            f"recall {self.recall:.3f} | precision {self.precision:.3f} | "
            f"F1 {self.f1:.3f} | thr {self.threshold:.4f}"
        )


def compute_report(
    y_true: np.ndarray, y_prob: np.ndarray, threshold: float
) -> ClassificationReport:
    """Full report for probabilities ``y_prob`` against labels ``y_true``."""
    y_true = np.asarray(y_true).reshape(-1).astype(np.int8)
    y_prob = np.asarray(y_prob, dtype=np.float64).reshape(-1)
    if y_true.shape != y_prob.shape:
        raise ValueError("y_true and y_prob must have the same length")

    n_pos = int(y_true.sum())
    n = int(y_true.size)
    pred = (y_prob >= threshold).astype(np.int8)

    tp = int(((pred == 1) & (y_true == 1)).sum())
    fp = int(((pred == 1) & (y_true == 0)).sum())
    tn = int(((pred == 0) & (y_true == 0)).sum())
    fn = int(((pred == 0) & (y_true == 1)).sum())

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    specificity = tn / (tn + fp) if (tn + fp) else 0.0

    single_class = n_pos == 0 or n_pos == n
    pr_auc = float("nan") if single_class else float(
        average_precision_score(y_true, y_prob)
    )
    roc_auc = float("nan") if single_class else float(roc_auc_score(y_true, y_prob))
    brier = float(brier_score_loss(y_true, np.clip(y_prob, 0.0, 1.0)))

    return ClassificationReport(
        threshold=float(threshold),
        n_samples=n,
        n_positive=n_pos,
        base_rate=float(n_pos / n) if n else 0.0,
        precision=float(precision),
        recall=float(recall),
        f1=float(f1),
        specificity=float(specificity),
        pr_auc=pr_auc,
        roc_auc=roc_auc,
        brier=brier,
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        accuracy_not_a_headline_metric=float((tp + tn) / n) if n else 0.0,
    )


def threshold_for_recall(
    y_true: np.ndarray, y_prob: np.ndarray, target_recall: float
) -> tuple[float, float, float]:
    """Highest threshold whose recall is at least ``target_recall``.

    Returns:
        ``(threshold, achieved_recall, achieved_precision)``.  If no
        threshold reaches the target, the one with the best recall is
        returned, so the caller always gets a usable operating point - check
        the returned recall before trusting it.
    """
    y_true = np.asarray(y_true).reshape(-1).astype(np.int8)
    y_prob = np.asarray(y_prob, dtype=np.float64).reshape(-1)
    if y_true.sum() == 0:
        return 0.5, 0.0, 0.0

    precision, recall, thresholds = precision_recall_curve(y_true, y_prob)
    # precision_recall_curve returns len(thresholds) == len(recall) - 1; the
    # final point is recall 0 / precision 1 with no threshold.
    precision, recall = precision[:-1], recall[:-1]

    ok = recall >= target_recall
    if not ok.any():
        best = int(np.argmax(recall))
        return float(thresholds[best]), float(recall[best]), float(precision[best])

    candidates = np.flatnonzero(ok)
    pick = candidates[int(np.argmax(thresholds[candidates]))]
    return float(thresholds[pick]), float(recall[pick]), float(precision[pick])


def precision_at_recall_table(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    recalls: tuple[float, ...] = (0.70, 0.80, 0.90, 0.95, 0.99),
) -> list[dict[str, float]]:
    """Operating-point table: what precision each recall level costs.

    This is the table to show an operations stakeholder - it answers "if we
    insist on catching 95% of events, how many false alarms do we accept?"
    """
    rows = []
    for target in recalls:
        thr, rec, prec = threshold_for_recall(y_true, y_prob, target)
        alarms_per_1000 = float(((np.asarray(y_prob) >= thr).mean()) * 1000.0)
        rows.append(
            {
                "target_recall": float(target),
                "threshold": thr,
                "achieved_recall": rec,
                "precision": prec,
                "alerts_per_1000_samples": alarms_per_1000,
            }
        )
    return rows


def lift_over_base_rate(report: ClassificationReport) -> float:
    """How many times better than chance the positive predictions are."""
    if report.base_rate <= 0.0:
        return float("nan")
    return report.precision / report.base_rate
