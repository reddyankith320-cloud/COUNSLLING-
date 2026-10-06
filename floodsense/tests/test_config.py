"""Config serialisation.

A training run writes ``config.json`` next to its checkpoint, and the
inference service reads it back. If the round trip returns plain dicts
instead of the nested dataclasses, nothing fails at save time, nothing
fails at load time, and the first attribute access inside the scoring path
raises - after deployment. Hence these tests.
"""

from __future__ import annotations

import json

import pytest

from floodsense.config import (
    SECTIONS,
    Config,
    FeatureConfig,
    LabelConfig,
    ModelConfig,
    RiskConfig,
    SplitConfig,
    TrainConfig,
    WindowConfig,
)


class TestRoundTrip:
    def test_sections_rebuild_as_dataclasses_not_dicts(self, tmp_path):
        path = tmp_path / "config.json"
        Config().to_json(path)
        restored = Config.from_json(path)

        assert isinstance(restored.features, FeatureConfig)
        assert isinstance(restored.labels, LabelConfig)
        assert isinstance(restored.windows, WindowConfig)
        assert isinstance(restored.splits, SplitConfig)
        assert isinstance(restored.model, ModelConfig)
        assert isinstance(restored.train, TrainConfig)
        assert isinstance(restored.risk, RiskConfig)

    def test_attribute_access_works_after_reload(self, tmp_path):
        """The exact access pattern the inference service uses."""
        path = tmp_path / "config.json"
        Config().to_json(path)
        cfg = Config.from_json(path)

        assert isinstance(cfg.windows.sequence_steps, int)
        assert isinstance(cfg.features.accumulation_minutes, tuple)
        assert isinstance(cfg.model.hidden_size, int)
        assert isinstance(cfg.labels.horizon_max_minutes, int)

    def test_values_survive(self, tmp_path):
        cfg = Config()
        cfg.model.hidden_size = 123
        cfg.model.attention = False
        cfg.model.input_norm = "layer"
        cfg.train.loss = "weighted_bce"
        cfg.labels.radius_km = 3.5
        cfg.target_recall = 0.9

        path = tmp_path / "config.json"
        cfg.to_json(path)
        back = Config.from_json(path)

        assert back.model.hidden_size == 123
        assert back.model.attention is False
        assert back.model.input_norm == "layer"
        assert back.train.loss == "weighted_bce"
        assert back.labels.radius_km == pytest.approx(3.5)
        assert back.target_recall == pytest.approx(0.9)

    def test_tuple_fields_do_not_degrade_to_lists(self, tmp_path):
        """JSON has no tuples; window code indexes and unpacks these."""
        cfg = Config()
        cfg.features.accumulation_minutes = (15, 60, 1440)
        cfg.features.rate_windows_minutes = (15,)
        cfg.risk.band_edges = (25, 55, 75)

        path = tmp_path / "config.json"
        cfg.to_json(path)
        back = Config.from_json(path)

        assert back.features.accumulation_minutes == (15, 60, 1440)
        assert isinstance(back.features.accumulation_minutes, tuple)
        assert isinstance(back.features.rate_windows_minutes, tuple)
        assert back.risk.band_edges == (25, 55, 75)

    def test_partial_config_falls_back_to_defaults(self):
        cfg = Config.from_dict({"model": {"hidden_size": 8}})
        assert cfg.model.hidden_size == 8
        assert cfg.model.num_layers == ModelConfig().num_layers
        assert cfg.train.epochs == TrainConfig().epochs

    def test_unknown_keys_are_ignored(self):
        """A config written by a newer version must still load."""
        cfg = Config.from_dict(
            {
                "model": {"hidden_size": 8, "some_future_flag": True},
                "a_whole_new_section": {"x": 1},
                "target_recall": 0.8,
            }
        )
        assert cfg.model.hidden_size == 8
        assert cfg.target_recall == pytest.approx(0.8)

    def test_every_section_is_registered(self):
        """A new section must be added to SECTIONS or it loads as a dict."""
        from dataclasses import fields

        scalars = {
            "target_recall", "operating_point", "target_accuracy",
            "accuracy_band",
        }
        nested = {f.name for f in fields(Config) if f.name not in scalars}
        assert nested == set(SECTIONS), (
            "Config gained or lost a section; update SECTIONS in config.py"
        )

    def test_json_is_human_readable_and_sorted(self, tmp_path):
        path = tmp_path / "config.json"
        Config().to_json(path)
        text = path.read_text()
        parsed = json.loads(text)
        assert "model" in parsed and "hidden_size" in parsed["model"]
        assert text.index('"features"') < text.index('"model"')   # sorted keys
