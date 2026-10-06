#!/usr/bin/env python3
"""Ablations: check that each architecture choice actually pays.

Every variant trains on the same synthetic data, with the same splits,
seed and schedule, changing one thing. The point is to make the README's
claims reproducible rather than asserted - in particular that input
LayerNorm *hurts* here, and that the recurrence beats its own baselines.

    # Fast check, a few minutes per variant
    python scripts/ablate.py --days 150 --epochs 8

    # The variants the README quotes
    python scripts/ablate.py --days 400 --epochs 25 \
        --variants baseline no_skip layer_norm no_attention

Variants:

  ``baseline``      the shipped configuration
  ``layer_norm``    input_norm="layer" - expected to be clearly worse
  ``no_skip``       drop the last-step skip connection
  ``no_attention``  pool the last hidden state instead of attending
  ``short_window``  12 steps (1 h) of history instead of 36 (3 h)
  ``weighted_bce``  swap focal loss for weighted BCE
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.config import Config  # noqa: E402

VARIANTS = {
    "baseline": {},
    "layer_norm": {"model.input_norm": "layer"},
    "no_skip": {"model.last_step_skip": False},
    "no_attention": {"model.attention": False},
    "short_window": {"windows.sequence_steps": 12},
    "weighted_bce": {"train.loss": "weighted_bce"},
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--days", type=int, default=150)
    p.add_argument("--stations", type=int, default=32)
    p.add_argument("--epochs", type=int, default=8)
    p.add_argument("--hidden-size", type=int, default=64)
    p.add_argument("--learning-rate", type=float, default=7e-4)
    p.add_argument("--dropout", type=float, default=0.25)
    p.add_argument("--patience", type=int, default=5)
    p.add_argument("--seed", type=int, default=20260101)
    p.add_argument("--outdir", default="artifacts/ablation")
    p.add_argument(
        "--variants", nargs="*", default=["baseline", "layer_norm"],
        help=f"any of: {', '.join(VARIANTS)}",
    )
    return p.parse_args()


def apply_override(cfg: Config, path: str, value) -> None:
    section, _, field = path.partition(".")
    target = getattr(cfg, section) if field else cfg
    setattr(target, field or section, value)


def build_config(args: argparse.Namespace, overrides: dict) -> Config:
    cfg = Config()
    cfg.train.epochs = args.epochs
    cfg.train.learning_rate = args.learning_rate
    cfg.train.patience = args.patience
    cfg.train.seed = args.seed
    cfg.train.use_mlflow = False
    cfg.windows.seed = args.seed
    cfg.model.hidden_size = args.hidden_size
    cfg.model.dropout = args.dropout
    for path, value in overrides.items():
        apply_override(cfg, path, value)
    return cfg


def main() -> int:
    args = parse_args()
    unknown = [v for v in args.variants if v not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown variant(s): {unknown}; choose from {list(VARIANTS)}")

    from floodsense.pipeline import prepare_from_synthetic
    from floodsense.synthetic import SyntheticConfig
    from floodsense.train import train

    print(
        f"Ablation on synthetic data: {args.days} days, {args.stations} stations, "
        f"{args.epochs} epochs max, seed {args.seed}\n"
    )

    rows = []
    for name in args.variants:
        overrides = VARIANTS[name]
        cfg = build_config(args, overrides)
        print(f"=== {name} === {overrides or '(shipped configuration)'}")

        # Rebuilt per variant because sequence_steps changes the splits.
        prepared = prepare_from_synthetic(
            cfg,
            SyntheticConfig(
                days=args.days, n_stations=args.stations, seed=args.seed
            ),
        )

        started = time.time()
        result = train(
            prepared,
            cfg,
            Path(args.outdir) / name,
            run_baselines=(name == "baseline"),
            verbose=True,
        )
        rows.append(
            {
                "variant": name,
                "override": json.dumps(overrides),
                "val_pr_auc": result.best_val_pr_auc,
                "test_pr_auc": result.test_report.pr_auc,
                "test_roc_auc": result.test_report.roc_auc,
                "test_event_recall": result.test_event_report.event_recall,
                "false_alarms_per_station_day": (
                    result.test_event_report.false_alarms_per_station_day
                ),
                "minutes": (time.time() - started) / 60.0,
            }
        )
        if result.baselines:
            for label, payload in result.baselines.items():
                if isinstance(payload, dict) and "test" in payload:
                    rows.append(
                        {
                            "variant": f"(baseline) {label}",
                            "override": "",
                            "val_pr_auc": float("nan"),
                            "test_pr_auc": payload["test"]["pr_auc"],
                            "test_roc_auc": payload["test"]["roc_auc"],
                            "test_event_recall": float("nan"),
                            "false_alarms_per_station_day": float("nan"),
                            "minutes": 0.0,
                        }
                    )
        print()

    print("| variant | override | val PR-AUC | test PR-AUC | test ROC-AUC | event recall | FA/station-day |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        print(
            f"| {row['variant']} | `{row['override']}` | "
            f"{row['val_pr_auc']:.4f} | {row['test_pr_auc']:.4f} | "
            f"{row['test_roc_auc']:.4f} | {row['test_event_recall']:.3f} | "
            f"{row['false_alarms_per_station_day']:.2f} |"
        )

    out = Path(args.outdir) / "ablation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))
    print(f"\nWritten to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
