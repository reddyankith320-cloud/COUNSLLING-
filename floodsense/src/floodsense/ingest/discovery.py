"""Network preflight and endpoint discovery for the official Singapore APIs.

Two jobs, both of which exist because guessing is not allowed here.

**Preflight** separates the failure modes that look identical from inside a
container: DNS failure, a blocked egress proxy, a TLS problem, an auth
rejection and a rate limit all surface as "it didn't work". The checks below
run in order and stop at the first layer that fails, so the report names the
layer rather than the symptom — and when the blocker is the environment's
allowlist, it names the hosts that must be allowed.

**Discovery** resolves dataset identifiers to their real endpoints through
data.gov.sg's own metadata API instead of hardcoding a path. The rainfall
endpoint is documented and stable; the PUB flood-alerts endpoint is newer and
its path is *not* asserted anywhere in this file. Inventing one would produce
a loader that 404s in a way that looks like "no floods today".

Documented facts this module relies on (data.gov.sg developer guide):

* real-time base: ``https://api-open.data.gov.sg/v2/real-time/api/``
* rainfall: ``GET /v2/real-time/api/rainfall`` with ``date``
  (``YYYY-MM-DD`` or ``YYYY-MM-DDTHH:mm:ss``) and ``paginationToken``
* auth: ``x-api-key`` header; without a key the v2 real-time limit is 6
  calls per 10 seconds (12 with a dev key, 30 with a prod key), enforced
  since 31 December 2025
"""

from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: Hosts FloodSense needs. Reported verbatim when the egress policy blocks
#: them, so the person has the exact allowlist entries to add.
REQUIRED_HOSTS: tuple[str, ...] = (
    "api-open.data.gov.sg",   # real-time rainfall + flood alerts
    "data.gov.sg",            # dataset metadata, CKAN datastore, CSV download
)

#: Useful but not required: PUB's site carries the published flood-prone
#: location list as PDFs, which must be geocoded by hand anyway.
OPTIONAL_HOSTS: tuple[str, ...] = ("www.pub.gov.sg", "pub.gov.sg")

REALTIME_BASE = "https://api-open.data.gov.sg/v2/real-time/api"
DATASET_METADATA = "https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/metadata"
DATASTORE_SEARCH = "https://data.gov.sg/api/action/datastore_search"

#: Only the rainfall path is documented well enough to hardcode.
KNOWN_ENDPOINTS: dict[str, str] = {"rainfall": f"{REALTIME_BASE}/rainfall"}

#: Candidate paths for the flood-alerts feed, tried in order **only when the
#: network is reachable**, and only to discover which one actually answers.
#: Nothing here is presented as the endpoint until a probe confirms it.
FLOOD_ALERT_CANDIDATES: tuple[str, ...] = (
    f"{REALTIME_BASE}/flood-alerts",
    f"{REALTIME_BASE}/flood-alert",
    f"{REALTIME_BASE}/floods",
)


@dataclass
class ProbeResult:
    """One layer of the preflight."""

    layer: str
    target: str
    ok: bool
    detail: str
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PreflightReport:
    probes: list[ProbeResult] = field(default_factory=list)
    reachable: bool = False
    blocked_hosts: list[str] = field(default_factory=list)
    blocking_layer: str = ""
    remedy: str = ""

    def to_dict(self) -> dict:
        return {
            "reachable": self.reachable,
            "blocking_layer": self.blocking_layer,
            "blocked_hosts": self.blocked_hosts,
            "required_hosts": list(REQUIRED_HOSTS),
            "optional_hosts": list(OPTIONAL_HOSTS),
            "remedy": self.remedy,
            "probes": [p.to_dict() for p in self.probes],
        }

    def write(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    def summary(self) -> str:
        lines = [
            f"Network preflight: {'REACHABLE' if self.reachable else 'BLOCKED'}"
        ]
        if not self.reachable:
            lines.append(f"  blocking layer : {self.blocking_layer}")
            lines.append(f"  blocked hosts  : {', '.join(self.blocked_hosts)}")
        for p in self.probes:
            lines.append(
                f"  [{'ok ' if p.ok else 'FAIL'}] {p.layer:<18} {p.target:<28} "
                f"{p.detail}"
            )
        if self.remedy:
            lines.append("")
            lines.append(self.remedy)
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Preflight layers
# --------------------------------------------------------------------------


def probe_dns(host: str, timeout: float = 10.0) -> ProbeResult:
    started = time.time()
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        addresses = sorted({i[4][0] for i in infos})
        return ProbeResult(
            "dns", host, True, f"resolves to {', '.join(addresses[:3])}",
            (time.time() - started) * 1000,
        )
    except socket.gaierror as exc:
        return ProbeResult(
            "dns", host, False, f"resolution failed: {exc}",
            (time.time() - started) * 1000,
        )


def probe_proxy_connect(host: str, timeout: float = 15.0) -> ProbeResult:
    """Ask the configured proxy to open a tunnel, and read its answer.

    This is the check that distinguishes an egress-policy denial from a
    network fault: a refused CONNECT returns an HTTP status *before* any TLS
    handshake, so the proxy's own message is the diagnosis.
    """
    import os

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        return ProbeResult("proxy", host, True, "no proxy configured; direct egress")

    parsed = urllib.parse.urlparse(proxy)
    started = time.time()
    try:
        sock = socket.create_connection(
            (parsed.hostname, parsed.port or 8080), timeout=timeout
        )
    except OSError as exc:
        return ProbeResult(
            "proxy", host, False, f"cannot reach proxy {proxy}: {exc}",
            (time.time() - started) * 1000,
        )

    try:
        sock.sendall(
            f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode()
        )
        raw = sock.recv(4096).decode("utf-8", errors="replace")
    except OSError as exc:
        return ProbeResult(
            "proxy", host, False, f"tunnel request failed: {exc}",
            (time.time() - started) * 1000,
        )
    finally:
        sock.close()

    elapsed = (time.time() - started) * 1000
    head, _, body = raw.partition("\r\n\r\n")
    status_line = head.splitlines()[0] if head else "(no response)"
    if " 200 " in status_line:
        return ProbeResult("proxy", host, True, "CONNECT tunnel granted", elapsed)
    return ProbeResult(
        "proxy", host, False,
        f"{status_line.strip()} - {body.strip() or 'no detail'}", elapsed,
    )


def probe_tls(host: str, timeout: float = 15.0) -> ProbeResult:
    """TLS handshake, only meaningful once a tunnel exists."""
    started = time.time()
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                cipher = tls.cipher()
                return ProbeResult(
                    "tls", host, True,
                    f"{tls.version()} {cipher[0] if cipher else ''}".strip(),
                    (time.time() - started) * 1000,
                )
    except Exception as exc:
        return ProbeResult(
            "tls", host, False, f"{type(exc).__name__}: {exc}",
            (time.time() - started) * 1000,
        )


def probe_http(url: str, api_key: str | None = None, timeout: float = 20.0) -> ProbeResult:
    """One HTTPS request, reporting status, redirects and rate limiting."""
    started = time.time()
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/json")
    if api_key:
        request.add_header("x-api-key", api_key)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2048).decode("utf-8", errors="replace")
            final = response.geturl()
            note = f"HTTP {response.status}"
            if final != url:
                note += f" (redirected to {final})"
            note += f", {len(body)} bytes"
            return ProbeResult(
                "http", url, True, note, (time.time() - started) * 1000
            )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        hint = ""
        if exc.code == 401 or exc.code == 403:
            hint = " - an API key may be required (x-api-key header)"
        elif exc.code == 429:
            hint = " - rate limited; use an API key for a higher limit"
        return ProbeResult(
            "http", url, False, f"HTTP {exc.code}{hint}: {detail}",
            (time.time() - started) * 1000,
        )
    except Exception as exc:
        return ProbeResult(
            "http", url, False, f"{type(exc).__name__}: {exc}",
            (time.time() - started) * 1000,
        )


def preflight(api_key: str | None = None, include_optional: bool = True) -> PreflightReport:
    """Run the full diagnosis, stopping at the first layer that blocks.

    Returns a report naming the blocking layer and the hosts to allow.
    """
    report = PreflightReport()
    hosts = list(REQUIRED_HOSTS) + (list(OPTIONAL_HOSTS) if include_optional else [])

    dns_failures, proxy_failures = [], []
    for host in hosts:
        dns = probe_dns(host)
        report.probes.append(dns)
        if not dns.ok:
            dns_failures.append(host)
            continue
        tunnel = probe_proxy_connect(host)
        report.probes.append(tunnel)
        if not tunnel.ok:
            proxy_failures.append(host)

    required_blocked = [h for h in REQUIRED_HOSTS if h in proxy_failures]
    required_unresolved = [h for h in REQUIRED_HOSTS if h in dns_failures]

    if required_unresolved:
        report.blocking_layer = "dns"
        report.blocked_hosts = required_unresolved
        report.remedy = (
            "DNS does not resolve these hosts. Check the container's resolver "
            "before changing anything else."
        )
        return report

    if required_blocked:
        report.blocking_layer = "egress_policy"
        report.blocked_hosts = required_blocked
        report.remedy = (
            "The environment's network policy refused the CONNECT tunnel for "
            "these hosts (HTTP 403 from the proxy, before TLS). Allow them in "
            "the environment's Network access settings - either a broader "
            "access level, or Custom with these under Allowed domains, keeping "
            "the default package-manager list:\n  "
            + "\n  ".join(REQUIRED_HOSTS)
            + "\nThen re-run this preflight. Nothing in FloodSense attempts to "
            "work around the policy."
        )
        return report

    # Tunnels are open: now the application layers can be tested.
    for host in REQUIRED_HOSTS:
        report.probes.append(probe_tls(host))

    rainfall = probe_http(f"{KNOWN_ENDPOINTS['rainfall']}", api_key=api_key)
    report.probes.append(rainfall)
    report.reachable = rainfall.ok
    if not rainfall.ok:
        report.blocking_layer = "application"
        report.remedy = (
            "Hosts are reachable but the rainfall endpoint did not answer. "
            "If the status is 401/403, supply an API key (x-api-key); if 429, "
            "the rate limit applies - a dev key raises it from 6 to 12 calls "
            "per 10 seconds."
        )
    return report


# --------------------------------------------------------------------------
# Endpoint discovery
# --------------------------------------------------------------------------


def fetch_dataset_metadata(
    dataset_id: str, api_key: str | None = None, timeout: float = 20.0
) -> dict[str, Any]:
    """Official metadata for a dataset id, used instead of guessing paths."""
    url = DATASET_METADATA.format(dataset_id=dataset_id)
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/json")
    if api_key:
        request.add_header("x-api-key", api_key)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def discover_flood_alert_endpoint(
    api_key: str | None = None, timeout: float = 15.0
) -> tuple[str | None, list[ProbeResult]]:
    """Probe the candidate paths and return the one that answers.

    Returns ``(endpoint, probes)``; ``endpoint`` is None when none answered,
    which is reported as "unknown" rather than defaulted to a guess.
    """
    probes = []
    for candidate in FLOOD_ALERT_CANDIDATES:
        probe = probe_http(candidate, api_key=api_key, timeout=timeout)
        probes.append(probe)
        if probe.ok:
            return candidate, probes
    return None, probes
