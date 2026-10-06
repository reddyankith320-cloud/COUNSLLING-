"""The sweep's dataset-sharing rule.

``scripts/lstm_sweep.py`` reuses one dataset build across candidates, which
is only sound for parameters consumed *after* the window index arrays exist.
``sequence_steps`` and ``negative_keep_rate`` are consumed *while* they are
built, so a candidate that moves either needs its own build. Getting this
wrong does not raise - it silently evaluates the base configuration under the
candidate's name and produces a duplicate row, so it is pinned here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from floodsense.config import Config

SWEEP = Path(__file__).resolve().parents[1] / "scripts" / "lstm_sweep.py"


def _load_sweep():
    spec = importlib.util.spec_from_file_location("lstm_sweep", SWEEP)
    module = importlib.util.module_from_spec(spec)
    sys.modules["lstm_sweep"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sweep():
    return _load_sweep()


class TestWindowKey:
    def test_model_level_changes_share_one_build(self, sweep):
        """Width, depth, loss and seed are read after the windows are fixed."""
        base = sweep.Candidate("base")
        for variant in (
            sweep.Candidate("wide", hidden_size=128),
            sweep.Candidate("deep", num_layers=3),
            sweep.Candidate("bce", loss="weighted_bce"),
            sweep.Candidate("no_skip", last_step_skip=False),
            sweep.Candidate("other_seed", seed=2),
            sweep.Candidate("slow", learning_rate=1e-4),
        ):
            assert variant.window_key() == base.window_key(), variant.name

    def test_window_level_changes_force_their_own_build(self, sweep):
        base = sweep.Candidate("base")
        for variant in (
            sweep.Candidate("more_neg", negative_keep_rate=0.25),
            sweep.Candidate("long", sequence_steps=72),
        ):
            assert variant.window_key() != base.window_key(), variant.name

    def test_shipped_candidates_needing_a_build_are_recognised(self, sweep):
        """The two candidates in the sweep that move window parameters."""
        base_key = (
            Config().windows.sequence_steps,
            Config().windows.negative_keep_rate,
        )
        own = {
            c.name
            for c in sweep.CANDIDATES + [sweep.LONG_WINDOW]
            if c.window_key() != base_key
        }
        assert own == {"more_negatives", "long_window_72"}

    def test_apply_writes_window_parameters_onto_the_config(self, sweep):
        """``build()`` reads these off the config, so they must land there."""
        candidate = sweep.Candidate(
            "x", negative_keep_rate=0.25, sequence_steps=72
        )
        cfg = candidate.apply(Config(), 7)
        assert cfg.windows.negative_keep_rate == 0.25
        assert cfg.windows.sequence_steps == 72
