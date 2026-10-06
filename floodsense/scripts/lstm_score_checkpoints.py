#!/usr/bin/env python3
"""Re-score already-trained sweep checkpoints on validation.

    python scripts/lstm_score_checkpoints.py --days 540 --stations 32 --seed 20261006

``lstm_sweep.py`` writes its validation table only after every candidate
finishes, so a run that dies partway leaves the trained checkpoints on disk
with no table. This rebuilds the table from those checkpoints: the dataset is
rebuilt from the same seed, each checkpoint is loaded and run over the
validation split, and the metrics are recomputed from its predictions.

Nothing is transcribed from a log. Every number in the output is recomputed
here from a checkpoint's own predictions, so a table produced this way is
exactly what the sweep would have written.

The test split is not touched.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
from torch.utils.data import DataLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from floodsense.config import Config  # noqa: E402


def load_sweep():
    """Reuse the sweep's candidate definitions rather than restating them."""
    spec = importlib.util.spec_from_file_location(
        "lstm_sweep", Path(__file__).resolve().parent / "lstm_sweep.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["lstm_sweep"] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=540)
    p.add_argument("--stations", type=int, default=32)
    p.add_argument("--seed", type=int, default=20261006)
    p.add_argument("--outdir", default="artifacts/lstm_sweep")
    p.add_argument("--results", default="results")
    p.add_argument("--exclude", default="",
                   help="comma-separated candidate names to leave out, for "
                        "checkpoints known to be invalid")
    p.add_argument("--note", action="append", default=[],
                   help="recorded in the table's notes; repeatable")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    sweep = load_sweep()
    outdir = Path(args.outdir)
    results_dir = Path(args.results)
    results_dir.mkdir(parents=True, exist_ok=True)

    from floodsense.model import FloodSenseLSTM
    from floodsense.train import predict, resolve_device

    base = Config()
    base.operating_point = "accuracy"
    base.train.seed = args.seed
    base.windows.seed = args.seed
    base_key = (base.windows.sequence_steps, base.windows.negative_keep_rate)

    excluded = {n.strip() for n in args.exclude.split(",") if n.strip()}
    everything = sweep.CANDIDATES + [sweep.LONG_WINDOW]

    present, missing, skipped = [], [], []
    for candidate in everything:
        if candidate.name in excluded:
            skipped.append(candidate.name)
        elif (outdir / candidate.name / "floodsense_lstm.pt").exists():
            present.append(candidate)
        else:
            missing.append(candidate.name)

    print(f"[score] checkpoints to score: {[c.name for c in present]}")
    if skipped:
        print(f"[score] excluded by request: {skipped}")
    if missing:
        print(f"[score] no checkpoint (never trained): {missing}")
    if not present:
        raise SystemExit("no checkpoints to score")

    builds: dict[tuple[int, float], object] = {}

    def prepared_for(cfg: Config, key: tuple[int, float]):
        if key not in builds:
            print(f"[score] building windows ({sweep.describe_build(key)})...")
            t = time.time()
            builds[key] = sweep.build(cfg, args)
            print(f"        {time.time() - t:.0f}s | "
                  f"{json.dumps(builds[key].labels.summary())}")
        return builds[key]

    device = resolve_device("cpu")
    rows, best = [], None

    for candidate in present:
        cfg = candidate.apply(base, args.seed)
        key = candidate.window_key()
        prepared = prepared_for(cfg, key)

        model = FloodSenseLSTM.load(outdir / candidate.name / "floodsense_lstm.pt")
        probs, _, _ = predict(
            model, DataLoader(prepared.dataset("val"), batch_size=4096), device
        )
        scores = sweep.score_validation(prepared, cfg, probs)
        row = {
            "name": candidate.name,
            "note": candidate.note,
            "hidden_size": candidate.hidden_size,
            "num_layers": candidate.num_layers,
            "dropout": candidate.dropout,
            "learning_rate": candidate.learning_rate,
            "loss": candidate.loss,
            "negative_keep_rate": candidate.negative_keep_rate,
            "sequence_steps": candidate.sequence_steps,
            "last_step_skip": candidate.last_step_skip,
            "n_parameters": int(model.n_parameters()),
            "own_dataset_build": key != base_key,
            "scored_from_checkpoint": True,
            **scores,
        }
        rows.append(row)
        print(
            f"[score] {candidate.name:<16} PR-AUC {row['pr_auc']:.4f} | "
            f"ROC {row['roc_auc']:.4f} | event recall {row['event_recall']:.3f} | "
            f"acc {row['accuracy']:.2%} | {row['n_parameters']:,} params"
        )
        if best is None or row["pr_auc"] > best["pr_auc"]:
            best = row

    payload = {
        "data_source": (
            f"SYNTHETIC (floodsense.synthetic, days={args.days}, "
            f"stations={args.stations}, seed={args.seed})"
        ),
        "selection_metric": "validation PR-AUC",
        "test_set_used": False,
        "selected": best["name"],
        "not_trained": missing,
        "excluded": sorted(excluded),
        "notes": list(args.note),
        "candidates": rows,
    }
    out_path = results_dir / "lstm_sweep_validation.json"
    out_path.write_text(json.dumps(payload, indent=2))
    (outdir / "selected.json").write_text(json.dumps(best, indent=2))
    print(f"\n[score] validation table -> {out_path}")
    print(f"[score] SELECTED so far: {best['name']} ({best['pr_auc']:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
