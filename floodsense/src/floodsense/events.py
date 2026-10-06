"""Event-level evaluation.

Per-interval metrics answer "was this one station-5-minute cell labelled
correctly?".  No responder asks that.  They ask:

* Of the floods that happened, how many did we warn about at all?
* How much warning did we get?
* How many times a day does a station cry wolf?

A single flood alert occupies six consecutive label cells (the 30-60 minute
window), and one burst of model output spans many cells too.  Scoring cells
independently therefore both inflates the sample count and makes the
false-alarm number unreadable.  This module collapses both sides into
episodes first:

* a **true event** is a contiguous run of ``label == 1`` for one station;
* an **alarm** is a contiguous run of ``prob >= threshold``, with runs
  separated by less than ``merge_gap_minutes`` joined into one, because an
  operator sees a flickering alarm as a single alarm.

An event counts as caught if any cell inside its window fired.  An alarm
counts as false if it overlaps no event window.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .schema import STEP_MINUTES


@dataclass
class EventReport:
    """Episode-level skill.

    Attributes:
        n_events: true flood events in the evaluated period.
        n_detected: events with at least one firing cell in their window.
        event_recall: ``n_detected / n_events`` - the headline for a
            responder.
        n_alarms: distinct alarm episodes raised.
        n_false_alarms: alarm episodes overlapping no event.
        false_alarms_per_station_day: operator-facing false-alarm load.
        precision_by_alarm: share of alarm episodes that were real.
        mean_lead_minutes: average warning time on detected events,
            measured from the first firing cell to the alert.
        median_lead_minutes: same, median.
        station_days: exposure the rates are divided by.
    """

    n_events: int
    n_detected: int
    event_recall: float
    n_alarms: int
    n_false_alarms: int
    false_alarms_per_station_day: float
    precision_by_alarm: float
    mean_lead_minutes: float
    median_lead_minutes: float
    station_days: float

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_line(self) -> str:
        return (
            f"events {self.n_detected}/{self.n_events} caught "
            f"(recall {self.event_recall:.3f}) | "
            f"false alarms {self.false_alarms_per_station_day:.2f} per station-day | "
            f"mean lead {self.mean_lead_minutes:.0f} min"
        )


def to_grids(
    index: np.ndarray,
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_steps: int,
    n_stations: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Scatter flat sample vectors back onto the ``(T, S)`` grid.

    Returns ``(label_grid, prob_grid, evaluated_mask)``.  Cells that were
    not part of the split are left at 0 and masked out.
    """
    label = np.zeros((n_steps, n_stations), dtype=np.int8)
    prob = np.zeros((n_steps, n_stations), dtype=np.float32)
    mask = np.zeros((n_steps, n_stations), dtype=bool)

    t_idx = index[:, 0].astype(np.int64)
    s_idx = index[:, 1].astype(np.int64)
    label[t_idx, s_idx] = np.asarray(y_true).reshape(-1).astype(np.int8)
    prob[t_idx, s_idx] = np.asarray(y_prob, dtype=np.float32).reshape(-1)
    mask[t_idx, s_idx] = True
    return label, prob, mask


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous ``True`` runs of a 1-D boolean array as ``[start, stop)``."""
    if flags.size == 0:
        return []
    padded = np.concatenate(([False], flags.astype(bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [
        (int(edges[i]), int(edges[i + 1])) for i in range(0, len(edges) - 1, 2)
    ]


def _merge(runs: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    """Join runs separated by fewer than ``gap`` steps."""
    if not runs:
        return []
    merged = [runs[0]]
    for start, stop in runs[1:]:
        if start - merged[-1][1] < gap:
            merged[-1] = (merged[-1][0], stop)
        else:
            merged.append((start, stop))
    return merged


def event_level_report(
    index: np.ndarray,
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: float,
    n_steps: int,
    n_stations: int,
    *,
    horizon_max_minutes: int = 60,
    merge_gap_minutes: int = 30,
    step_minutes: int = STEP_MINUTES,
) -> EventReport:
    """Collapse cells into episodes and score detection, lead time and load."""
    label, prob, mask = to_grids(index, y_true, y_prob, n_steps, n_stations)
    fired = (prob >= threshold) & mask
    gap = max(int(round(merge_gap_minutes / step_minutes)), 1)

    n_events = n_detected = n_alarms = n_false = 0
    leads: list[float] = []

    for s in range(n_stations):
        events = _runs(label[:, s] > 0)
        alarms = _merge(_runs(fired[:, s]), gap)

        n_events += len(events)
        n_alarms += len(alarms)

        for start, stop in events:
            window = fired[start:stop, s]
            if window.any():
                n_detected += 1
                first = start + int(np.flatnonzero(window)[0])
                # The label window ends horizon_max before the alert, so the
                # alert sits horizon_max minutes after the window's start.
                alert_step = start + int(round(horizon_max_minutes / step_minutes))
                leads.append(max((alert_step - first) * step_minutes, 0.0))

        for start, stop in alarms:
            if not (label[start:stop, s] > 0).any():
                n_false += 1

    station_days = float(mask.sum()) * step_minutes / (60.0 * 24.0)
    return EventReport(
        n_events=n_events,
        n_detected=n_detected,
        event_recall=float(n_detected / n_events) if n_events else 0.0,
        n_alarms=n_alarms,
        n_false_alarms=n_false,
        false_alarms_per_station_day=(
            float(n_false / station_days) if station_days > 0 else 0.0
        ),
        precision_by_alarm=(
            float((n_alarms - n_false) / n_alarms) if n_alarms else 0.0
        ),
        mean_lead_minutes=float(np.mean(leads)) if leads else 0.0,
        median_lead_minutes=float(np.median(leads)) if leads else 0.0,
        station_days=station_days,
    )


def event_operating_curve(
    index: np.ndarray,
    y_true: np.ndarray,
    y_prob: np.ndarray,
    thresholds: np.ndarray,
    n_steps: int,
    n_stations: int,
    **kwargs,
) -> list[dict[str, float]]:
    """Event recall and false-alarm load across candidate thresholds.

    This is the table to put in front of an operations stakeholder: it
    prices every recall level in false alarms per station-day.
    """
    rows = []
    for thr in thresholds:
        report = event_level_report(
            index, y_true, y_prob, float(thr), n_steps, n_stations, **kwargs
        )
        rows.append(
            {
                "threshold": float(thr),
                "event_recall": report.event_recall,
                "false_alarms_per_station_day": report.false_alarms_per_station_day,
                "precision_by_alarm": report.precision_by_alarm,
                "mean_lead_minutes": report.mean_lead_minutes,
            }
        )
    return rows


def threshold_for_event_recall(
    index: np.ndarray,
    y_true: np.ndarray,
    y_prob: np.ndarray,
    target_event_recall: float,
    n_steps: int,
    n_stations: int,
    *,
    n_candidates: int = 60,
    **kwargs,
) -> tuple[float, EventReport]:
    """Highest threshold still catching ``target_event_recall`` of events.

    Event recall is monotone non-increasing in the threshold, so a scan over
    quantiles of the predicted probabilities is enough.
    """
    positive_probs = np.asarray(y_prob)[np.asarray(y_true) > 0]
    if positive_probs.size == 0:
        return 0.5, event_level_report(
            index, y_true, y_prob, 0.5, n_steps, n_stations, **kwargs
        )

    candidates = np.unique(
        np.quantile(positive_probs, np.linspace(0.0, 1.0, n_candidates))
    )
    best_threshold = float(candidates[0])
    best_report = None
    for thr in candidates:  # ascending: keep the last one that still passes
        report = event_level_report(
            index, y_true, y_prob, float(thr), n_steps, n_stations, **kwargs
        )
        if report.event_recall >= target_event_recall:
            best_threshold, best_report = float(thr), report
    if best_report is None:
        best_report = event_level_report(
            index, y_true, y_prob, best_threshold, n_steps, n_stations, **kwargs
        )
    return best_threshold, best_report
