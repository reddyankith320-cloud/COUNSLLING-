"""NEA "Historical Rainfall across Singapore" - annual CSVs, 2016-2024.

Published as one CSV per year under data.gov.sg collection 2279, at
5-minute station resolution.  The 2024 file alone is ~6.4 million rows, so
the loader reads in chunks, filters to the rainfall reading type and
down-casts before concatenating.

Published columns (renamed into the canonical schema by
``schema.HISTORICAL_CSV_RENAME``): ``Date``, ``Timestamp``,
``Update Timestamp``, ``Station Id``, ``Station Name``,
``Station Device Id``, ``Location Longitude``, ``Location Latitude``,
``Reading Update Timestamp``, ``Reading Value``, ``Reading Type``,
``Reading Unit``.

NEA states these files may contain missing records and have not been
through the quality-control applied to climate records, which is why
``RainGrid`` reindexes onto a regular grid and keeps an explicit gap mask.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..schema import (
    HISTORICAL_CSV_RENAME,
    HISTORICAL_READING_TYPE,
    SG_BOUNDS,
    TIMEZONE,
    normalise_header,
)

#: data.gov.sg issues a signed CSV URL through this endpoint.
POLL_DOWNLOAD_URL = (
    "https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/poll-download"
)


def load_historical_csv(
    path: str | Path,
    *,
    chunksize: int = 500_000,
    reading_type: str | None = HISTORICAL_READING_TYPE,
    stations: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read one annual CSV.

    Args:
        path: the CSV (optionally ``.gz``/``.zip`` - pandas infers).
        chunksize: rows per chunk; keeps peak memory near 100 MB.
        reading_type: keep only this ``Reading Type``.  ``None`` keeps all.
        stations: optional allow-list of station ids.

    Returns:
        ``(readings, stations)`` in the canonical schema.
    """
    path = Path(path)
    reading_frames: list[pd.DataFrame] = []
    station_frames: list[pd.DataFrame] = []

    for chunk in pd.read_csv(path, chunksize=chunksize, low_memory=False):
        chunk = chunk.rename(columns=lambda c: normalise_header(c))
        chunk = chunk.rename(columns=HISTORICAL_CSV_RENAME)

        missing = {"ts", "station_id", "rainfall_mm"} - set(chunk.columns)
        if missing:
            raise ValueError(
                f"{path} is missing the columns {sorted(missing)} after "
                f"normalisation; headers seen: {sorted(chunk.columns)}. The "
                "published exports use either title-case or snake_case - a "
                "third spelling needs adding to HISTORICAL_CSV_RENAME."
            )

        if reading_type is not None and "reading_type" in chunk.columns:
            chunk = chunk.loc[chunk["reading_type"] == reading_type]
        if stations is not None:
            chunk = chunk.loc[chunk["station_id"].isin(stations)]
        if chunk.empty:
            continue

        if {"station_id", "longitude", "latitude"}.issubset(chunk.columns):
            cols = ["station_id", "longitude", "latitude"]
            if "station_name" in chunk.columns:
                cols.append("station_name")
            station_frames.append(chunk.loc[:, cols].drop_duplicates("station_id"))

        reading_frames.append(
            chunk.loc[:, ["ts", "station_id", "rainfall_mm"]].astype(
                {"rainfall_mm": "float32"}
            )
        )

    if not reading_frames:
        raise ValueError(
            f"{path} yielded no rows; check the Reading Type filter "
            f"({reading_type!r}) and the column names"
        )

    readings = pd.concat(reading_frames, ignore_index=True)
    readings["ts"] = pd.to_datetime(readings["ts"], errors="coerce", format="mixed")
    if readings["ts"].dt.tz is None:
        readings["ts"] = readings["ts"].dt.tz_localize(TIMEZONE)
    else:
        readings["ts"] = readings["ts"].dt.tz_convert(TIMEZONE)
    readings = readings.dropna(subset=["ts", "rainfall_mm"])

    station_meta = (
        pd.concat(station_frames, ignore_index=True).drop_duplicates("station_id")
        if station_frames
        else pd.DataFrame(columns=["station_id", "longitude", "latitude", "station_name"])
    )
    if "station_name" not in station_meta.columns:
        station_meta["station_name"] = station_meta["station_id"]

    return readings.reset_index(drop=True), _clean_stations(station_meta)


def load_historical_dir(
    directory: str | Path, pattern: str = "*.csv*", **kwargs
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read and concatenate every annual CSV in a directory."""
    directory = Path(directory)
    files = sorted(directory.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no files matching {pattern!r} under {directory}")

    readings, stations = [], []
    for f in files:
        r, s = load_historical_csv(f, **kwargs)
        readings.append(r)
        stations.append(s)

    return (
        pd.concat(readings, ignore_index=True)
        .sort_values(["ts", "station_id"])
        .reset_index(drop=True),
        pd.concat(stations, ignore_index=True).drop_duplicates("station_id"),
    )


def _clean_stations(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop stations whose coordinates fall outside Singapore."""
    out = frame.dropna(subset=["longitude", "latitude"]).copy()
    inside = (
        out["longitude"].between(SG_BOUNDS["lon_min"], SG_BOUNDS["lon_max"])
        & out["latitude"].between(SG_BOUNDS["lat_min"], SG_BOUNDS["lat_max"])
    )
    return out.loc[inside].reset_index(drop=True)


def resolve_download_url(dataset_id: str, timeout: float = 30.0) -> str:
    """Ask data.gov.sg for a signed CSV URL for ``dataset_id``.

    Requires outbound access to ``api-open.data.gov.sg``.  Kept separate
    from the readers so the parsing path stays testable offline.
    """
    import json
    import urllib.request

    url = POLL_DOWNLOAD_URL.format(dataset_id=dataset_id)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    for path in (("data", "url"), ("data", "downloadUrl"), ("url",)):
        node: object = payload
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, str) and node.startswith("http"):
            return node

    raise RuntimeError(
        f"no download URL in the response for {dataset_id}: {payload!r}"
    )
