"""Staged canonical tables on disk.

Separating "fetch" from "train" matters in practice: the historical rainfall
CSVs are gigabytes, the real-time APIs are rate-limited, and a training run
that re-downloads its inputs is neither reproducible nor welcome on someone
else's quota.  ``scripts/fetch_data.py`` writes this layout once; training
reads it as often as it likes.

    <data-dir>/
      readings.parquet            ts, station_id, rainfall_mm
      stations.parquet            station_id, station_name, longitude, latitude
      alerts.parquet              alert_id, ts_start, ts_end, ...
      flood_prone_points.csv      optional, geocoded PUB location list
      flood_prone_areas.csv       optional, annual hectares
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..schema import TIMEZONE

_TABLES = ("readings", "stations", "alerts")


def _write(frame: pd.DataFrame, stem: Path) -> Path:
    """Write Parquet when an engine is available, else CSV."""
    try:
        path = stem.with_suffix(".parquet")
        frame.to_parquet(path, index=False)
        return path
    except Exception:
        path = stem.with_suffix(".csv")
        frame.to_csv(path, index=False)
        return path


def _read(stem: Path) -> pd.DataFrame | None:
    for suffix in (".parquet", ".csv"):
        path = stem.with_suffix(suffix)
        if path.exists():
            if suffix == ".parquet":
                return pd.read_parquet(path)
            return pd.read_csv(path)
    return None


def save_canonical(
    directory: str | Path,
    readings: pd.DataFrame,
    stations: pd.DataFrame,
    alerts: pd.DataFrame,
    flood_prone_points: pd.DataFrame | None = None,
    flood_prone_areas: pd.DataFrame | None = None,
) -> dict[str, str]:
    """Persist the canonical tables; returns the paths written."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    written = {
        "readings": str(_write(readings, directory / "readings")),
        "stations": str(_write(stations, directory / "stations")),
        "alerts": str(_write(alerts, directory / "alerts")),
    }
    if flood_prone_points is not None:
        path = directory / "flood_prone_points.csv"
        flood_prone_points.to_csv(path, index=False)
        written["flood_prone_points"] = str(path)
    if flood_prone_areas is not None:
        path = directory / "flood_prone_areas.csv"
        flood_prone_areas.to_csv(path, index=False)
        written["flood_prone_areas"] = str(path)
    return written


def load_canonical(directory: str | Path) -> dict[str, pd.DataFrame]:
    """Load the staged tables, restoring Singapore-time timestamps."""
    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"{directory} does not exist; run scripts/fetch_data.py")

    tables: dict[str, pd.DataFrame] = {}
    for name in _TABLES:
        frame = _read(directory / name)
        if frame is None:
            raise FileNotFoundError(
                f"{directory}/{name}.(parquet|csv) is missing; "
                "run scripts/fetch_data.py to stage the datasets"
            )
        tables[name] = frame

    tables["readings"] = _localise(tables["readings"], ["ts"])
    tables["alerts"] = _localise(tables["alerts"], ["ts_start", "ts_end"])

    points = directory / "flood_prone_points.csv"
    if points.exists():
        from .flood_prone import load_flood_prone_points

        tables["flood_prone_points"] = load_flood_prone_points(points)

    areas = directory / "flood_prone_areas.csv"
    if areas.exists():
        from .flood_prone import load_flood_prone_areas

        tables["flood_prone_areas"] = load_flood_prone_areas(areas)

    return tables


def _localise(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy()
    for column in columns:
        if column not in out.columns:
            continue
        ts = pd.to_datetime(out[column], errors="coerce", format="mixed")
        if getattr(ts.dt, "tz", None) is None:
            ts = ts.dt.tz_localize(TIMEZONE, ambiguous="NaT", nonexistent="NaT")
        else:
            ts = ts.dt.tz_convert(TIMEZONE)
        out[column] = ts
    return out
