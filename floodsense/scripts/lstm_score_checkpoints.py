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
    p.add_argument("--ensemble", default="",
                   help="also score a seed ensemble from member checkpoints, "
                        "as NAME:COUNT (e.g. deep_h96_l3:3). Lets an ensemble "
                        "whose run died after training its members be scored "
                        "without retraining them.")
    p.add_argument("--merge", action="store_true",
                   help="fold these rows into an existing table instead of "
                        "replacing it")
    return p.parse_args()


def parse_ensemble(spec: str) -> tuple[str, int]:
    name, _, count = spec.partition(":")
    if not name or not count.isdigit() or int(count) < 2:
        raise SystemExit(f"--ensemble wants NAME:COUNT with COUNT>=2, got {spec!r}")
    return name, int(count)


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

    ensemble_request = None
    if args.ensemble:
        name, count = parse_ensemble(args.ensemble)
        winner = next((c for c in everything if c.name == name), None)
        if winner is None:
            raise SystemExit(f"{name} is not one of the sweep's candidates")
        members = [outdir / f"{name}_s{k}" for k in range(count)]
        absent = [m.name for m in members
                  if not (m / "floodsense_lstm.pt").exists()]
        if absent:
            raise SystemExit(f"ensemble members not trained: {absent}")
        ensemble_request = (winner, count, members)

    print(f"[score] checkpoints to score: {[c.name for c in present]}")
    if skipped:
        print(f"[score] excluded by request: {skipped}")
    if missing:
        print(f"[score] no checkpoint (never trained): {missing}")
    if not present and not args.ensemble:
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

    if ensemble_request is not None:
        winner, count, members = ensemble_request
        cfg = winner.apply(base, args.seed)
        key = winner.window_key()
        prepared = prepared_for(cfg, key)
        stack = []
        for member in members:
            model = FloodSenseLSTM.load(member / "floodsense_lstm.pt")
            probs, _, _ = predict(
                model,
                DataLoader(prepared.dataset("val"), batch_size=4096),
                device,
            )
            stack.append(probs)
            print(f"[score] {member.name} scored")
        averaged = np.mean(stack, axis=0)
        np.save(outdir / "ensemble_val_probs.npy", averaged)
        scores = sweep.score_validation(prepared, cfg, averaged)
        row = {
            "name": f"{winner.name}_ensemble_x{count}",
            "note": f"mean probability over {count} seeds",
            "sequence_steps": winner.sequence_steps,
            "negative_keep_rate": winner.negative_keep_rate,
            "own_dataset_build": key != base_key,
            "scored_from_checkpoint": True,
            **scores,
        }
        rows.append(row)
        print(
            f"[score] {row['name']:<16} PR-AUC {row['pr_auc']:.4f} | "
            f"ROC {row['roc_auc']:.4f} | event recall {row['event_recall']:.3f} | "
            f"acc {row['accuracy']:.2%}"
        )
        if best is None or row["pr_auc"] > best["pr_auc"]:
            best = row

    not_trained, excluded, notes = missing, sorted(excluded), list(args.note)
    out_path = results_dir / "lstm_sweep_validation.json"
    if args.merge and out_path.exists():
        merged = sweep.merge_table(json.loads(out_path.read_text()), rows)
        rows, best = merged["candidates"], merged["best"]
        not_trained, excluded = merged["not_trained"], merged["excluded"]
        notes = merged["notes"] + notes
        print(f"[score] merged: replaced {merged['replaced']} row(s), "
              f"best is now {best['name']} ({best['pr_auc']:.4f})")

    payload = {
        "data_source": (
            f"SYNTHETIC (floodsense.synthetic, days={args.days}, "
            f"stations={args.stations}, seed={args.seed})"
        ),
        "selection_metric": "validation PR-AUC",
        "test_set_used": False,
        "selected": best["name"],
        "not_trained": not_trained,
        "excluded": excluded,
        "notes": notes,
        "candidates": rows,
    }
    out_path.write_text(json.dumps(payload, indent=2))
    (outdir / "selected.json").write_text(json.dumps(best, indent=2))
    print(f"\n[score] validation table -> {out_path}")
    print(f"[score] SELECTED so far: {best['name']} ({best['pr_auc']:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
