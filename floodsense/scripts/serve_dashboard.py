#!/usr/bin/env python3
"""Serve the dashboard and the results it reads.

    python scripts/serve_dashboard.py          # http://127.0.0.1:8000/dashboard/

The dashboard fetches ``../results/final_metrics.json`` at load time rather
than having numbers written into it, so it needs an HTTP origin: opening the
file directly makes the browser refuse the fetch. This serves the project
root so both ``/dashboard/`` and ``/results/`` resolve.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        # The dashboard must never show a stale run's numbers.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args()

    metrics = ROOT / "results" / "final_metrics.json"
    if metrics.exists():
        payload = json.loads(metrics.read_text())
        print(
            f"serving {metrics.relative_to(ROOT)}: model {payload.get('model')}, "
            f"accuracy {payload.get('accuracy', 0) * 100:.2f}%, "
            f"event recall {payload.get('event_recall', 0) * 100:.1f}%"
        )
    else:
        print(
            f"note: {metrics} does not exist yet - run "
            "scripts/final_evaluation.py first; the page will say so."
        )

    handler = functools.partial(Handler, directory=str(ROOT))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((args.host, args.port), handler) as httpd:
        print(f"dashboard: http://{args.host}:{args.port}/dashboard/")
        print("ctrl-c to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
