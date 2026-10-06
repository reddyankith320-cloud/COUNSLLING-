"""The regular station x time rainfall grid.

Everything in FloodSense is computed on a *regular* 5-minute grid rather
than on the raw observation stream.  Two reasons:

1. NEA states the historical rainfall datasets may contain missing records
   and have not been through climate-grade quality control.  Resampling onto
   a fixed grid makes the gaps explicit instead of silently shortening a
   rolling window.
2. Once the data is a dense ``(T, S)`` array, every rolling feature is a
   cumulative-sum operation, which is what makes 8 years x ~70 stations
   tractable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .schema import SG_BOUNDS, STEP_MINUTES, TIMEZONE


@dataclass
class RainGrid:
    """Dense rainfall on a regular time grid.

    Attributes:
        times: ``(T,)`` tz-aware ``DatetimeIndex``, strictly increasing with
            a constant ``STEP_MINUTES`` step.
        station_ids: ``(S,)`` station identifiers, column order of ``rain``.
        rain: ``(T, S)`` float32 rainfall in mm per 5-minute interval.
            ``NaN`` marks a genuinely missing observation.
        longitude: ``(S,)`` float64 station longitude.
        latitude: ``(S,)`` float64 station latitude.
        station_names: ``(S,)`` human-readable names.
    """

    times: pd.DatetimeIndex
    station_ids: np.ndarray
    rain: np.ndarray
    longitude: np.ndarray
    latitude: np.ndarray
    station_names: np.ndarray

    def __post_init__(self) -> None:
        t, s = self.rain.shape
        if t != len(self.times):
            raise ValueError(f"rain has {t} rows but {len(self.times)} times")
        if s != len(self.station_ids):
            raise ValueError(f"rain has {s} cols but {len(self.station_ids)} stations")

    @property
    def n_steps(self) -> int:
        return self.rain.shape[0]

    @property
    def n_stations(self) -> int:
        return self.rain.shape[1]

    @property
    def missing_fraction(self) -> float:
        """Share of grid cells with no observation."""
        return float(np.isnan(self.rain).mean())

    def filled(self, value: float = 0.0) -> np.ndarray:
        """Rainfall with gaps replaced by ``value``.

        Zero-fill is the right default for *rainfall accumulation*: a missing
        tipping-bucket record is far more often "no rain" than "heavy rain".
        The gap mask is kept separately (``observed_mask``) and fed to the
        model as a feature so it can learn to distrust long gaps.
        """
        out = np.where(np.isnan(self.rain), value, self.rain)
        return out.astype(np.float32, copy=False)

    def observed_mask(self) -> np.ndarray:
        """``(T, S)`` float32, 1.0 where an observation exists."""
        return (~np.isnan(self.rain)).astype(np.float32)

    def station_index(self) -> dict[str, int]:
        return {sid: i for i, sid in enumerate(self.station_ids)}

    def subset_time(self, start: int, stop: int) -> "RainGrid":
        """Slice steps ``[start, stop)``, keeping all stations."""
        return RainGrid(
            times=self.times[start:stop],
            station_ids=self.station_ids,
            rain=self.rain[start:stop],
            longitude=self.longitude,
            latitude=self.latitude,
            station_names=self.station_names,
        )

    def stations_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "station_id": self.station_ids,
                "station_name": self.station_names,
                "longitude": self.longitude,
                "latitude": self.latitude,
            }
        )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_long(
        cls,
        readings: pd.DataFrame,
        stations: pd.DataFrame | None = None,
        *,
        step_minutes: int = STEP_MINUTES,
        drop_empty_stations: bool = True,
    ) -> "RainGrid":
        """Build a grid from canonical long-form readings.

        Args:
            readings: columns ``ts``, ``station_id``, ``rainfall_mm``.
            stations: optional metadata (``station_id``, ``station_name``,
                ``longitude``, ``latitude``).  When omitted the coordinates
                are taken from ``readings`` if present.
            drop_empty_stations: discard stations that never reported.
        """
        required = {"ts", "station_id", "rainfall_mm"}
        missing = required - set(readings.columns)
        if missing:
            raise ValueError(f"readings missing columns: {sorted(missing)}")

        df = readings.loc[:, ["ts", "station_id", "rainfall_mm"]].copy()
        df["ts"] = _to_sgt(df["ts"])
        df = df.dropna(subset=["ts", "station_id"])

        # Snap to the grid and collapse duplicate publications of the same
        # interval (the API re-publishes a reading when it is corrected).
        freq = f"{step_minutes}min"
        df["ts"] = df["ts"].dt.floor(freq)
        df = (
            df.groupby(["ts", "station_id"], observed=True, as_index=False)["rainfall_mm"]
            .mean()
        )

        if stations is None:
            if {"longitude", "latitude"}.issubset(readings.columns):
                stations = (
                    readings.loc[:, ["station_id", "longitude", "latitude"]]
                    .drop_duplicates("station_id")
                    .assign(station_name=lambda d: d["station_id"])
                )
            else:
                raise ValueError(
                    "stations metadata is required when readings carry no coordinates"
                )

        meta = stations.drop_duplicates("station_id").set_index("station_id")
        if "station_name" not in meta.columns:
            meta["station_name"] = meta.index

        wide = df.pivot(index="ts", columns="station_id", values="rainfall_mm")

        if drop_empty_stations:
            wide = wide.loc[:, wide.notna().any(axis=0)]

        keep = [sid for sid in wide.columns if sid in meta.index]
        if not keep:
            raise ValueError("no station in the readings has metadata")
        wide = wide.loc[:, keep]

        full_index = pd.date_range(
            wide.index.min(), wide.index.max(), freq=freq, tz=TIMEZONE
        )
        wide = wide.reindex(full_index)

        meta = meta.loc[keep]
        return cls(
            times=full_index,
            station_ids=np.asarray(keep, dtype=object),
            rain=wide.to_numpy(dtype=np.float32),
            longitude=meta["longitude"].to_numpy(dtype=np.float64),
            latitude=meta["latitude"].to_numpy(dtype=np.float64),
            station_names=meta["station_name"].astype(str).to_numpy(dtype=object),
        )

    def validate_coordinates(self) -> np.ndarray:
        """Boolean mask of stations whose coordinates sit inside Singapore."""
        return (
            (self.longitude >= SG_BOUNDS["lon_min"])
            & (self.longitude <= SG_BOUNDS["lon_max"])
            & (self.latitude >= SG_BOUNDS["lat_min"])
            & (self.latitude <= SG_BOUNDS["lat_max"])
        )


def _to_sgt(series: pd.Series) -> pd.Series:
    """Parse to tz-aware Singapore time.

    data.gov.sg publishes ISO 8601 in SGT (``+08:00``).  Naive strings are
    assumed to be SGT already.
    """
    ts = pd.to_datetime(series, errors="coerce", format="mixed", utc=False)
    try:
        tz = ts.dt.tz
    except AttributeError:  # not datetimelike at all
        raise ValueError("ts column could not be parsed as datetimes") from None
    if tz is None:
        return ts.dt.tz_localize(TIMEZONE, ambiguous="NaT", nonexistent="NaT")
    return ts.dt.tz_convert(TIMEZONE)


def haversine_km(
    lon1: np.ndarray, lat1: np.ndarray, lon2: np.ndarray, lat2: np.ndarray
) -> np.ndarray:
    """Great-circle distance in km, broadcasting over the inputs."""
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return 2.0 * r * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def pairwise_km(
    lon: np.ndarray, lat: np.ndarray, other_lon: np.ndarray, other_lat: np.ndarray
) -> np.ndarray:
    """``(n, m)`` distance matrix in km."""
    return haversine_km(
        lon[:, None], lat[:, None], other_lon[None, :], other_lat[None, :]
    )
