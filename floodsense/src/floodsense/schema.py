"""Canonical column names and dataset identifiers.

Everything downstream of ``floodsense.ingest`` speaks the canonical schema
defined here, so a new source only needs a loader that renames into it.

Dataset identifiers are the real data.gov.sg ids for the four official
FloodSense datasets.  They are recorded here so the ingestion layer never
hard-codes an id inline.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------
# Canonical schemas
# --------------------------------------------------------------------------

#: One rainfall observation from one station.  ``rainfall_mm`` is the total
#: depth over the 5-minute interval *ending* at ``ts``.
RAINFALL_COLUMNS: Final[tuple[str, ...]] = (
    "ts",            # tz-aware datetime (Asia/Singapore)
    "station_id",    # str, e.g. "S50"
    "rainfall_mm",   # float32, mm per 5 min
)

#: Station metadata.
STATION_COLUMNS: Final[tuple[str, ...]] = (
    "station_id",
    "station_name",
    "longitude",
    "latitude",
)

#: One PUB flood alert event.
ALERT_COLUMNS: Final[tuple[str, ...]] = (
    "alert_id",
    "ts_start",      # tz-aware datetime the alert was raised
    "ts_end",        # tz-aware datetime it cleared (may be NaT while active)
    "location_name",
    "longitude",
    "latitude",
    "severity",      # as published by PUB
    "urgency",       # as published by PUB
)

#: Annual national flood-prone extent (PUB).  Two columns only - this is an
#: aggregate trend series, NOT a geospatial layer.  See ingest/flood_prone.py.
FLOOD_PRONE_COLUMNS: Final[tuple[str, ...]] = ("year", "hectares")

#: A flood-prone *location* (geocoded from PUB's published list).  Used for
#: static spatial vulnerability features.
FLOOD_PRONE_POINT_COLUMNS: Final[tuple[str, ...]] = (
    "location_name",
    "longitude",
    "latitude",
    "as_of",         # date of the PUB list this row came from
)

# --------------------------------------------------------------------------
# Official data.gov.sg dataset identifiers
# --------------------------------------------------------------------------

#: NEA, "Historical Rainfall across Singapore" - annual CSV collection
#: (collection 2279), 5-minute station totals.  Dec 2016 - Dec 2024.
#: Only the ids verified at build time are listed; the loader accepts any
#: ``d_*`` id so the remaining years can be added from the collection page.
HISTORICAL_RAINFALL_DATASETS: Final[dict[int, str]] = {
    2019: "d_61995f092320e7155b7528050880b502",
    2020: "d_9e7de44094f876f6804b8b5bcee45c81",
    2024: "d_a0b69d3e02576a1fd0ab673e71f83507",
}

#: NEA, "Rainfall across Singapore (API)" - real-time, 5-minute refresh.
REALTIME_RAINFALL_DATASET: Final[str] = "d_6580738cdd7db79374ed3152159fbd69"

#: PUB, "Flood Alerts across Singapore (API)" - real-time alert events.
FLOOD_ALERTS_DATASET: Final[str] = "d_f1404e08587ce555b9ea3f565e2eb9a3"

#: PUB, "Flood Prone Areas" - annual hectares, 2022-2025.
FLOOD_PRONE_AREAS_DATASET: Final[str] = "d_c4aed98f1533eb3a66f65dbb1a30da46"

#: The ``Reading Type`` value that marks a 5-minute rainfall total in the
#: historical CSVs.  Rows with any other reading type are dropped.
HISTORICAL_READING_TYPE: Final[str] = "TB1 Rainfall 5 Minute Total F"

#: Column names in the historical rainfall CSVs, mapped to the canonical
#: schema. Keys are *normalised* headers (lower-cased, trimmed, spaces turned
#: into underscores), because the published exports are not consistent: the
#: dataset page documents title-case headers ("Station Id") while the CSV
#: download delivers snake_case ("station_id"). Normalising first accepts
#: both without a second mapping table.
HISTORICAL_CSV_RENAME: Final[dict[str, str]] = {
    "timestamp": "ts",
    "station_id": "station_id",
    "station_name": "station_name",
    "location_longitude": "longitude",
    "location_latitude": "latitude",
    "reading_value": "rainfall_mm",
    "reading_type": "reading_type",
    "reading_unit": "reading_unit",
}


def normalise_header(name: str) -> str:
    """Lower-case, trim and underscore a CSV header for lookup."""
    return str(name).strip().lower().replace(" ", "_")

#: Observation cadence of both the historical CSVs and the real-time API.
STEP_MINUTES: Final[int] = 5

#: Singapore local time zone - every published timestamp is SGT (ISO 8601).
TIMEZONE: Final[str] = "Asia/Singapore"

#: Bounding box of mainland Singapore (longitude/latitude degrees).  Used to
#: reject obviously malformed coordinates and to place synthetic stations.
SG_BOUNDS: Final[dict[str, float]] = {
    "lon_min": 103.60,
    "lon_max": 104.09,
    "lat_min": 1.15,
    "lat_max": 1.48,
}
