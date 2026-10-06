#!/usr/bin/env python3
"""Distribution-shift report across the chronological splits.

    python scripts/distribution_report.py --source synthetic --days 540 \
        --stations 32 --seed 20260601 --out results/synthetic_distribution_shift.json

Descriptive only, and deliberately separate from model evaluation: it reads
rainfall and labels, never a model's test predictions, so it can be produced
without touching the frozen evaluation.

The output name carries the provenance. A synthetic run writes
``synthetic_distribution_shift.json``; the real pipeline writes
``real_distribution_shift.json`` itself.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.config import Config  # noqa: E402
from floodsense.distribution import build_report  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", choices=("synthetic", "local"), default="synthetic")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--days", type=int, default=540)
    p.add_argument("--stations", type=int, default=32)
    p.add_argument("--seed", type=int, default=20260601)
    p.add_argument("--out", default="results/synthetic_distribution_shift.json")
    args = p.parse_args()

    cfg = Config()
    cfg.train.seed = args.seed
    cfg.windows.seed = args.seed

    if args.source == "synthetic":
        from floodsense.pipeline import prepare_from_synthetic
        from floodsense.synthetic import SyntheticConfig

        prepared = prepare_from_synthetic(
            cfg, SyntheticConfig(days=args.days, n_stations=args.stations, seed=args.seed)
        )
        source = (
            f"SYNTHETIC (floodsense.synthetic, days={args.days}, "
            f"stations={args.stations}, seed={args.seed})"
        )
    else:
        from floodsense.ingest.local import load_canonical
        from floodsense.pipeline import prepare

        tables = load_canonical(args.data_dir)
        prepared = prepare(
            readings=tables["readings"],
            stations=tables["stations"],
            alerts=tables["alerts"],
            cfg=cfg,
            flood_prone_points=tables.get("flood_prone_points"),
        )
        source = f"staged data at {args.data_dir}"

    report = build_report(prepared, data_source=source)
    print(report.summary())
    report.write(args.out)
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
