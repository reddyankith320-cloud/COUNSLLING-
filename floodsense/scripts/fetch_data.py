#!/usr/bin/env python3
"""Stage the four official datasets into the canonical layout.

Needs outbound access to ``data.gov.sg`` and ``api-open.data.gov.sg``.  Run
it once; training then reads from disk, so a run is reproducible and does
not re-spend anyone's API quota.

    # Live rainfall snapshot plus current alerts (quick smoke test)
    python scripts/fetch_data.py --out data/ --realtime

    # A date range of 5-minute rainfall from the real-time API
    python scripts/fetch_data.py --out data/ --from 2026-09-01 --to 2026-09-30

    # Annual historical CSVs already downloaded by hand
    python scripts/fetch_data.py --out data/ --historical-dir ~/Downloads/rainfall

Historical rainfall is published as one CSV per year (2016-2024), and the
2024 file alone is ~6.4M rows / 1.1 GB.  Download those from the dataset
pages (or with ``--historical-dataset`` which resolves a signed URL) rather
than pulling eight years through the 5-minute API.

Note on labels: a model needs *historical* flood alerts to learn from.  PUB
began publishing alerts by API in November 2025, so the alert history
available through the API is short.  Appending each day's snapshot to
``alerts.csv`` over time is the practical way to accumulate it - pass
``--append-alerts``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.ingest.flood_prone import (  # noqa: E402
    fetch_flood_prone_areas,
    load_flood_prone_areas,
    load_flood_prone_points,
)
from floodsense.ingest.historical import (  # noqa: E402
    load_historical_dir,
    resolve_download_url,
)
from floodsense.ingest.local import save_canonical  # noqa: E402
from floodsense.ingest.realtime import (  # noqa: E402
    fetch_flood_alerts,
    fetch_rainfall,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--out", default="data", help="output directory")
    p.add_argument("--api-key", default=None, help="data.gov.sg API key")

    p.add_argument("--realtime", action="store_true", help="latest rainfall snapshot")
    p.add_argument("--from", dest="date_from", default=None, help="YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", default=None, help="YYYY-MM-DD")

    p.add_argument(
        "--historical-dir", default=None, help="directory of annual rainfall CSVs"
    )
    p.add_argument(
        "--historical-dataset",
        default=None,
        help="a d_* dataset id to resolve a signed download URL for",
    )

    p.add_argument(
        "--flood-prone-points",
        default=None,
        help="CSV of geocoded PUB flood-prone locations",
    )
    p.add_argument(
        "--no-alerts", action="store_true", help="skip the flood-alerts API"
    )
    p.add_argument(
        "--append-alerts",
        action="store_true",
        help="merge into any existing alerts file instead of replacing it",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.historical_dataset:
        url = resolve_download_url(args.historical_dataset)
        print(f"[fetch] signed download URL for {args.historical_dataset}:\n{url}")
        print("[fetch] download it, then re-run with --historical-dir")
        return 0

    readings_parts: list[pd.DataFrame] = []
    stations_parts: list[pd.DataFrame] = []

    if args.historical_dir:
        print(f"[fetch] reading annual CSVs from {args.historical_dir}")
        readings, stations = load_historical_dir(args.historical_dir)
        print(f"[fetch]   {len(readings):,} readings, {len(stations)} stations")
        readings_parts.append(readings)
        stations_parts.append(stations)

    dates: list[str | None] = []
    if args.date_from and args.date_to:
        dates = [
            d.strftime("%Y-%m-%d")
            for d in pd.date_range(args.date_from, args.date_to, freq="D")
        ]
    elif args.realtime:
        dates = [None]

    for date in dates:
        label = date or "latest"
        try:
            readings, stations = fetch_rainfall(date=date, api_key=args.api_key)
        except Exception as exc:  # one bad day must not lose the rest
            print(f"[fetch] rainfall {label}: FAILED ({exc})")
            continue
        print(f"[fetch] rainfall {label}: {len(readings):,} readings")
        readings_parts.append(readings)
        stations_parts.append(stations)

    if not readings_parts:
        print(
            "[fetch] nothing fetched. Pass --realtime, --from/--to, or "
            "--historical-dir."
        )
        return 2

    readings = (
        pd.concat(readings_parts, ignore_index=True)
        .drop_duplicates(["ts", "station_id"])
        .sort_values(["ts", "station_id"], ignore_index=True)
    )
    stations = pd.concat(stations_parts, ignore_index=True).drop_duplicates(
        "station_id", ignore_index=True
    )

    alerts = pd.DataFrame()
    if not args.no_alerts:
        try:
            alerts = fetch_flood_alerts(api_key=args.api_key)
            print(
                f"[fetch] flood alerts: {len(alerts)} record(s) "
                f"({alerts.attrs.get('dropped_without_location', 0)} without a location)"
            )
        except Exception as exc:
            print(f"[fetch] flood alerts: FAILED ({exc})")
            print(
                "[fetch]   confirm the endpoint on the dataset page and pass it "
                "via floodsense.ingest.realtime.FLOOD_ALERTS_URL"
            )

    existing = out / "alerts.csv"
    if args.append_alerts and existing.exists():
        previous = pd.read_csv(existing)
        alerts = (
            pd.concat([previous, alerts], ignore_index=True)
            .drop_duplicates("alert_id", ignore_index=True)
        )
        print(f"[fetch] alerts merged with existing history: {len(alerts)} total")

    try:
        areas = fetch_flood_prone_areas()
        print(f"[fetch] flood-prone areas: {len(areas)} rows from the datastore")
    except Exception as exc:
        areas = load_flood_prone_areas()
        print(f"[fetch] flood-prone areas: using published series ({exc})")

    points = (
        load_flood_prone_points(args.flood_prone_points)
        if args.flood_prone_points
        else None
    )
    if points is not None:
        print(f"[fetch] flood-prone points: {len(points)} geocoded locations")

    written = save_canonical(
        out,
        readings=readings,
        stations=stations,
        alerts=alerts,
        flood_prone_points=points,
        flood_prone_areas=areas,
    )
    for name, path in written.items():
        print(f"[fetch] wrote {name}: {path}")

    if alerts.empty:
        print(
            "\n[fetch] WARNING: no flood alerts staged. Training needs a "
            "positive class - accumulate alert snapshots over time with "
            "--append-alerts, or supply a historical alert file."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
