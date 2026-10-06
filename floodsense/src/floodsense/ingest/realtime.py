"""Live feeds: NEA 5-minute rainfall and PUB flood alerts.

The rainfall endpoint and its response shape are stable and documented on
the dataset page.  The flood-alerts endpoint is newer (PUB released alerts
by API in November 2025) and its field spellings are **not** assumed here:
``parse_flood_alerts`` accepts several plausible key names for the same
quantity and tells you what it could not map, rather than silently
producing empty columns.  Point ``FLOOD_ALERTS_URL`` at whatever the
dataset page documents and the parser adapts.

data.gov.sg introduced rate limits on its real-time APIs at the end of
2025, with API keys the supported way to avoid throttling.  Pass one via
``api_key`` and it is sent as a header.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import pandas as pd

from ..schema import TIMEZONE

#: NEA, "Rainfall across Singapore (API)" - 5-minute station totals.
RAINFALL_URL = "https://api-open.data.gov.sg/v2/real-time/api/rainfall"

#: PUB, "Flood Alerts across Singapore (API)".  Confirm against the dataset
#: page before relying on it; override with the ``url`` argument.
FLOOD_ALERTS_URL = "https://api-open.data.gov.sg/v2/real-time/api/flood-alerts"

_ALERT_KEYS = {
    "alert_id": ("id", "alertId", "alert_id", "eventId"),
    "ts_start": ("startTime", "start_time", "timestamp", "effective", "onset", "sent"),
    "ts_end": ("endTime", "end_time", "expires", "cleared", "clearedTime"),
    "location_name": ("location", "locationName", "name", "areaDesc", "description"),
    "severity": ("severity", "level", "alertLevel"),
    "urgency": ("urgency",),
}


def _get_json(
    url: str,
    params: dict[str, str] | None = None,
    *,
    api_key: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/json")
    if api_key:
        request.add_header("x-api-key", api_key)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # surface the body: it explains why
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {detail}") from exc


# --------------------------------------------------------------------------
# Rainfall
# --------------------------------------------------------------------------


def fetch_rainfall(
    date: str | None = None,
    *,
    url: str = RAINFALL_URL,
    api_key: str | None = None,
    pagination_token: str | None = None,
    max_pages: int = 50,
    timeout: float = 30.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch rainfall readings.

    Args:
        date: ``YYYY-MM-DD`` for one day, or ``None`` for the latest
            reading.  The API paginates a full day, so pages are followed
            up to ``max_pages``.
        pagination_token: resume a previous pull.

    Returns:
        ``(readings, stations)`` in the canonical schema.
    """
    payloads = []
    params: dict[str, str] = {}
    if date:
        params["date"] = date
    if pagination_token:
        params["paginationToken"] = pagination_token

    for _ in range(max_pages):
        payload = _get_json(url, params or None, api_key=api_key, timeout=timeout)
        payloads.append(payload)
        token = _dig(payload, ("data", "paginationToken"))
        if not token:
            break
        params = dict(params, paginationToken=str(token))
        if date:
            params["date"] = date

    return parse_rainfall(payloads)


def parse_rainfall(
    payloads: list[dict[str, Any]] | dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse one or more rainfall API payloads into canonical frames.

    The v2 response nests ``data.stations`` (id, name, location) and
    ``data.readings`` (one entry per timestamp, each with a list of
    ``{stationId, value}``).
    """
    if isinstance(payloads, dict):
        payloads = [payloads]

    station_rows: dict[str, dict[str, Any]] = {}
    reading_rows: list[dict[str, Any]] = []

    for payload in payloads:
        for station in _dig(payload, ("data", "stations")) or []:
            sid = station.get("id") or station.get("deviceId")
            if not sid:
                continue
            location = station.get("location") or {}
            station_rows[str(sid)] = {
                "station_id": str(sid),
                "station_name": station.get("name", str(sid)),
                "longitude": _as_float(location.get("longitude")),
                "latitude": _as_float(location.get("latitude")),
            }

        for reading in _dig(payload, ("data", "readings")) or []:
            ts = reading.get("timestamp")
            for item in reading.get("data") or []:
                sid = item.get("stationId") or item.get("station_id")
                if sid is None:
                    continue
                reading_rows.append(
                    {
                        "ts": ts,
                        "station_id": str(sid),
                        "rainfall_mm": _as_float(item.get("value")),
                    }
                )

    readings = pd.DataFrame(reading_rows, columns=["ts", "station_id", "rainfall_mm"])
    if not readings.empty:
        readings["ts"] = _to_sgt(readings["ts"])
        readings["rainfall_mm"] = readings["rainfall_mm"].astype("float32")
        readings = readings.dropna(subset=["ts"]).reset_index(drop=True)

    stations = pd.DataFrame(
        list(station_rows.values()),
        columns=["station_id", "station_name", "longitude", "latitude"],
    )
    return readings, stations


# --------------------------------------------------------------------------
# Flood alerts
# --------------------------------------------------------------------------


def fetch_flood_alerts(
    *,
    url: str = FLOOD_ALERTS_URL,
    api_key: str | None = None,
    timeout: float = 30.0,
    params: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Fetch current PUB flood alerts in the canonical schema.

    Note: this dataset covers flood *alerts*.  PUB flood *warning* notices
    are a separate publication and are not included.
    """
    return parse_flood_alerts(
        _get_json(url, params, api_key=api_key, timeout=timeout)
    )


def parse_flood_alerts(payload: dict[str, Any]) -> pd.DataFrame:
    """Map an alerts payload onto the canonical alert schema.

    Field names are resolved against ``_ALERT_KEYS``, so a reasonable
    variation in spelling is handled.  Records whose coordinates cannot be
    found are dropped - an alert with no location cannot be associated with
    a station - and the count of dropped records is reported through the
    frame's ``attrs``.
    """
    records = _find_records(payload)
    rows, dropped = [], 0

    for i, record in enumerate(records):
        lon, lat = _find_coordinates(record)
        if lon is None or lat is None:
            dropped += 1
            continue
        rows.append(
            {
                "alert_id": str(_first(record, _ALERT_KEYS["alert_id"], f"alert-{i}")),
                "ts_start": _first(record, _ALERT_KEYS["ts_start"], None),
                "ts_end": _first(record, _ALERT_KEYS["ts_end"], None),
                "location_name": _first(record, _ALERT_KEYS["location_name"], ""),
                "longitude": lon,
                "latitude": lat,
                "severity": _first(record, _ALERT_KEYS["severity"], ""),
                "urgency": _first(record, _ALERT_KEYS["urgency"], ""),
            }
        )

    frame = pd.DataFrame(
        rows,
        columns=[
            "alert_id", "ts_start", "ts_end", "location_name",
            "longitude", "latitude", "severity", "urgency",
        ],
    )
    if not frame.empty:
        frame["ts_start"] = _to_sgt(frame["ts_start"])
        frame["ts_end"] = _to_sgt(frame["ts_end"])
        frame = frame.dropna(subset=["ts_start"]).reset_index(drop=True)

    frame.attrs["dropped_without_location"] = dropped
    frame.attrs["records_seen"] = len(records)
    return frame


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _dig(payload: Any, path: tuple[str, ...]) -> Any:
    node = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _find_records(payload: Any) -> list[dict[str, Any]]:
    """Locate the list of alert records inside an unknown envelope."""
    for path in (
        ("data", "records"),
        ("data", "alerts"),
        ("data", "events"),
        ("data", "items"),
        ("records",),
        ("alerts",),
        ("items",),
        ("features",),
    ):
        node = _dig(payload, path)
        if isinstance(node, list) and node:
            return [_unwrap(item) for item in node if isinstance(item, dict)]
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return [_unwrap(item) for item in data if isinstance(item, dict)]
    return []


def _unwrap(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a GeoJSON feature into a flat record, if that is what it is."""
    if "properties" in item and isinstance(item["properties"], dict):
        merged = dict(item["properties"])
        geometry = item.get("geometry")
        if isinstance(geometry, dict):
            merged["_geometry"] = geometry
        return merged
    return item


def _find_coordinates(record: dict[str, Any]) -> tuple[float | None, float | None]:
    """Pull a lon/lat pair out of the shapes these feeds actually use."""
    location = record.get("location")
    if isinstance(location, dict):
        lon = _as_float(location.get("longitude") or location.get("lon"))
        lat = _as_float(location.get("latitude") or location.get("lat"))
        if lon is not None and lat is not None:
            return lon, lat

    lon = _as_float(record.get("longitude") or record.get("lon") or record.get("x"))
    lat = _as_float(record.get("latitude") or record.get("lat") or record.get("y"))
    if lon is not None and lat is not None:
        return lon, lat

    geometry = record.get("_geometry") or record.get("geometry")
    if isinstance(geometry, dict):
        coords = geometry.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            # GeoJSON order is [longitude, latitude].
            return _as_float(coords[0]), _as_float(coords[1])

    return None, None


def _first(record: dict[str, Any], keys: tuple[str, ...], default: Any) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return default


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_sgt(series: pd.Series) -> pd.Series:
    ts = pd.to_datetime(series, errors="coerce", format="mixed", utc=False)
    try:
        tz = ts.dt.tz
    except AttributeError:
        return pd.to_datetime(pd.Series([pd.NaT] * len(series), index=series.index))
    if tz is None:
        return ts.dt.tz_localize(TIMEZONE, ambiguous="NaT", nonexistent="NaT")
    return ts.dt.tz_convert(TIMEZONE)
