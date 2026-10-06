#!/usr/bin/env python3
"""Train the FloodSense LSTM.

Examples:

    # Offline, no network: synthetic storms in the canonical schema.
    python scripts/train.py --source synthetic --days 270 --stations 32

    # Real Singapore open data previously staged to disk by
    # scripts/fetch_data.py.
    python scripts/train.py --source local --data-dir data/

Artifacts land in ``--outdir``: ``floodsense_lstm.pt``, ``config.json``,
``scaler.json`` and ``metrics.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.config import Config  # noqa: E402
from floodsense.train import train  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--source",
        choices=("synthetic", "local"),
        default="synthetic",
        help="synthetic generator, or canonical tables staged on disk",
    )
    p.add_argument("--data-dir", default="data", help="for --source local")
    p.add_argument("--outdir", default="artifacts/run", help="where to write artifacts")

    p.add_argument("--days", type=int, default=270, help="synthetic record length")
    p.add_argument("--stations", type=int, default=32, help="synthetic station count")
    p.add_argument(
        "--alerts-per-station-month",
        type=float,
        default=3.0,
        help="synthetic alert frequency; lower is harder and more realistic",
    )

    p.add_argument("--epochs", type=int, default=None)
    p.add_argument("--batch-size", type=int, default=None)
    p.add_argument("--learning-rate", type=float, default=None)
    p.add_argument("--hidden-size", type=int, default=None)
    p.add_argument("--num-layers", type=int, default=None)
    p.add_argument("--sequence-steps", type=int, default=None)
    p.add_argument("--loss", choices=("focal", "weighted_bce"), default=None)
    p.add_argument("--no-attention", action="store_true")
    p.add_argument("--no-skip", action="store_true", help="disable the last-step skip")
    p.add_argument("--dropout", type=float, default=None)
    p.add_argument("--patience", type=int, default=None, help="early-stopping patience")
    p.add_argument(
        "--input-norm", choices=("none", "layer"), default=None,
        help="input normalisation; 'layer' normalises across channels per step",
    )
    p.add_argument(
        "--target-recall",
        type=float,
        default=None,
        help="event-level recall the operating point must reach",
    )
    p.add_argument(
        "--operating-point",
        choices=("event_recall", "interval_recall", "accuracy"),
        default=None,
        help="rule for choosing the decision threshold (default event_recall)",
    )
    p.add_argument(
        "--target-accuracy",
        type=float,
        default=None,
        help="accuracy to reach when --operating-point accuracy",
    )
    p.add_argument("--negative-keep-rate", type=float, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--device", default=None, choices=("auto", "cpu", "cuda"))
    p.add_argument("--no-baselines", action="store_true")
    p.add_argument("--no-mlflow", action="store_true")
    p.add_argument("--config", default=None, help="load a saved config.json first")
    return p.parse_args()


def build_config(args: argparse.Namespace) -> Config:
    cfg = Config.from_json(args.config) if args.config else Config()

    if args.epochs is not None:
        cfg.train.epochs = args.epochs
    if args.batch_size is not None:
        cfg.train.batch_size = args.batch_size
    if args.learning_rate is not None:
        cfg.train.learning_rate = args.learning_rate
    if args.hidden_size is not None:
        cfg.model.hidden_size = args.hidden_size
    if args.num_layers is not None:
        cfg.model.num_layers = args.num_layers
    if args.sequence_steps is not None:
        cfg.windows.sequence_steps = args.sequence_steps
    if args.loss is not None:
        cfg.train.loss = args.loss
    if args.no_attention:
        cfg.model.attention = False
    if args.no_skip:
        cfg.model.last_step_skip = False
    if args.dropout is not None:
        cfg.model.dropout = args.dropout
    if args.patience is not None:
        cfg.train.patience = args.patience
    if args.input_norm is not None:
        cfg.model.input_norm = args.input_norm
    if args.target_recall is not None:
        cfg.target_recall = args.target_recall
    if args.operating_point is not None:
        cfg.operating_point = args.operating_point
    if args.target_accuracy is not None:
        cfg.target_accuracy = args.target_accuracy
    if args.negative_keep_rate is not None:
        cfg.windows.negative_keep_rate = args.negative_keep_rate
    if args.seed is not None:
        cfg.train.seed = args.seed
        cfg.windows.seed = args.seed
    if args.device is not None:
        cfg.train.device = args.device
    if args.no_mlflow:
        cfg.train.use_mlflow = False
    return cfg


def main() -> int:
    args = parse_args()
    cfg = build_config(args)

    if args.source == "synthetic":
        from floodsense.pipeline import prepare_from_synthetic
        from floodsense.synthetic import SyntheticConfig

        print(
            "[floodsense] SYNTHETIC DATA. Metrics below validate the pipeline, "
            "not real-world skill."
        )
        prepared = prepare_from_synthetic(
            cfg,
            SyntheticConfig(
                days=args.days,
                n_stations=args.stations,
                seed=cfg.train.seed,
                target_alerts_per_station_month=args.alerts_per_station_month,
            ),
        )
    else:
        from floodsense.ingest.local import load_canonical
        from floodsense.pipeline import prepare

        tables = load_canonical(args.data_dir)
        print(
            f"[floodsense] REAL DATA from {args.data_dir}: "
            f"{len(tables['readings']):,} readings, "
            f"{len(tables['alerts']):,} alerts, "
            f"{len(tables['stations']):,} stations"
        )
        prepared = prepare(
            readings=tables["readings"],
            stations=tables["stations"],
            alerts=tables["alerts"],
            cfg=cfg,
            flood_prone_points=tables.get("flood_prone_points"),
        )

    print(json.dumps(prepared.report(), indent=2, default=str))

    result = train(
        prepared, cfg, args.outdir, run_baselines=not args.no_baselines
    )

    if result.baselines:
        from floodsense.baselines import comparison_table

        print("\n" + comparison_table(result.baselines, result.test_report.to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
