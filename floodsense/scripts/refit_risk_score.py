#!/usr/bin/env python3
"""Re-fit the Flood Risk Score's normalisation references in place.

The score blends the model's probability with rainfall intensity,
accumulation and location vulnerability. Only the probability comes from
the network; the other three are normalised against percentiles of the
training data. Those references are therefore a *separate* fitted artifact,
and re-fitting them does not touch the model.

Worth doing when:

* the reference period should move (a new wet season is in the record);
* the score's weights or band edges changed in the config;
* an older run's ``risk_scorer.json`` predates a fix to how the references
  are computed.

    python scripts/refit_risk_score.py --run artifacts/run_synth_v3 \
        --source synthetic --days 400 --stations 32

The run's own ``config.json`` supplies the weights, bands and split
boundaries, so the references are measured over the same training region
the model saw.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.config import Config  # noqa: E402
from floodsense.risk import RiskScorer  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--run", required=True, help="artifact directory to update")
    p.add_argument("--source", choices=("synthetic", "local"), default="synthetic")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--days", type=int, default=400)
    p.add_argument("--stations", type=int, default=32)
    p.add_argument(
        "--no-backup", action="store_true", help="skip the .bak copy"
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    run = Path(args.run)
    target = run / "risk_scorer.json"
    config_path = run / "config.json"
    if not config_path.exists():
        raise SystemExit(f"{config_path} not found; is --run an artifact directory?")

    cfg = Config.from_json(config_path)

    if args.source == "synthetic":
        from floodsense.pipeline import prepare_from_synthetic
        from floodsense.synthetic import SyntheticConfig

        prepared = prepare_from_synthetic(
            cfg,
            SyntheticConfig(
                days=args.days, n_stations=args.stations, seed=cfg.train.seed
            ),
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

    if target.exists():
        previous = json.loads(target.read_text())
        print("before:")
        for key in (
            "intensity_reference", "accumulation_reference", "vulnerability_reference"
        ):
            print(f"  {key}: {previous.get(key)}")
        if not args.no_backup:
            shutil.copy2(target, target.with_suffix(".json.bak"))
            print(f"  backed up to {target.with_suffix('.json.bak')}")

    scorer = RiskScorer.from_prepared(prepared, cfg.risk)
    target.write_text(json.dumps(scorer.to_dict(), indent=2))

    print("after:")
    payload = scorer.to_dict()
    for key in (
        "intensity_reference", "accumulation_reference", "vulnerability_reference"
    ):
        print(f"  {key}: {payload[key]}")
    print(f"  fitted on: {payload['fitted_on'].get('description', '')}")
    print(f"\nwrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
