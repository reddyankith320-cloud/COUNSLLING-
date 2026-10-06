"""Feature engineering: correctness and, above all, causality.

The causality tests are the important ones.  A single off-by-one in a
rolling window turns the whole project into a model that reads the future,
and that failure is invisible in the metrics - it just makes them better.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from floodsense.config import FeatureConfig
from floodsense.features import (
    build_dynamic_features,
    build_static_features,
    linear_filter,
    rolling_max,
    rolling_sum,
    shift_down,
    steps_since,
    trend_slope,
)
from floodsense.grid import RainGrid, haversine_km
from floodsense.schema import TIMEZONE


def make_grid(rain: np.ndarray, n_stations: int | None = None) -> RainGrid:
    rain = np.asarray(rain, dtype=np.float32)
    if rain.ndim == 1:
        rain = rain[:, None]
    n_stations = n_stations or rain.shape[1]
    times = pd.date_range("2024-01-01", periods=rain.shape[0], freq="5min", tz=TIMEZONE)
    return RainGrid(
        times=times,
        station_ids=np.array([f"S{i}" for i in range(n_stations)], dtype=object),
        rain=rain,
        longitude=np.linspace(103.7, 103.9, n_stations),
        latitude=np.linspace(1.3, 1.4, n_stations),
        station_names=np.array([f"Station {i}" for i in range(n_stations)], dtype=object),
    )


class TestRollingPrimitives:
    def test_rolling_sum_window_one_is_identity(self):
        x = np.array([[1.0], [2.0], [3.0]], dtype=np.float32)
        assert np.allclose(rolling_sum(x, 1), x)

    def test_rolling_sum_trailing_window(self):
        x = np.arange(6, dtype=np.float32).reshape(6, 1)
        out = rolling_sum(x, 3)
        # Partial windows at the head, full windows after.
        assert out[0, 0] == pytest.approx(0.0)
        assert out[1, 0] == pytest.approx(1.0)
        assert out[2, 0] == pytest.approx(3.0)       # 0+1+2
        assert out[5, 0] == pytest.approx(12.0)      # 3+4+5

    def test_rolling_sum_never_sees_the_future(self):
        """A spike at the end must not affect any earlier step."""
        base = np.zeros((20, 1), dtype=np.float32)
        spiked = base.copy()
        spiked[19, 0] = 100.0
        for window in (3, 6, 12):
            a, b = rolling_sum(base, window), rolling_sum(spiked, window)
            assert np.allclose(a[:19], b[:19]), f"window {window} leaked"

    def test_rolling_max_trailing_window(self):
        x = np.array([[0.0], [5.0], [1.0], [0.0]], dtype=np.float32)
        out = rolling_max(x, 3)
        assert out[1, 0] == pytest.approx(5.0)
        assert out[3, 0] == pytest.approx(5.0)       # still inside the window

    def test_rolling_max_drops_old_values(self):
        x = np.array([[9.0], [0.0], [0.0], [0.0]], dtype=np.float32)
        assert rolling_max(x, 2)[3, 0] == pytest.approx(0.0)

    def test_shift_down_repeats_head(self):
        x = np.array([[1.0], [2.0], [3.0]], dtype=np.float32)
        out = shift_down(x, 1)
        assert out[0, 0] == pytest.approx(1.0)
        assert out[2, 0] == pytest.approx(2.0)

    def test_trend_slope_of_a_ramp(self):
        x = np.arange(10, dtype=np.float32).reshape(10, 1)
        slope = trend_slope(x, 4)
        assert slope[-1, 0] == pytest.approx(1.0, abs=1e-4)

    def test_trend_slope_of_a_constant_is_zero(self):
        x = np.full((10, 1), 3.0, dtype=np.float32)
        assert trend_slope(x, 6)[-1, 0] == pytest.approx(0.0, abs=1e-5)

    def test_trend_slope_is_negative_when_falling(self):
        x = np.arange(10, 0, -1, dtype=np.float32).reshape(10, 1)
        assert trend_slope(x, 4)[-1, 0] < 0

    def test_linear_filter_weights_align_to_the_present(self):
        x = np.array([[0.0], [0.0], [1.0]], dtype=np.float32)
        out = linear_filter(x, np.array([0.0, 0.0, 1.0], dtype=np.float32))
        assert out[2, 0] == pytest.approx(1.0)

    def test_steps_since_counts_from_last_true(self):
        cond = np.array([[True], [False], [False], [True], [False]])
        out = steps_since(cond, cap=99)
        assert list(out[:, 0]) == [0.0, 1.0, 2.0, 0.0, 1.0]

    def test_steps_since_caps_when_never_true(self):
        cond = np.zeros((5, 1), dtype=bool)
        assert np.all(steps_since(cond, cap=3) == 3.0)


class TestDynamicFeatures:
    def test_expected_channels_present(self):
        grid = make_grid(np.random.default_rng(0).gamma(1.0, 0.3, (1200, 4)), 4)
        matrix = build_dynamic_features(grid)
        for name in (
            "rain_5min", "acc_15m", "acc_30m", "acc_1h", "acc_3h", "acc_6h",
            "acc_1d", "acc_3d", "intensity_mm_hr", "peak_5min_30m",
            "rate_15m", "rate_30m", "trend_slope_30m", "dry_spell_log",
            "observed", "gap_log", "hour_sin", "doy_cos",
        ):
            assert name in matrix.names, f"{name} missing"

    def test_shape_and_finiteness(self):
        grid = make_grid(np.random.default_rng(1).gamma(1.0, 0.3, (900, 3)), 3)
        matrix = build_dynamic_features(grid)
        assert matrix.values.shape == (900, 3, len(matrix.names))
        assert np.isfinite(matrix.values).all()

    def test_intensity_is_rain_per_hour(self):
        rain = np.zeros((900, 1), dtype=np.float32)
        rain[500, 0] = 1.0
        matrix = build_dynamic_features(make_grid(rain))
        assert matrix.channel("intensity_mm_hr")[500, 0] == pytest.approx(12.0)

    def test_accumulations_are_monotone_in_window_length(self):
        rng = np.random.default_rng(2)
        grid = make_grid(rng.gamma(1.0, 0.4, (1500, 2)), 2)
        matrix = build_dynamic_features(grid)
        a15 = matrix.channel("acc_15m")[1000]
        a30 = matrix.channel("acc_30m")[1000]
        a60 = matrix.channel("acc_1h")[1000]
        assert np.all(a15 <= a30 + 1e-5)
        assert np.all(a30 <= a60 + 1e-5)

    def test_no_feature_reads_the_future(self):
        """Perturbing the final step must not change any earlier feature."""
        rng = np.random.default_rng(3)
        rain = rng.gamma(1.0, 0.3, (1000, 2)).astype(np.float32)
        spiked = rain.copy()
        spiked[-1, :] += 50.0

        base = build_dynamic_features(make_grid(rain, 2)).values
        after = build_dynamic_features(make_grid(spiked, 2)).values
        assert np.allclose(base[:-1], after[:-1], atol=1e-5)

    def test_warmup_matches_longest_window(self):
        grid = make_grid(np.zeros((2000, 1), dtype=np.float32))
        cfg = FeatureConfig(accumulation_minutes=(15, 60, 1440), ewm_halflife_minutes=())
        matrix = build_dynamic_features(grid, cfg)
        assert matrix.warmup_steps == 288       # 1440 min / 5 min

    def test_warmup_covers_ewm_burn_in(self):
        """An EWM starts at zero, so it reads low for a few half-lives.

        Training on that stretch would teach the model that every record
        begins dry, so the warm-up has to cover the slowest exponential
        state even when it exceeds the longest fixed window.
        """
        grid = make_grid(np.zeros((4000, 1), dtype=np.float32))
        cfg = FeatureConfig(
            accumulation_minutes=(15, 60), ewm_halflife_minutes=(1440,)
        )
        matrix = build_dynamic_features(grid, cfg)
        assert matrix.warmup_steps == 3 * 288   # three half-lives

    def test_ewm_channels_present_and_ordered_by_halflife(self):
        grid = make_grid(
            np.random.default_rng(4).gamma(1.0, 0.3, (3000, 2)).astype(np.float32), 2
        )
        matrix = build_dynamic_features(grid)
        for name in ("ewm_1h", "ewm_6h", "ewm_1d", "ewm_3d"):
            assert name in matrix.names

    def test_longer_halflife_is_smoother(self):
        """A slow EWM must respond less to a single burst than a fast one."""
        rain = np.zeros((3000, 1), dtype=np.float32)
        rain[1500, 0] = 50.0
        matrix = build_dynamic_features(make_grid(rain))
        fast = matrix.channel("ewm_1h")[1500, 0]
        slow = matrix.channel("ewm_3d")[1500, 0]
        assert fast > slow > 0.0

    def test_rolling_std_separates_burst_from_soak(self):
        """Equal depth, different distribution, different std."""
        burst = np.zeros((3000, 1), dtype=np.float32)
        burst[1500, 0] = 6.0
        soak = np.zeros((3000, 1), dtype=np.float32)
        soak[1495:1501, 0] = 1.0

        b = build_dynamic_features(make_grid(burst))
        s = build_dynamic_features(make_grid(soak))
        assert b.channel("acc_30m")[1500, 0] == pytest.approx(
            s.channel("acc_30m")[1500, 0], abs=1e-4
        )
        assert b.channel("roll_std_30m")[1500, 0] > s.channel("roll_std_30m")[1500, 0]

    def test_spatial_gradient_is_zero_when_rain_is_uniform(self):
        rain = np.full((3000, 4), 0.4, dtype=np.float32)
        matrix = build_dynamic_features(make_grid(rain, 4))
        assert np.allclose(matrix.channel("gradient_30m")[2900], 0.0, atol=1e-3)

    def test_spatial_gradient_is_positive_where_the_cell_sits(self):
        rain = np.zeros((3000, 4), dtype=np.float32)
        rain[1400:1500, 0] = 3.0                 # only station 0 is raining
        matrix = build_dynamic_features(make_grid(rain, 4))
        gradient = matrix.channel("gradient_30m")[1499]
        assert gradient[0] > 0.0
        assert np.all(gradient[1:] <= 0.0)

    def test_lag_features_expose_past_rainfall(self):
        rain = np.zeros((3000, 1), dtype=np.float32)
        rain[1500, 0] = 9.0
        matrix = build_dynamic_features(make_grid(rain))
        assert matrix.channel("lag_rain_30m")[1506, 0] == pytest.approx(9.0)
        assert matrix.channel("lag_rain_30m")[1500, 0] == pytest.approx(0.0)

    def test_monsoon_indicators_are_binary_and_disjoint(self):
        grid = make_grid(np.zeros((3000, 1), dtype=np.float32))
        matrix = build_dynamic_features(grid)
        ne = matrix.channel("monsoon_ne")
        sw = matrix.channel("monsoon_sw")
        assert set(np.unique(ne)) <= {0.0, 1.0}
        assert np.all(ne * sw == 0.0)           # never both at once

    def test_missing_data_sets_observed_flag(self):
        rain = np.zeros((900, 1), dtype=np.float32)
        rain[400, 0] = np.nan
        matrix = build_dynamic_features(make_grid(rain))
        assert matrix.channel("observed")[400, 0] == pytest.approx(0.0)
        assert matrix.channel("observed")[401, 0] == pytest.approx(1.0)
        assert matrix.channel("gap_log")[400, 0] > 0.0

    def test_neighbour_features_see_other_stations(self):
        rain = np.zeros((900, 3), dtype=np.float32)
        rain[500, 1] = 10.0                     # only station 1 gets rain
        matrix = build_dynamic_features(make_grid(rain, 3))
        nbr = matrix.channel("nbr_max_acc_30m")
        assert nbr[500, 0] > 0.0                # station 0 sees its neighbour
        assert matrix.channel("rain_5min")[500, 0] == pytest.approx(0.0)

    def test_dry_spell_resets_on_rain(self):
        rain = np.zeros((900, 1), dtype=np.float32)
        rain[600, 0] = 5.0
        matrix = build_dynamic_features(make_grid(rain))
        dry = matrix.channel("dry_spell_log")
        assert dry[600, 0] == pytest.approx(0.0)
        assert dry[650, 0] > dry[601, 0]


class TestStaticFeatures:
    def test_without_auxiliary_data_falls_back_safely(self):
        grid = make_grid(np.zeros((400, 3), dtype=np.float32), 3)
        statics = build_static_features(grid)
        assert statics.values.shape[0] == 3
        assert np.isfinite(statics.values).all()
        assert np.all(statics.values[:, statics.index_of("alerts_per_year")] == 0.0)

    def test_alert_rate_counts_only_nearby_alerts(self):
        grid = make_grid(np.zeros((400, 2), dtype=np.float32), 2)
        alerts = pd.DataFrame(
            {
                "ts_start": pd.to_datetime(
                    ["2024-01-01", "2024-01-02"]
                ).tz_localize(TIMEZONE),
                "longitude": [grid.longitude[0], 103.0],   # second is far away
                "latitude": [grid.latitude[0], 1.0],
            }
        )
        statics = build_static_features(
            grid, historical_alerts=alerts, alert_radius_km=2.0, reference_days=365.25
        )
        counts = statics.values[:, statics.index_of("alert_count_log")]
        assert counts[0] > 0.0
        assert counts[1] == pytest.approx(np.log1p(0.0))

    def test_flood_prone_distance_and_counts(self):
        grid = make_grid(np.zeros((400, 2), dtype=np.float32), 2)
        points = pd.DataFrame(
            {
                "longitude": [grid.longitude[0]],
                "latitude": [grid.latitude[0]],
            }
        )
        statics = build_static_features(grid, flood_prone_points=points)
        dist = statics.values[:, statics.index_of("dist_floodprone_km")]
        assert dist[0] == pytest.approx(0.0, abs=1e-3)
        assert dist[1] > dist[0]
        assert statics.values[0, statics.index_of("floodprone_within_1000m")] == 1.0


class TestGeometry:
    def test_haversine_zero_distance(self):
        d = haversine_km(
            np.array([103.8]), np.array([1.35]), np.array([103.8]), np.array([1.35])
        )
        assert d[0] == pytest.approx(0.0, abs=1e-9)

    def test_haversine_one_degree_latitude(self):
        d = haversine_km(
            np.array([103.8]), np.array([1.0]), np.array([103.8]), np.array([2.0])
        )
        assert d[0] == pytest.approx(111.2, abs=0.5)
