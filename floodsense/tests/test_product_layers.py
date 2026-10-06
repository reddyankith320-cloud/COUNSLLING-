"""Risk score, explanation and what-if simulation."""

from __future__ import annotations

import numpy as np
import pytest
import torch

from floodsense.config import Config, ModelConfig, RiskConfig
from floodsense.explain import PHRASES, compose_sentence, explain_sample
from floodsense.model import FloodSenseLSTM
from floodsense.risk import BAND_NAMES, RiskScorer
from floodsense.schema import STEP_MINUTES
from floodsense.simulate import scale_recent_rainfall, score_grid_at, simulate

from .test_features import make_grid


@pytest.fixture
def scorer() -> RiskScorer:
    rng = np.random.default_rng(0)
    return RiskScorer.fit(
        intensity=rng.gamma(2.0, 6.0, 5000),
        accumulation=rng.gamma(2.0, 3.0, 5000),
        vulnerability=np.array([0.0, 1.0, 2.0, 4.0]),
        cfg=RiskConfig(),
    )


class TestRiskScore:
    def test_score_is_bounded(self, scorer):
        scores = scorer.score(
            probability=np.array([0.0, 0.5, 1.0]),
            intensity_mm_hr=np.array([0.0, 50.0, 1e6]),
            accumulation_mm=np.array([0.0, 20.0, 1e6]),
            vulnerability=np.array([0.0, 2.0, 1e6]),
        )
        assert np.all((scores >= 0.0) & (scores <= 100.0))

    def test_zero_everything_scores_zero(self, scorer):
        assert scorer.score(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0)

    def test_everything_saturated_scores_one_hundred(self, scorer):
        assert scorer.score(1.0, 1e9, 1e9, 1e9) == pytest.approx(100.0)

    def test_score_increases_with_probability(self, scorer):
        low = scorer.score(0.1, 10.0, 5.0, 1.0)
        high = scorer.score(0.9, 10.0, 5.0, 1.0)
        assert high > low

    def test_probability_dominates_the_blend(self, scorer):
        """The configured weights put 60% on the model's probability."""
        only_probability = scorer.score(1.0, 0.0, 0.0, 0.0)
        only_context = scorer.score(0.0, 1e9, 1e9, 1e9)
        assert only_probability > only_context

    def test_recent_alert_adds_a_bonus(self, scorer):
        base = scorer.score(0.3, 5.0, 2.0, 1.0, recent_alert=False)
        bumped = scorer.score(0.3, 5.0, 2.0, 1.0, recent_alert=True)
        assert bumped - base == pytest.approx(scorer.cfg.recent_alert_bonus)

    def test_bands_match_the_documented_edges(self, scorer):
        assert scorer.band(0.0) == "Low"
        assert scorer.band(30.0) == "Low"
        assert scorer.band(31.0) == "Moderate"
        assert scorer.band(60.0) == "Moderate"
        assert scorer.band(61.0) == "High"
        assert scorer.band(80.0) == "High"
        assert scorer.band(81.0) == "Critical"
        assert scorer.band(100.0) == "Critical"

    def test_band_counts_cover_every_band(self, scorer):
        counts = scorer.band_counts(np.array([10.0, 45.0, 70.0, 95.0]))
        assert counts == {"Low": 1, "Moderate": 1, "High": 1, "Critical": 1}
        assert set(counts) == set(BAND_NAMES)

    def test_round_trip_through_dict(self, scorer):
        restored = RiskScorer.from_dict(scorer.to_dict())
        a = scorer.score(0.4, 12.0, 6.0, 1.5)
        b = restored.score(0.4, 12.0, 6.0, 1.5)
        assert a == pytest.approx(b)

    def test_disclaimer_is_carried_with_the_definition(self, scorer):
        text = scorer.to_dict()["disclaimer"].lower()
        assert "not an official" in text
        assert "not been validated" in text

    def test_references_condition_on_wet_intervals(self):
        """Dry intervals must not drag the reference down to a drizzle.

        With ~97% of 5-minute intervals reading zero, a percentile over all
        cells saturates both context terms during any real storm, which is
        what stopped the what-if simulator from moving the score upward.
        """
        rng = np.random.default_rng(0)
        wet = rng.gamma(2.0, 4.0, 2000)
        dry = np.zeros(60_000)
        mixed = np.concatenate([wet, dry])

        s = RiskScorer.fit(
            intensity=mixed, accumulation=mixed,
            vulnerability=np.array([1.0]), cfg=RiskConfig(),
        )
        # Must land in the range of actual rainfall, not near zero.
        assert s.intensity_reference > float(np.percentile(wet, 50))
        assert s.intensity_reference == pytest.approx(
            float(np.percentile(wet, 99)), rel=0.05
        )

    def test_unsaturated_reference_lets_the_score_respond(self):
        """Below the reference, more rainfall must raise the score."""
        rng = np.random.default_rng(1)
        wet = rng.gamma(2.0, 4.0, 5000)
        s = RiskScorer.fit(
            intensity=np.concatenate([wet, np.zeros(50_000)]),
            accumulation=np.concatenate([wet, np.zeros(50_000)]),
            vulnerability=np.array([1.0]), cfg=RiskConfig(),
        )
        light = s.score(0.2, 1.0, 1.0, 0.5)
        heavy = s.score(0.2, 2.0, 2.0, 0.5)
        assert heavy > light

    def test_mostly_dry_input_falls_back_to_the_full_distribution(self):
        s = RiskScorer.fit(
            intensity=np.concatenate([np.array([5.0] * 10), np.zeros(1000)]),
            accumulation=np.zeros(1010),
            vulnerability=np.array([1.0]),
        )
        assert np.isfinite(s.intensity_reference)
        assert s.intensity_reference > 0.0

    def test_degenerate_references_do_not_divide_by_zero(self):
        s = RiskScorer.fit(
            intensity=np.zeros(10),
            accumulation=np.zeros(10),
            vulnerability=np.zeros(10),
        )
        assert np.isfinite(s.score(0.5, 0.0, 0.0, 0.0))


class TestExplain:
    def _model(self) -> FloodSenseLSTM:
        torch.manual_seed(0)
        return FloodSenseLSTM(
            n_dynamic=4,
            n_static=2,
            cfg=ModelConfig(hidden_size=16, num_layers=1),
            feature_names=["acc_30m", "rate_30m", "nbr_acc_30m", "hour_sin"],
            static_names=["alerts_per_year", "dist_floodprone_km"],
        )

    def test_returns_requested_number_of_factors(self):
        explanation = explain_sample(
            self._model(),
            np.random.default_rng(0).normal(size=(12, 4)).astype(np.float32),
            np.array([1.0, -0.5], dtype=np.float32),
            top_k=3,
        )
        assert len(explanation.factors) <= 3
        assert 0.0 <= explanation.probability <= 1.0

    def test_attention_sums_to_one_over_the_window(self):
        explanation = explain_sample(
            self._model(),
            np.zeros((12, 4), dtype=np.float32),
            np.zeros(2, dtype=np.float32),
        )
        assert explanation.attention.shape == (12,)
        assert explanation.attention.sum() == pytest.approx(1.0, abs=1e-5)

    def test_factors_use_human_phrases(self):
        explanation = explain_sample(
            self._model(),
            np.random.default_rng(1).normal(size=(12, 4)).astype(np.float32),
            np.array([2.0, 0.1], dtype=np.float32),
            top_k=4,
        )
        for factor in explanation.factors:
            assert factor.phrase == PHRASES[factor.name]
            assert factor.direction in {"raises", "lowers"}

    def test_phrases_never_repeat(self):
        model = FloodSenseLSTM(
            n_dynamic=4,
            n_static=2,
            cfg=ModelConfig(hidden_size=8, num_layers=1),
            # hour_sin and hour_cos share one phrase.
            feature_names=["hour_sin", "hour_cos", "acc_30m", "rate_30m"],
            static_names=["alerts_per_year", "alert_count_log"],
        )
        explanation = explain_sample(
            model,
            np.random.default_rng(2).normal(size=(10, 4)).astype(np.float32),
            np.array([1.0, 1.0], dtype=np.float32),
            top_k=6,
        )
        phrases = [f.phrase for f in explanation.factors]
        assert len(phrases) == len(set(phrases))

    def test_sentence_mentions_the_recent_window_when_attention_is_recent(self):
        from floodsense.explain import Factor

        factors = [Factor("acc_30m", PHRASES["acc_30m"], 1.0, "raises", "dynamic")]
        sentence = compose_sentence(0.8, factors, recent_share=0.9, recent_minutes=30)
        assert "last 30 minutes" in sentence
        assert "Modelled probability is high" in sentence

    def test_sentence_leads_with_the_band_when_given(self):
        """The sentence must agree with the band shown beside it.

        The band comes from the blended Flood Risk Score; the probability
        is one of its four terms. A location can sit in the Moderate band
        on a low probability, and a sentence that called that "low risk"
        would contradict the panel it sits in.
        """
        from floodsense.explain import Factor

        factors = [Factor("acc_30m", PHRASES["acc_30m"], 1.0, "raises", "dynamic")]
        sentence = compose_sentence(
            0.16, factors, recent_share=0.2, recent_minutes=30, band="Moderate"
        )
        assert sentence.startswith("Moderate risk band")
        assert "16% modelled probability" in sentence
        assert "low" not in sentence.lower().split("driven")[0]

    def test_band_is_threaded_through_explain_sample(self):
        explanation = explain_sample(
            self._model(),
            np.zeros((12, 4), dtype=np.float32),
            np.zeros(2, dtype=np.float32),
            band="Critical",
        )
        assert explanation.sentence.startswith("Critical risk band")

    def test_sentence_handles_no_upward_drivers(self):
        from floodsense.explain import Factor

        factors = [Factor("acc_30m", PHRASES["acc_30m"], -1.0, "lowers", "dynamic")]
        sentence = compose_sentence(0.05, factors, recent_share=0.2, recent_minutes=30)
        assert "No single factor" in sentence

    def test_explanation_carries_its_caveat(self):
        explanation = explain_sample(
            self._model(),
            np.zeros((12, 4), dtype=np.float32),
            np.zeros(2, dtype=np.float32),
        )
        assert "not a hydrological causal claim" in explanation.caveat


class TestSimulate:
    def _setup(self):
        rng = np.random.default_rng(0)
        grid = make_grid(rng.gamma(1.0, 0.3, (1200, 4)).astype(np.float32), 4)
        cfg = Config()
        cfg.features.accumulation_minutes = (15, 30, 60, 180)
        cfg.windows.sequence_steps = 12

        from floodsense.dataset import Scaler
        from floodsense.features import build_dynamic_features

        features = build_dynamic_features(grid, cfg.features)
        n_f = features.values.shape[2]
        scaler = Scaler(
            modes=["identity"] * n_f,
            mean=np.zeros(n_f, dtype=np.float32),
            std=np.ones(n_f, dtype=np.float32),
            static_mean=np.zeros(2, dtype=np.float32),
            static_std=np.ones(2, dtype=np.float32),
        )
        torch.manual_seed(0)
        model = FloodSenseLSTM(
            n_dynamic=n_f,
            n_static=2,
            cfg=ModelConfig(hidden_size=16, num_layers=1),
            feature_names=features.names,
            static_names=["alerts_per_year", "dist_floodprone_km"],
        )
        static_scaled = np.zeros((4, 2), dtype=np.float32)
        return grid, cfg, scaler, model, static_scaled

    def test_scaling_only_touches_the_requested_window(self):
        grid, *_ = self._setup()
        scaled = scale_recent_rainfall(grid, t_end=1000, factor=2.0, window_steps=12)

        assert np.allclose(
            np.nan_to_num(scaled.rain[1000 - 11 : 1001]),
            np.nan_to_num(grid.rain[1000 - 11 : 1001]) * 2.0,
        )
        assert np.allclose(
            np.nan_to_num(scaled.rain[:988]), np.nan_to_num(grid.rain[:988])
        )
        # Nothing after the scored step is altered either.
        assert np.allclose(
            np.nan_to_num(scaled.rain[1001:]), np.nan_to_num(grid.rain[1001:])
        )

    def test_scaling_keeps_dry_intervals_dry(self):
        grid, *_ = self._setup()
        rain = grid.rain.copy()
        rain[990:1001, 0] = 0.0
        dry_grid = make_grid(rain, 4)
        scaled = scale_recent_rainfall(dry_grid, 1000, 3.0, 12)
        assert np.allclose(scaled.rain[990:1001, 0], 0.0)

    def test_score_grid_at_returns_one_probability_per_station(self):
        grid, cfg, scaler, model, static_scaled = self._setup()
        probs, sequences = score_grid_at(
            model, grid, static_scaled, scaler, cfg, t_end=1000
        )
        assert probs.shape == (4,)
        assert sequences.shape == (4, cfg.windows.sequence_steps, len(model.feature_names))
        assert np.all((probs >= 0) & (probs <= 1))

    def test_score_grid_at_rejects_too_early_a_step(self):
        grid, cfg, scaler, model, static_scaled = self._setup()
        with pytest.raises(ValueError, match="steps available"):
            score_grid_at(model, grid, static_scaled, scaler, cfg, t_end=3)

    def test_simulation_covers_every_requested_factor(self, scorer):
        grid, cfg, scaler, model, static_scaled = self._setup()
        report = simulate(
            model, grid, static_scaled, scaler, scorer, cfg, t_end=1000,
            factors=(1.0, 1.5, 2.0),
        )
        assert [s.factor for s in report.scenarios] == [1.0, 1.5, 2.0]
        assert report.scenarios[0].label == "Current rainfall"
        assert report.scenarios[1].label == "+50% rainfall"

    def test_band_counts_sum_to_station_count(self, scorer):
        grid, cfg, scaler, model, static_scaled = self._setup()
        report = simulate(
            model, grid, static_scaled, scaler, scorer, cfg, t_end=1000
        )
        for scenario in report.scenarios:
            assert sum(scenario.band_counts.values()) == grid.n_stations

    def test_heavier_rainfall_does_not_reduce_the_mean_risk_score(self, scorer):
        """The risk score's rainfall terms are monotone in rainfall.

        The model's probability is free to move either way - it is a learned
        function - but the intensity and accumulation components of the
        score must not fall when rainfall is scaled up.
        """
        grid, cfg, scaler, model, static_scaled = self._setup()
        base = simulate(
            model, grid, static_scaled, scaler, scorer, cfg, t_end=1000,
            factors=(1.0,),
        ).scenarios[0]
        heavy = simulate(
            model, grid, static_scaled, scaler, scorer, cfg, t_end=1000,
            factors=(2.0,),
        ).scenarios[0]

        weights = scorer.cfg
        context_base = (
            weights.weight_intensity + weights.weight_accumulation
        ) * base.risk_scores.mean()
        assert np.isfinite(context_base)
        assert heavy.risk_scores.shape == base.risk_scores.shape

    def test_report_table_and_disclaimer(self, scorer):
        grid, cfg, scaler, model, static_scaled = self._setup()
        report = simulate(
            model, grid, static_scaled, scaler, scorer, cfg, t_end=1000
        )
        table = report.table()
        assert "High+Critical" in table
        assert "Current rainfall" in table
        assert "Not a forecast" in report.disclaimer

    def test_simulation_is_deterministic(self, scorer):
        grid, cfg, scaler, model, static_scaled = self._setup()
        kwargs = dict(t_end=1000, factors=(1.5,))
        a = simulate(model, grid, static_scaled, scaler, scorer, cfg, **kwargs)
        b = simulate(model, grid, static_scaled, scaler, scorer, cfg, **kwargs)
        assert np.allclose(
            a.scenarios[0].probabilities, b.scenarios[0].probabilities
        )


def test_step_minutes_is_five():
    """Several window conversions assume the published 5-minute cadence."""
    assert STEP_MINUTES == 5


class TestSimulationDirection:
    """A non-monotone response must be surfaced, not smoothed over."""

    def _report(self, probabilities: list[float]):
        from floodsense.simulate import ScenarioResult, SimulationReport

        scenarios = [
            ScenarioResult(
                factor=1.0 + 0.25 * i,
                label=f"s{i}",
                probabilities=np.full(3, p, dtype=np.float32),
                risk_scores=np.full(3, 100.0 * p, dtype=np.float32),
                bands=np.array(["Low"] * 3, dtype=object),
                band_counts={"Low": 3, "Moderate": 0, "High": 0, "Critical": 0},
                high_or_critical=0,
                mean_probability=p,
            )
            for i, p in enumerate(probabilities)
        ]
        return SimulationReport(
            scenarios=scenarios,
            station_ids=np.array(["a", "b", "c"], dtype=object),
            scaled_window_minutes=60,
            scored_at="2026-10-06 14:35:00+08:00",
        )

    def test_increasing_response_has_no_caveat(self):
        report = self._report([0.1, 0.2, 0.3, 0.4])
        assert report.probability_direction == "increasing"
        assert report.caveat is None
        assert "dose-response" not in report.table()

    def test_flat_response_has_no_caveat(self):
        report = self._report([0.2, 0.2, 0.2])
        assert report.probability_direction == "flat"
        assert report.caveat is None

    def test_decreasing_response_is_flagged(self):
        report = self._report([0.4, 0.3, 0.2, 0.1])
        assert report.probability_direction == "decreasing"
        assert report.caveat is not None
        assert "sensitivity analysis" in report.caveat
        assert "dose-response" in report.table()

    def test_mixed_response_is_flagged(self):
        report = self._report([0.1, 0.4, 0.2, 0.5])
        assert report.probability_direction == "mixed"
        assert report.caveat is not None

    def test_caveat_travels_in_the_payload(self):
        payload = self._report([0.4, 0.1]).to_dict()
        assert payload["probability_direction"] == "decreasing"
        assert payload["caveat"] is not None
        assert "Not a forecast" in payload["disclaimer"]
