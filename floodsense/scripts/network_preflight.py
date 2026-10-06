#!/usr/bin/env python3
"""Diagnose access to the official Singapore open-data hosts.

    python scripts/network_preflight.py
    python scripts/network_preflight.py --api-key "$DATAGOV_API_KEY"

Runs DNS, proxy CONNECT, TLS and HTTP in that order and stops at the first
layer that blocks, so the output names the layer rather than the symptom.
Writes ``results/network_preflight.json``.

Exit status: 0 when the APIs are reachable, 2 when they are not — so a
pipeline script can gate on it.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from floodsense.ingest.discovery import (  # noqa: E402
    FLOOD_ALERT_CANDIDATES,
    KNOWN_ENDPOINTS,
    discover_flood_alert_endpoint,
    preflight,
)
from floodsense.schema import (  # noqa: E402
    FLOOD_ALERTS_DATASET,
    FLOOD_PRONE_AREAS_DATASET,
    REALTIME_RAINFALL_DATASET,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--api-key",
        default=os.environ.get("DATAGOV_API_KEY"),
        help="data.gov.sg API key; also read from DATAGOV_API_KEY",
    )
    p.add_argument("--out", default="results/network_preflight.json")
    p.add_argument(
        "--discover",
        action="store_true",
        help="when reachable, probe for the flood-alerts endpoint",
    )
    args = p.parse_args()

    report = preflight(api_key=args.api_key)
    print(report.summary())

    payload = report.to_dict()
    payload["api_key_supplied"] = bool(args.api_key)
    payload["datasets"] = {
        "realtime_rainfall": REALTIME_RAINFALL_DATASET,
        "flood_alerts": FLOOD_ALERTS_DATASET,
        "flood_prone_areas": FLOOD_PRONE_AREAS_DATASET,
    }
    payload["documented_endpoints"] = dict(KNOWN_ENDPOINTS)
    payload["flood_alert_endpoint"] = None
    payload["flood_alert_candidates"] = list(FLOOD_ALERT_CANDIDATES)
    payload["flood_alert_endpoint_note"] = (
        "Not asserted. The rainfall path is documented; the PUB flood-alerts "
        "path is not, so it is discovered by probing when the network is "
        "reachable. An invented path would 404 in a way that looks like "
        "'no floods today'."
    )

    if report.reachable and args.discover:
        print("\nDiscovering the flood-alerts endpoint...")
        endpoint, probes = discover_flood_alert_endpoint(api_key=args.api_key)
        payload["flood_alert_endpoint"] = endpoint
        payload["flood_alert_probes"] = [pr.to_dict() for pr in probes]
        print(
            f"  -> {endpoint}" if endpoint
            else "  -> none of the candidates answered; check the dataset page"
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    import json

    out.write_text(json.dumps(payload, indent=2))
    print(f"\nwritten to {out}")

    if not report.reachable:
        print(
            "\nREAL DATA NOT AVAILABLE. FloodSense will not fabricate it and "
            "will not route around the policy."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
