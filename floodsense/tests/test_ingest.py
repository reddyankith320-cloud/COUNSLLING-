"""Ingestion: canonical-schema conformance and defensive parsing.

The real feeds cannot be reached from a test run, so these exercise the
parsers against recorded-shape payloads.  The flood-alerts parser is
deliberately tested against several field spellings and envelope shapes,
because the PUB alerts API is new and its exact schema should be confirmed
against the dataset page rather than assumed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from floodsense.grid import RainGrid
from floodsense.ingest.flood_prone import (
    PUBLISHED_FLOOD_PRONE_HECTARES,
    flood_prone_trend,
    load_flood_prone_areas,
    load_flood_prone_points,
)
from floodsense.ingest.historical import load_historical_csv
from floodsense.ingest.local import load_canonical, save_canonical
from floodsense.ingest.realtime import parse_flood_alerts, parse_rainfall
from floodsense.schema import ALERT_COLUMNS, HISTORICAL_READING_TYPE


class TestHistoricalCsv:
    def _write(self, tmp_path, rows: list[dict]) -> str:
        path = tmp_path / "rainfall_2024.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        return str(path)

    def _row(self, ts: str, station: str = "S50", value: float = 0.4, **kwargs):
        row = {
            "Timestamp": ts,
            "Station Id": station,
            "Station Name": f"Station {station}",
            "Location Longitude": 103.8,
            "Location Latitude": 1.35,
            "Reading Value": value,
            "Reading Type": HISTORICAL_READING_TYPE,
            "Reading Unit": "mm",
        }
        row.update(kwargs)
        return row

    def test_renames_into_the_canonical_schema(self, tmp_path):
        path = self._write(
            tmp_path,
            [
                self._row("2024-01-01T00:00:00+08:00"),
                self._row("2024-01-01T00:05:00+08:00", value=1.2),
            ],
        )
        readings, stations = load_historical_csv(path)

        assert list(readings.columns) == ["ts", "station_id", "rainfall_mm"]
        assert len(readings) == 2
        assert readings["rainfall_mm"].dtype == np.float32
        assert stations.loc[0, "station_id"] == "S50"

    def test_timestamps_land_in_singapore_time(self, tmp_path):
        path = self._write(tmp_path, [self._row("2024-01-01T00:00:00+08:00")])
        readings, _ = load_historical_csv(path)
        assert str(readings["ts"].dt.tz) == "Asia/Singapore"

    def test_naive_timestamps_are_assumed_sgt(self, tmp_path):
        path = self._write(tmp_path, [self._row("2024-01-01 00:00:00")])
        readings, _ = load_historical_csv(path)
        assert readings["ts"].iloc[0].hour == 0
        assert str(readings["ts"].dt.tz) == "Asia/Singapore"

    def test_other_reading_types_are_dropped(self, tmp_path):
        path = self._write(
            tmp_path,
            [
                self._row("2024-01-01T00:00:00+08:00"),
                self._row("2024-01-01T00:05:00+08:00", **{"Reading Type": "Air Temperature"}),
            ],
        )
        readings, _ = load_historical_csv(path)
        assert len(readings) == 1

    def test_station_allow_list(self, tmp_path):
        path = self._write(
            tmp_path,
            [
                self._row("2024-01-01T00:00:00+08:00", station="S50"),
                self._row("2024-01-01T00:00:00+08:00", station="S99"),
            ],
        )
        readings, _ = load_historical_csv(path, stations={"S50"})
        assert set(readings["station_id"]) == {"S50"}

    def test_stations_outside_singapore_are_dropped(self, tmp_path):
        path = self._write(
            tmp_path,
            [
                self._row("2024-01-01T00:00:00+08:00"),
                self._row(
                    "2024-01-01T00:00:00+08:00",
                    station="BAD",
                    **{"Location Longitude": 0.0, "Location Latitude": 0.0},
                ),
            ],
        )
        _, stations = load_historical_csv(path)
        assert set(stations["station_id"]) == {"S50"}

    def test_empty_result_raises_a_diagnostic_error(self, tmp_path):
        path = self._write(
            tmp_path,
            [self._row("2024-01-01T00:00:00+08:00", **{"Reading Type": "Wind Speed"})],
        )
        with pytest.raises(ValueError, match="Reading Type"):
            load_historical_csv(path)

    def test_chunking_does_not_change_the_result(self, tmp_path):
        rows = [
            self._row(f"2024-01-01T00:{m:02d}:00+08:00", value=m / 10.0)
            for m in range(0, 50, 5)
        ]
        path = self._write(tmp_path, rows)
        a, _ = load_historical_csv(path, chunksize=2)
        b, _ = load_historical_csv(path, chunksize=10_000)
        assert len(a) == len(b) == len(rows)
        assert a["rainfall_mm"].sum() == pytest.approx(b["rainfall_mm"].sum())


class TestRainfallApi:
    def _payload(self) -> dict:
        return {
            "code": 0,
            "data": {
                "stations": [
                    {
                        "id": "S50",
                        "deviceId": "S50",
                        "name": "Clementi Road",
                        "location": {"latitude": 1.3337, "longitude": 103.7768},
                    }
                ],
                "readings": [
                    {
                        "timestamp": "2026-10-06T14:35:00+08:00",
                        "data": [{"stationId": "S50", "value": 0.6}],
                    },
                    {
                        "timestamp": "2026-10-06T14:40:00+08:00",
                        "data": [{"stationId": "S50", "value": 1.4}],
                    },
                ],
                "readingType": "TB1 Rainfall 5 Minute Total F",
                "readingUnit": "mm",
            },
        }

    def test_parses_readings_and_stations(self):
        readings, stations = parse_rainfall(self._payload())
        assert list(readings.columns) == ["ts", "station_id", "rainfall_mm"]
        assert len(readings) == 2
        assert stations.loc[0, "station_name"] == "Clementi Road"
        assert stations.loc[0, "longitude"] == pytest.approx(103.7768)

    def test_multiple_pages_concatenate(self):
        readings, stations = parse_rainfall([self._payload(), self._payload()])
        assert len(readings) == 4
        assert len(stations) == 1          # de-duplicated

    def test_output_feeds_raingrid_directly(self):
        readings, stations = parse_rainfall(self._payload())
        grid = RainGrid.from_long(readings, stations)
        assert grid.n_stations == 1
        assert grid.n_steps == 2

    def test_empty_payload_yields_empty_frames(self):
        readings, stations = parse_rainfall({"data": {}})
        assert readings.empty and stations.empty
        assert list(readings.columns) == ["ts", "station_id", "rainfall_mm"]


class TestFloodAlertsApi:
    def test_nested_location_shape(self):
        payload = {
            "data": {
                "records": [
                    {
                        "id": "A1",
                        "startTime": "2026-10-06T14:00:00+08:00",
                        "endTime": "2026-10-06T15:00:00+08:00",
                        "location": {"latitude": 1.35, "longitude": 103.8},
                        "locationName": "Somewhere Road",
                        "severity": "Moderate",
                        "urgency": "Immediate",
                    }
                ]
            }
        }
        alerts = parse_flood_alerts(payload)
        assert len(alerts) == 1
        assert list(alerts.columns) == list(ALERT_COLUMNS)
        assert alerts.loc[0, "longitude"] == pytest.approx(103.8)
        assert str(alerts["ts_start"].dt.tz) == "Asia/Singapore"

    def test_flat_lat_lon_shape(self):
        payload = {
            "alerts": [
                {
                    "alertId": "A2",
                    "timestamp": "2026-10-06T14:00:00+08:00",
                    "lon": 103.8,
                    "lat": 1.35,
                    "description": "Flash flood",
                }
            ]
        }
        alerts = parse_flood_alerts(payload)
        assert len(alerts) == 1
        assert alerts.loc[0, "alert_id"] == "A2"

    def test_geojson_feature_shape(self):
        payload = {
            "features": [
                {
                    "properties": {
                        "id": "A3",
                        "sent": "2026-10-06T14:00:00+08:00",
                        "areaDesc": "Dunearn Road",
                    },
                    "geometry": {"type": "Point", "coordinates": [103.8, 1.35]},
                }
            ]
        }
        alerts = parse_flood_alerts(payload)
        assert len(alerts) == 1
        # GeoJSON order is [lon, lat] and must not be swapped.
        assert alerts.loc[0, "longitude"] == pytest.approx(103.8)
        assert alerts.loc[0, "latitude"] == pytest.approx(1.35)

    def test_records_without_location_are_dropped_and_counted(self):
        payload = {
            "data": {
                "records": [
                    {"id": "A4", "startTime": "2026-10-06T14:00:00+08:00"},
                    {
                        "id": "A5",
                        "startTime": "2026-10-06T14:00:00+08:00",
                        "longitude": 103.8,
                        "latitude": 1.35,
                    },
                ]
            }
        }
        alerts = parse_flood_alerts(payload)
        assert len(alerts) == 1
        assert alerts.attrs["dropped_without_location"] == 1
        assert alerts.attrs["records_seen"] == 2

    def test_unknown_envelope_yields_empty_frame(self):
        alerts = parse_flood_alerts({"something": "else"})
        assert alerts.empty
        assert list(alerts.columns) == list(ALERT_COLUMNS)


class TestFloodProne:
    def test_published_series_is_the_offline_fallback(self):
        areas = load_flood_prone_areas()
        assert list(areas["year"]) == [2022, 2023, 2024, 2025]
        assert areas.loc[0, "hectares"] == pytest.approx(27.0)
        assert dict(zip(areas["year"], areas["hectares"])) == PUBLISHED_FLOOD_PRONE_HECTARES

    def test_trend_summary(self):
        trend = flood_prone_trend()
        assert trend["first_year"] == 2022
        assert trend["last_year"] == 2025
        assert trend["absolute_change_ha"] == pytest.approx(-3.7, abs=1e-6)
        assert trend["percent_change"] < 0

    def test_reads_a_downloaded_csv(self, tmp_path):
        path = tmp_path / "areas.csv"
        pd.DataFrame({"year": [2023, 2022], "hectares": [24.1, 27.0]}).to_csv(
            path, index=False
        )
        areas = load_flood_prone_areas(path)
        assert list(areas["year"]) == [2022, 2023]      # sorted

    def test_rejects_a_csv_without_hectares(self, tmp_path):
        path = tmp_path / "bad.csv"
        pd.DataFrame({"year": [2022], "something": [1]}).to_csv(path, index=False)
        with pytest.raises(ValueError, match="hectares"):
            load_flood_prone_areas(path)

    def test_points_outside_singapore_are_dropped(self, tmp_path):
        path = tmp_path / "points.csv"
        pd.DataFrame(
            {
                "location_name": ["Good", "Geocoder error"],
                "longitude": [103.8, -74.0],
                "latitude": [1.35, 40.7],
            }
        ).to_csv(path, index=False)

        points = load_flood_prone_points(path)
        assert len(points) == 1
        assert points.attrs["dropped_outside_singapore"] == 1
        assert list(points.columns) == [
            "location_name", "longitude", "latitude", "as_of",
        ]

    def test_points_accepts_alternative_name_columns(self, tmp_path):
        path = tmp_path / "points.csv"
        pd.DataFrame(
            {"Location": ["Dunearn Road"], "Longitude": [103.8], "Latitude": [1.35]}
        ).to_csv(path, index=False)
        points = load_flood_prone_points(path)
        assert points.loc[0, "location_name"] == "Dunearn Road"


class TestLocalStaging:
    def test_round_trip_preserves_timestamps(self, tmp_path):
        readings = pd.DataFrame(
            {
                "ts": pd.to_datetime(
                    ["2024-01-01T00:00:00+08:00", "2024-01-01T00:05:00+08:00"]
                ).tz_convert("Asia/Singapore"),
                "station_id": ["S50", "S50"],
                "rainfall_mm": np.array([0.2, 0.4], dtype=np.float32),
            }
        )
        stations = pd.DataFrame(
            {
                "station_id": ["S50"],
                "station_name": ["Clementi"],
                "longitude": [103.78],
                "latitude": [1.33],
            }
        )
        alerts = pd.DataFrame(
            {
                "alert_id": ["A1"],
                "ts_start": pd.to_datetime(["2024-01-01T01:00:00+08:00"]).tz_convert(
                    "Asia/Singapore"
                ),
                "ts_end": pd.to_datetime(["2024-01-01T02:00:00+08:00"]).tz_convert(
                    "Asia/Singapore"
                ),
                "location_name": ["Somewhere"],
                "longitude": [103.78],
                "latitude": [1.33],
                "severity": ["Moderate"],
                "urgency": ["Immediate"],
            }
        )

        save_canonical(tmp_path, readings, stations, alerts)
        tables = load_canonical(tmp_path)

        assert str(tables["readings"]["ts"].dt.tz) == "Asia/Singapore"
        assert str(tables["alerts"]["ts_start"].dt.tz) == "Asia/Singapore"
        assert tables["readings"]["ts"].iloc[0].hour == 0
        assert len(tables["stations"]) == 1

    def test_missing_directory_is_a_clear_error(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="fetch_data"):
            load_canonical(tmp_path / "nope")


class TestPubFloodAlertSchema:
    """The documented PUB flood-alert shape, from the dataset's OpenAPI spec.

    Two details here are easy to get wrong and both corrupt the labels: the
    ``circle`` is [latitude, longitude, radius] rather than GeoJSON order,
    and every flood carries a paired ``Cancel`` message.
    """

    def _alert(self, identifier="ID-1", msg_type="Alert", lat=1.33201, lng=103.87015,
               when="2025-05-22T09:55:00+08:00", severity="Minor"):
        return {
            "datetime": when,
            "updatedTimestamp": when,
            "item": {
                "type": "observation",
                "identifier": identifier,
                "msgType": msg_type,
                "sender": "pub_joint_ops_ctr@pub.gov.sg",
                "scope": "Public",
                "status": "Actual",
                "readings": [
                    {
                        "area": {
                            "areaDesc": "at Bt Timah Rd from Wilby Rd to Blackmore Dr",
                            "circle": [lat, lng, 1],
                        },
                        "category": "Met",
                        "certainty": "Observed",
                        "description": "Flash flood at Bt Timah Rd.",
                        "event": "Flood",
                        "headline": "Flash Flood Alert",
                        "severity": severity,
                        "urgency": "Immediate",
                    }
                ],
            },
        }

    def _cancel(self, references, when="2025-05-22T11:10:00+08:00"):
        return {
            "datetime": when,
            "item": {
                "msgType": "Cancel",
                "identifier": "CANCEL-1",
                "references": f"pub_joint_ops_ctr@pub.gov.sg, {references}, {when}",
                "readings": [],
            },
        }

    def test_circle_is_latitude_first_not_geojson(self):
        """Swapping these puts every Singapore alert in the Sea of Japan."""
        payload = {"data": {"records": [self._alert()]}}
        alerts = parse_flood_alerts(payload)
        assert alerts.loc[0, "longitude"] == pytest.approx(103.87015)
        assert alerts.loc[0, "latitude"] == pytest.approx(1.33201)
        # And it must survive the Singapore bounding-box validator.
        from floodsense.ingest.validate import validate_alerts

        _, report = validate_alerts(alerts)
        assert not any(
            i.code == "coordinates_outside_singapore" for i in report.errors
        )

    def test_cancel_is_not_counted_as_a_flood_event(self):
        payload = {
            "data": {
                "records": [self._alert("ID-1"), self._cancel("ID-1")]
            }
        }
        alerts = parse_flood_alerts(payload)
        assert len(alerts) == 1
        assert alerts.attrs["cancel_messages"] == 1

    def test_cancel_supplies_the_end_time(self):
        payload = {
            "data": {"records": [self._alert("ID-1"), self._cancel("ID-1")]}
        }
        alerts = parse_flood_alerts(payload)
        assert alerts.attrs["cancels_matched"] == 1
        duration = alerts.loc[0, "ts_end"] - alerts.loc[0, "ts_start"]
        assert duration == pd.Timedelta(minutes=75)

    def test_unmatched_alert_has_no_end_time(self):
        payload = {"data": {"records": [self._alert("ID-1")]}}
        alerts = parse_flood_alerts(payload)
        assert pd.isna(alerts.loc[0, "ts_end"])

    def test_severity_and_urgency_are_captured(self):
        payload = {"data": {"records": [self._alert(severity="Severe")]}}
        alerts = parse_flood_alerts(payload)
        assert alerts.loc[0, "severity"] == "Severe"
        assert alerts.loc[0, "urgency"] == "Immediate"

    def test_area_description_becomes_the_location_name(self):
        alerts = parse_flood_alerts({"data": {"records": [self._alert()]}})
        assert "Bt Timah Rd" in alerts.loc[0, "location_name"]

    def test_multiple_readings_get_distinct_ids(self):
        record = self._alert("ID-1")
        record["item"]["readings"].append(
            dict(record["item"]["readings"][0], severity="Moderate")
        )
        alerts = parse_flood_alerts({"data": {"records": [record]}})
        assert len(alerts) == 2
        assert alerts["alert_id"].nunique() == 2

    def test_broadcast_radius_is_recorded_but_not_a_footprint(self):
        """The spec states the radius is NOT the extent of flooding."""
        alerts = parse_flood_alerts({"data": {"records": [self._alert()]}})
        assert "_broadcast_radius_km" in alerts.columns
        assert alerts.loc[0, "_broadcast_radius_km"] == pytest.approx(1.0)

    def test_output_feeds_the_labeller(self):
        """Canonical columns, so build_labels consumes it unchanged."""
        alerts = parse_flood_alerts({"data": {"records": [self._alert()]}})
        for column in ("alert_id", "ts_start", "ts_end", "longitude", "latitude"):
            assert column in alerts.columns
        assert str(alerts["ts_start"].dt.tz) == "Asia/Singapore"

    def test_empty_records_yield_an_empty_frame(self):
        alerts = parse_flood_alerts({"data": {"records": []}})
        assert alerts.empty


class TestRealHistoricalCsvHeaders:
    """The published CSV uses snake_case; the dataset page shows title-case."""

    def test_snake_case_headers_load(self, tmp_path):
        path = tmp_path / "rain.csv"
        pd.DataFrame(
            {
                "date": ["2016-12-02"],
                "timestamp": ["2016-12-02T21:49:59+08:00"],
                "station_id": ["S77"],
                "station_name": ["Alexandra Road"],
                "location_longitude": [103.8125],
                "location_latitude": [1.2937],
                "reading_value": [0.4],
                "reading_type": [HISTORICAL_READING_TYPE],
                "reading_unit": ["mm"],
            }
        ).to_csv(path, index=False)

        readings, stations = load_historical_csv(path)
        assert len(readings) == 1
        assert readings.loc[0, "rainfall_mm"] == pytest.approx(0.4)
        assert stations.loc[0, "station_id"] == "S77"

    def test_title_case_headers_still_load(self, tmp_path):
        path = tmp_path / "rain.csv"
        pd.DataFrame(
            {
                "Timestamp": ["2016-12-02T21:49:59+08:00"],
                "Station Id": ["S77"],
                "Station Name": ["Alexandra Road"],
                "Location Longitude": [103.8125],
                "Location Latitude": [1.2937],
                "Reading Value": [0.4],
                "Reading Type": [HISTORICAL_READING_TYPE],
            }
        ).to_csv(path, index=False)

        readings, _ = load_historical_csv(path)
        assert len(readings) == 1

    def test_unknown_headers_fail_with_a_useful_message(self, tmp_path):
        path = tmp_path / "rain.csv"
        pd.DataFrame({"when": ["2016-12-02"], "mm": [0.4]}).to_csv(path, index=False)
        with pytest.raises(ValueError, match="after.*normalisation|missing"):
            load_historical_csv(path)
