"""Schema and sanity validation — the Bronze → Silver gate.

Synthetic data is clean by construction. Real gauge data is not: NEA states
the historical files may contain missing records and have not had the
quality control applied to climate records, readings get re-published when
corrected, and a geocoder can put a Singapore road in another hemisphere.

So every real table passes through here before it reaches the feature code,
and the report says what was dropped and why. The principle throughout: drop
a row only when keeping it would corrupt a downstream computation, and never
drop one silently.

Severities:

``ERROR``  the table cannot be used as-is; rows are dropped.
``WARN``   usable, but something is off and the number is worth seeing.
``INFO``   context for reading the other two.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from ..schema import SG_BOUNDS, STEP_MINUTES, TIMEZONE

ERROR = "ERROR"
WARN = "WARN"
INFO = "INFO"

#: A 5-minute total above this is not meteorology, it is a broken gauge.
#: Singapore's heaviest recorded short-duration rates are far below it, so
#: the threshold rejects instrument faults without touching real extremes.
IMPLAUSIBLE_MM_PER_5MIN = 100.0


@dataclass
class Issue:
    level: str
    code: str
    detail: str
    n_rows: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationReport:
    table: str
    n_rows_in: int = 0
    n_rows_out: int = 0
    issues: list[Issue] = field(default_factory=list)

    def add(self, level: str, code: str, detail: str, n_rows: int = 0) -> None:
        self.issues.append(Issue(level, code, detail, n_rows))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == ERROR]

    @property
    def passed(self) -> bool:
        return self.n_rows_out > 0

    @property
    def n_dropped(self) -> int:
        return self.n_rows_in - self.n_rows_out

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "n_rows_in": self.n_rows_in,
            "n_rows_out": self.n_rows_out,
            "n_dropped": self.n_dropped,
            "passed": self.passed,
            "issues": [i.to_dict() for i in self.issues],
        }

    def summary(self) -> str:
        lines = [
            f"{self.table}: {self.n_rows_in:,} in -> {self.n_rows_out:,} out "
            f"({self.n_dropped:,} dropped)"
        ]
        for issue in self.issues:
            count = f" [{issue.n_rows:,} rows]" if issue.n_rows else ""
            lines.append(f"  {issue.level:<5} {issue.code}: {issue.detail}{count}")
        return "\n".join(lines)


def _require_columns(
    frame: pd.DataFrame, columns: tuple[str, ...], report: ValidationReport
) -> bool:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        report.add(
            ERROR,
            "missing_columns",
            f"required columns absent: {missing}; found {list(frame.columns)}",
        )
        return False
    return True


def _to_sgt(series: pd.Series) -> pd.Series:
    ts = pd.to_datetime(series, errors="coerce", format="mixed")
    if getattr(ts.dt, "tz", None) is None:
        return ts.dt.tz_localize(TIMEZONE, ambiguous="NaT", nonexistent="NaT")
    return ts.dt.tz_convert(TIMEZONE)


def validate_rainfall(
    readings: pd.DataFrame, *, drop_implausible: bool = True
) -> tuple[pd.DataFrame, ValidationReport]:
    """Validate canonical rainfall readings."""
    report = ValidationReport("rainfall", n_rows_in=len(readings))
    if not _require_columns(readings, ("ts", "station_id", "rainfall_mm"), report):
        return readings.iloc[0:0], report

    out = readings.copy()

    out["ts"] = _to_sgt(out["ts"])
    bad_ts = int(out["ts"].isna().sum())
    if bad_ts:
        report.add(ERROR, "unparseable_timestamp", "timestamps dropped", bad_ts)
        out = out.loc[out["ts"].notna()]

    out["rainfall_mm"] = pd.to_numeric(out["rainfall_mm"], errors="coerce")
    bad_value = int(out["rainfall_mm"].isna().sum())
    if bad_value:
        report.add(WARN, "missing_value", "null or non-numeric readings dropped", bad_value)
        out = out.loc[out["rainfall_mm"].notna()]

    negative = int((out["rainfall_mm"] < 0).sum())
    if negative:
        report.add(ERROR, "negative_rainfall", "negative depths dropped", negative)
        out = out.loc[out["rainfall_mm"] >= 0]

    implausible = int((out["rainfall_mm"] > IMPLAUSIBLE_MM_PER_5MIN).sum())
    if implausible:
        level = ERROR if drop_implausible else WARN
        report.add(
            level,
            "implausible_rainfall",
            f"readings above {IMPLAUSIBLE_MM_PER_5MIN} mm per {STEP_MINUTES} min "
            f"({'dropped' if drop_implausible else 'kept'}); this is a gauge "
            "fault, not weather",
            implausible,
        )
        if drop_implausible:
            out = out.loc[out["rainfall_mm"] <= IMPLAUSIBLE_MM_PER_5MIN]

    off_grid = int(
        (out["ts"].dt.minute % STEP_MINUTES != 0).sum()
        + (out["ts"].dt.second != 0).sum()
    )
    if off_grid:
        report.add(
            INFO,
            "off_grid_timestamps",
            f"readings not aligned to the {STEP_MINUTES}-minute grid; RainGrid "
            "floors them and averages collisions",
            off_grid,
        )

    duplicated = int(out.duplicated(["ts", "station_id"]).sum())
    if duplicated:
        report.add(
            WARN,
            "duplicate_readings",
            "same station and interval published more than once; averaged by "
            "RainGrid (a reading is re-published when corrected)",
            duplicated,
        )

    if len(out):
        span_days = (out["ts"].max() - out["ts"].min()).total_seconds() / 86400.0
        stations = out["station_id"].nunique()
        expected = span_days * 24 * 60 / STEP_MINUTES * stations
        coverage = len(out) / expected if expected > 0 else 0.0
        report.add(
            INFO,
            "coverage",
            f"{stations} stations over {span_days:.1f} days; "
            f"{coverage:.1%} of the slots a complete record would hold",
        )
        if coverage < 0.5:
            report.add(
                WARN,
                "sparse_coverage",
                f"only {coverage:.1%} of expected slots present; long gaps "
                "weaken the accumulation features",
            )

    report.n_rows_out = len(out)
    return out.reset_index(drop=True), report


def validate_alerts(alerts: pd.DataFrame) -> tuple[pd.DataFrame, ValidationReport]:
    """Validate canonical flood alerts — the label source."""
    report = ValidationReport("flood_alerts", n_rows_in=len(alerts))
    if len(alerts) == 0:
        report.add(
            ERROR,
            "no_alerts",
            "no flood alerts supplied; without a positive class there is "
            "nothing to learn. PUB began publishing alerts by API in late "
            "2025, so a historical archive must be accumulated.",
        )
        return alerts, report

    if not _require_columns(
        alerts, ("ts_start", "longitude", "latitude"), report
    ):
        return alerts.iloc[0:0], report

    out = alerts.copy()

    out["ts_start"] = _to_sgt(out["ts_start"])
    bad_start = int(out["ts_start"].isna().sum())
    if bad_start:
        report.add(ERROR, "unparseable_ts_start", "alerts without a usable start time", bad_start)
        out = out.loc[out["ts_start"].notna()]

    if "ts_end" in out.columns:
        out["ts_end"] = _to_sgt(out["ts_end"])
        reversed_span = int((out["ts_end"] < out["ts_start"]).sum())
        if reversed_span:
            report.add(
                WARN,
                "end_before_start",
                "alert end precedes its start; ts_end cleared for these",
                reversed_span,
            )
            out.loc[out["ts_end"] < out["ts_start"], "ts_end"] = pd.NaT
        open_ended = int(out["ts_end"].isna().sum())
        if open_ended:
            report.add(
                INFO,
                "open_ended_alerts",
                "alerts with no end time; a default duration is assumed when "
                "building the active-alert mask",
                open_ended,
            )

    for column in ("longitude", "latitude"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    no_coords = int(out[["longitude", "latitude"]].isna().any(axis=1).sum())
    if no_coords:
        report.add(
            ERROR,
            "missing_coordinates",
            "alerts without coordinates cannot be matched to a station",
            no_coords,
        )
        out = out.dropna(subset=["longitude", "latitude"])

    outside = ~(
        out["longitude"].between(SG_BOUNDS["lon_min"], SG_BOUNDS["lon_max"])
        & out["latitude"].between(SG_BOUNDS["lat_min"], SG_BOUNDS["lat_max"])
    )
    n_outside = int(outside.sum())
    if n_outside:
        report.add(
            ERROR,
            "coordinates_outside_singapore",
            "alerts outside the Singapore bounding box dropped; a geocoder "
            "that resolves a road to another country would otherwise corrupt "
            "every spatial feature",
            n_outside,
        )
        out = out.loc[~outside]

    if "alert_id" in out.columns:
        duplicated = int(out.duplicated("alert_id").sum())
        if duplicated:
            report.add(
                WARN,
                "duplicate_alert_id",
                "repeated alert ids collapsed; one event must not count twice",
                duplicated,
            )
            out = out.drop_duplicates("alert_id")

    if len(out):
        span_days = (out["ts_start"].max() - out["ts_start"].min()).total_seconds() / 86400.0
        report.add(
            INFO,
            "alert_span",
            f"{len(out)} alerts over {span_days:.1f} days "
            f"({out['ts_start'].min()} to {out['ts_start'].max()})",
        )
        if span_days < 180:
            report.add(
                WARN,
                "short_alert_history",
                f"only {span_days:.0f} days of alert history; a chronological "
                "train/validation/test split needs enough events in every "
                "split for the metrics to mean anything",
            )

    report.n_rows_out = len(out)
    return out.reset_index(drop=True), report


def validate_stations(stations: pd.DataFrame) -> tuple[pd.DataFrame, ValidationReport]:
    """Validate station metadata."""
    report = ValidationReport("stations", n_rows_in=len(stations))
    if not _require_columns(
        stations, ("station_id", "longitude", "latitude"), report
    ):
        return stations.iloc[0:0], report

    out = stations.copy()
    for column in ("longitude", "latitude"):
        out[column] = pd.to_numeric(out[column], errors="coerce")

    no_coords = int(out[["longitude", "latitude"]].isna().any(axis=1).sum())
    if no_coords:
        report.add(ERROR, "missing_coordinates", "stations without coordinates", no_coords)
        out = out.dropna(subset=["longitude", "latitude"])

    outside = ~(
        out["longitude"].between(SG_BOUNDS["lon_min"], SG_BOUNDS["lon_max"])
        & out["latitude"].between(SG_BOUNDS["lat_min"], SG_BOUNDS["lat_max"])
    )
    n_outside = int(outside.sum())
    if n_outside:
        report.add(
            ERROR, "coordinates_outside_singapore", "stations outside the bounding box", n_outside
        )
        out = out.loc[~outside]

    duplicated = int(out.duplicated("station_id").sum())
    if duplicated:
        report.add(WARN, "duplicate_station_id", "repeated station ids collapsed", duplicated)
        out = out.drop_duplicates("station_id")

    if len(out) < 5:
        report.add(
            WARN,
            "few_stations",
            f"only {len(out)} stations; the spatial neighbour features need a "
            "network to be meaningful",
        )

    report.n_rows_out = len(out)
    return out.reset_index(drop=True), report


def validate_all(
    readings: pd.DataFrame, stations: pd.DataFrame, alerts: pd.DataFrame
) -> tuple[dict[str, pd.DataFrame], dict[str, ValidationReport]]:
    """Validate the three canonical tables together."""
    clean_readings, rainfall_report = validate_rainfall(readings)
    clean_stations, station_report = validate_stations(stations)
    clean_alerts, alert_report = validate_alerts(alerts)

    known = set(clean_stations["station_id"]) if len(clean_stations) else set()
    if known and len(clean_readings):
        orphan = ~clean_readings["station_id"].isin(known)
        n_orphan = int(orphan.sum())
        if n_orphan:
            rainfall_report.add(
                WARN,
                "readings_without_station_metadata",
                "readings from stations with no coordinates dropped; they "
                "cannot be placed on the map or given neighbours",
                n_orphan,
            )
            clean_readings = clean_readings.loc[~orphan].reset_index(drop=True)
            rainfall_report.n_rows_out = len(clean_readings)

    return (
        {
            "readings": clean_readings,
            "stations": clean_stations,
            "alerts": clean_alerts,
        },
        {
            "rainfall": rainfall_report,
            "stations": station_report,
            "flood_alerts": alert_report,
        },
    )
