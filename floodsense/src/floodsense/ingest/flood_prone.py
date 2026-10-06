"""PUB flood-prone-area data.

There are two distinct things here, and conflating them is a trap:

**"Flood Prone Areas" (data.gov.sg, dataset d_c4aed98f...)** is an annual
*national aggregate*: two columns, ``year`` and ``hectares``, four rows for
2022-2025.  It is the right source for the required three-year trend and
tells you nothing about *where*.

**PUB's published "List of Flood Prone Areas in Singapore"** is the
location-level list (a PDF refreshed periodically, on the order of 35
locations in the 2024-2025 editions).  Geocoding that list is what gives
per-station spatial vulnerability features.

So the trend chart comes from the dataset, and the spatial features come
from the geocoded list plus the historical alert record.  The aggregate
series has four rows and must never be used as a spatial layer.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..schema import FLOOD_PRONE_AREAS_DATASET, SG_BOUNDS

#: CKAN datastore endpoint backing the tabular datasets.
DATASTORE_URL = "https://data.gov.sg/api/action/datastore_search"

#: The published national series, recorded so the trend is available
#: offline and so a fetch can be sanity-checked against it.
#: Source: PUB, "Flood Prone Areas" (data.gov.sg), Jan 2022 - Jan 2025.
PUBLISHED_FLOOD_PRONE_HECTARES: dict[int, float] = {
    2022: 27.0,
    2023: 24.1,
    2024: 23.6,
    2025: 23.3,
}


def load_flood_prone_areas(
    path: str | Path | None = None, *, fallback: bool = True
) -> pd.DataFrame:
    """Annual national flood-prone extent.

    Args:
        path: a CSV previously downloaded from data.gov.sg.  When omitted,
            the published series above is returned (if ``fallback``).

    Returns:
        ``year`` (int), ``hectares`` (float), sorted by year.
    """
    if path is not None:
        frame = pd.read_csv(path)
        frame.columns = [str(c).strip().lower() for c in frame.columns]
        if "year" not in frame.columns:
            raise ValueError(f"{path} has no 'year' column: {list(frame.columns)}")
        value_col = next(
            (c for c in frame.columns if "hect" in c or c in {"value", "area"}), None
        )
        if value_col is None:
            raise ValueError(
                f"{path} has no hectares column: {list(frame.columns)}"
            )
        out = frame.loc[:, ["year", value_col]].rename(
            columns={value_col: "hectares"}
        )
    elif fallback:
        out = pd.DataFrame(
            {
                "year": list(PUBLISHED_FLOOD_PRONE_HECTARES),
                "hectares": list(PUBLISHED_FLOOD_PRONE_HECTARES.values()),
            }
        )
    else:
        raise ValueError("no path given and fallback disabled")

    out["year"] = out["year"].astype(int)
    out["hectares"] = out["hectares"].astype(float)
    return out.sort_values("year").reset_index(drop=True)


def flood_prone_trend(areas: pd.DataFrame | None = None) -> dict[str, float]:
    """Summarise the multi-year trend for the dashboard's analytics panel."""
    areas = load_flood_prone_areas() if areas is None else areas.sort_values("year")
    if areas.empty:
        return {}

    first, last = areas.iloc[0], areas.iloc[-1]
    span_years = max(int(last["year"]) - int(first["year"]), 1)
    change = float(last["hectares"]) - float(first["hectares"])

    return {
        "first_year": int(first["year"]),
        "last_year": int(last["year"]),
        "first_hectares": float(first["hectares"]),
        "last_hectares": float(last["hectares"]),
        "absolute_change_ha": change,
        "percent_change": 100.0 * change / float(first["hectares"]),
        "mean_annual_change_ha": change / span_years,
    }


def fetch_flood_prone_areas(
    dataset_id: str = FLOOD_PRONE_AREAS_DATASET,
    *,
    limit: int = 1000,
    timeout: float = 30.0,
) -> pd.DataFrame:
    """Pull the annual series live from the CKAN datastore."""
    import json
    import urllib.parse
    import urllib.request

    url = f"{DATASTORE_URL}?{urllib.parse.urlencode({'resource_id': dataset_id, 'limit': limit})}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    records = (payload.get("result") or {}).get("records") or []
    if not records:
        raise RuntimeError(f"datastore returned no records for {dataset_id}")

    frame = pd.DataFrame(records)
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    value_col = next((c for c in frame.columns if "hect" in c), None)
    if "year" not in frame.columns or value_col is None:
        raise RuntimeError(f"unexpected columns from datastore: {list(frame.columns)}")

    out = frame.loc[:, ["year", value_col]].rename(columns={value_col: "hectares"})
    out["year"] = out["year"].astype(int)
    out["hectares"] = out["hectares"].astype(float)
    return out.sort_values("year").reset_index(drop=True)


def load_flood_prone_points(path: str | Path) -> pd.DataFrame:
    """Load the geocoded PUB flood-prone *location* list.

    Expected columns (case-insensitive): ``location_name`` (or ``location``
    / ``name``), ``longitude``, ``latitude``, and optionally ``as_of``.
    Produce this file by geocoding PUB's published list - it is not
    available as a coordinate dataset.

    Rows outside Singapore's bounding box are dropped: a geocoder that
    silently resolves "Dunearn Road" to another country would otherwise
    corrupt every spatial feature.
    """
    path = Path(path)
    frame = pd.read_csv(path)
    frame.columns = [str(c).strip().lower().replace(" ", "_") for c in frame.columns]

    name_col = next(
        (c for c in ("location_name", "location", "name", "area") if c in frame.columns),
        None,
    )
    if name_col is None or not {"longitude", "latitude"}.issubset(frame.columns):
        raise ValueError(
            f"{path} needs a name column plus longitude/latitude; "
            f"found {list(frame.columns)}"
        )

    out = frame.rename(columns={name_col: "location_name"})
    out = out.dropna(subset=["longitude", "latitude"])
    out["longitude"] = out["longitude"].astype(float)
    out["latitude"] = out["latitude"].astype(float)

    inside = (
        out["longitude"].between(SG_BOUNDS["lon_min"], SG_BOUNDS["lon_max"])
        & out["latitude"].between(SG_BOUNDS["lat_min"], SG_BOUNDS["lat_max"])
    )
    dropped = int((~inside).sum())
    out = out.loc[inside].copy()
    if "as_of" not in out.columns:
        out["as_of"] = ""

    out = out.loc[:, ["location_name", "longitude", "latitude", "as_of"]]
    out.attrs["dropped_outside_singapore"] = dropped
    return out.reset_index(drop=True)
