#!/usr/bin/env python3
"""Exercise a trained run: predict, explain, simulate.

    python scripts/demo.py --run artifacts/run_synth_v1

Scores every station at one timestep, prints the priority list, explains the
top location, and runs the rainfall-scaling scenarios.  With
``--source synthetic`` it regenerates the same synthetic grid the run was
trained on; with ``--source local`` it reads staged real data.

``--json`` writes the full dashboard payload, which is the contract a
front end would consume.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.config import Config  # noqa: E402
from floodsense.grid import RainGrid  # noqa: E402
from floodsense.infer import FloodSenseService  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--run", default="artifacts/run_synth_v1", help="artifact directory")
    p.add_argument("--source", choices=("synthetic", "local"), default="synthetic")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--days", type=int, default=270)
    p.add_argument("--stations", type=int, default=32)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument(
        "--step",
        type=int,
        default=None,
        help="grid step to score; default is the busiest step in the record",
    )
    p.add_argument("--top", type=int, default=8, help="rows in the priority list")
    p.add_argument("--json", default=None, help="write the dashboard payload here")
    return p.parse_args()


def build_grid(args: argparse.Namespace, config: Config) -> RainGrid:
    if args.source == "synthetic":
        from floodsense.synthetic import SyntheticConfig, generate

        bundle = generate(
            SyntheticConfig(
                days=args.days,
                n_stations=args.stations,
                seed=args.seed if args.seed is not None else config.train.seed,
            )
        )
        return RainGrid.from_long(bundle.readings, bundle.stations)

    from floodsense.ingest.local import load_canonical

    tables = load_canonical(args.data_dir)
    return RainGrid.from_long(tables["readings"], tables["stations"])


def pick_step(grid: RainGrid, config: Config) -> int:
    """Score the wettest step, so the demo shows the model working.

    Warm-up is respected: the longest accumulation window plus the sequence
    length must fit before the chosen step.
    """
    from floodsense.features import rolling_sum
    from floodsense.schema import STEP_MINUTES

    history = max(
        int(round(m / STEP_MINUTES)) for m in config.features.accumulation_minutes
    )
    earliest = history + config.windows.sequence_steps
    if grid.n_steps <= earliest:
        raise SystemExit(
            f"record too short: {grid.n_steps} steps, need more than {earliest}"
        )

    island_rain = rolling_sum(grid.filled(0.0), 6).sum(axis=1)
    island_rain[:earliest] = -1.0
    return int(island_rain.argmax())


def main() -> int:
    args = parse_args()
    service = FloodSenseService.from_artifacts(args.run)
    grid = build_grid(args, service.config)
    step = args.step if args.step is not None else pick_step(grid, service.config)

    print(f"FloodSense demo | run={args.run} | source={args.source}")
    print(f"Scoring {grid.n_stations} stations at {grid.times[step]} (step {step})\n")

    table, sequences = service.score(grid, step)
    columns = [
        "station_id", "station_name", "flood_risk_score", "risk_band",
        "flood_probability_30_60min", "rain_30min_mm", "rain_60min_mm",
    ]
    print("PRIORITY LIST (highest Flood Risk Score first)")
    print(table.loc[:, columns].head(args.top).to_string(index=False))

    counts = service.scorer.band_counts(table["flood_risk_score"].to_numpy())
    print(f"\nBAND COUNTS  {counts}")

    top_station = str(table.iloc[0]["station_id"])
    explanation = service.explain(
        grid, top_station, step, sequences=sequences,
        band=str(table.iloc[0]["risk_band"]),
    )
    print(f"\nEXPLANATION for {top_station}")
    print(f"  {explanation.sentence}")
    print(f"  probability: {explanation.probability:.4f}")
    for factor in explanation.factors:
        print(
            f"    {factor.direction:>6} | {factor.contribution:+.4f} | {factor.phrase}"
        )
    print(f"  attention in last 30 min: {explanation.attention_recent_share:.0%}")
    print(f"  caveat: {explanation.caveat}")

    simulation = service.simulate(grid, step)
    print("\nWHAT-IF: rainfall scaled over the last 60 minutes")
    print(simulation.table())
    print(f"  {simulation.disclaimer}")

    print("\nFLOOD RISK SCORE definition")
    definition = service.scorer.to_dict()
    print(f"  weights: {definition['weights']}")
    print(f"  bands:   Low<={definition['band_edges'][0]} "
          f"Moderate<={definition['band_edges'][1]} "
          f"High<={definition['band_edges'][2]} Critical>{definition['band_edges'][2]}")
    print(f"  {definition['disclaimer']}")

    if args.json:
        payload = service.dashboard_payload(grid, step, top_n=args.top)
        Path(args.json).write_text(json.dumps(payload, indent=2, default=str))
        print(f"\nDashboard payload written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
