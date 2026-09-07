#!/usr/bin/env python
"""Resolve open item O-1: how do we actually reach api.mospi.gov.in?

This script makes real network calls and must be run by a human on a machine
with internet access. It answers three questions the architecture is currently
guessing at, and writes the answers to a committed evidence file so the guess
becomes a record.

    1. Does the API require a bearer token?
       The official NSO client sets no Authorization header anywhere, which
       suggests not - but "suggests" is not "verified".

    2. Which TLS rung works?
       The official client disables certificate verification entirely, citing
       legacy renegotiation. ADR-016 says we climb a ladder instead, keeping
       verification on at every rung. This finds out which rung succeeds.

    3. What does robots.txt actually say?
       ADR-019 argues robots.txt does not govern API access. That argument is
       stronger if we know what it says rather than assuming.

Nothing here is destructive and no credentials are used. It needs ``certifi``
(trust anchors come from certifi, not the host store - see collector/tls.py), so
run it with the project venv:

    .venv/Scripts/python scripts/smoke_mospi.py

Output goes to docs/evidence/O1-mospi-api.md, which should be committed.
"""

from __future__ import annotations

import importlib.util
import json
import ssl
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _load_tls_module():
    """Load collector/tls.py directly, without importing the collector package.

    A network diagnostic should still run when the project is broken - that is
    when it is most needed. Importing ``collector`` pulls in the adapter chain
    and on down to SQLAlchemy, so a missing database driver would stop us
    finding out whether we can reach MoSPI at all. Loading the one module by
    path keeps the dependency surface to certifi alone.
    """
    path = _REPO / "packages" / "collector" / "tls.py"
    spec = importlib.util.spec_from_file_location("apix_tls_standalone", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before executing: tls.py uses `from __future__ import annotations`
    # with dataclasses, and dataclasses resolves those string annotations by
    # looking the defining module up in sys.modules. Skip this and the lookup
    # returns None the moment the first dataclass is processed.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_tls = _load_tls_module()
TlsLadder = _tls.TlsLadder
TlsMode = _tls.TlsMode
build_ssl_context = _tls.build_ssl_context

BASE = "https://api.mospi.gov.in"
ENDPOINTS = [
    "/api/cpi/getCpiBaseYear",
    "/api/cpi/getCpiFilterByLevelAndBaseYear?base_year=2024&level=Item&series_code=Current",
]
USER_AGENT = "APIx-Research/0.1 (+https://github.com/sujal128005/apix; MoSPI SIH 2026 PS 26056)"
EVIDENCE = _REPO / "docs" / "evidence" / "O1-mospi-api.md"


def attempt(url: str, mode: TlsMode, *, token: str | None = None) -> dict[str, object]:
    """One request on one TLS rung. Returns a record, never raises."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)
    record: dict[str, object] = {"url": url, "tls_mode": str(mode), "authenticated": bool(token)}
    try:
        context = build_ssl_context(mode)
    except FileNotFoundError as exc:
        record |= {"ok": False, "error": f"context unavailable: {exc}"}
        return record

    try:
        with urllib.request.urlopen(request, timeout=20, context=context) as response:
            body = response.read(4000).decode("utf-8", errors="replace")
            record |= {
                "ok": True,
                "http_status": response.status,
                "content_type": response.headers.get("Content-Type"),
                "body_head": body[:600],
            }
    except urllib.error.HTTPError as exc:
        record |= {"ok": False, "http_status": exc.code, "reason": str(exc.reason)}
    except ssl.SSLError as exc:
        record |= {"ok": False, "error_type": "ssl", "error": repr(exc)}
    except (urllib.error.URLError, TimeoutError) as exc:
        record |= {"ok": False, "error_type": "transport", "error": repr(exc)}
    return record


def fetch_robots() -> dict[str, object]:
    url = f"{BASE}/robots.txt"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(
            request, timeout=20, context=build_ssl_context(TlsMode.LEGACY)
        ) as response:
            return {"http_status": response.status, "body": response.read(2000).decode("utf-8")}
    except urllib.error.HTTPError as exc:
        return {"http_status": exc.code, "body": None, "reason": str(exc.reason)}
    except Exception as exc:
        return {"http_status": None, "body": None, "error": repr(exc)}


def main() -> int:
    started = datetime.now(UTC)
    print(f"APIx O-1 smoke test - {started.isoformat()}")
    print(f"Target: {BASE}\n")

    results: list[dict[str, object]] = []
    working_mode: TlsMode | None = None
    reached_status: int | None = None

    # A TLS rung "works" when the handshake completes and the server answers -
    # even with 401 or 403. Those are HTTP verdicts about authorisation, not
    # transport failures, and conflating them would send a reader chasing a
    # certificate problem that does not exist.
    for mode in TlsLadder().modes():
        print(f"[TLS {mode}] {ENDPOINTS[0]}")
        record = attempt(f"{BASE}{ENDPOINTS[0]}", mode)
        results.append(record)
        status = record.get("http_status")
        if record.get("ok"):
            print(f"    -> OK (HTTP {status})")
            working_mode, reached_status = mode, int(status) if status else None
            break
        if status is not None:
            print(f"    -> TLS OK, HTTP {status} ({record.get('reason')})")
            working_mode, reached_status = mode, int(status)
            break
        print(f"    -> TRANSPORT/TLS FAILED: {record.get('error')}")

    if working_mode is None:
        print("\nNo TLS rung completed a handshake with verification on.")
        print("Per ADR-016 we do NOT disable verification. Options, in order:")
        print("  1. Retry from a network without TLS interception (VPN/AV off).")
        print("  2. Export the server certificate and use the PINNED rung.")
        print("  3. Record the host as unreachable and rely on Tier 1/3 evidence.")
    else:
        print(f"\nTLS works on rung: {working_mode} (verification stayed on)")
        if reached_status in (401, 403):
            print(f"Access refused with HTTP {reached_status}.")
            print("This is an authorisation answer, not a TLS one. Likely causes:")
            print("  - a bearer token IS required after all (contradicts the NSO client)")
            print("  - the User-Agent or origin is filtered")
            print("  - the endpoint path has changed")
            print("Do NOT disable certificate verification: TLS is not the problem.")
        elif reached_status == 200:
            print("Unauthenticated access succeeded - no bearer token needed.")
            for endpoint in ENDPOINTS[1:]:
                print(f"[TLS {working_mode}] {endpoint}")
                results.append(attempt(f"{BASE}{endpoint}", working_mode))

    print("\n[robots.txt]")
    robots = fetch_robots()
    print(f"    -> HTTP {robots.get('http_status')}")

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        "\n".join(
            [
                "# O-1 evidence - api.mospi.gov.in",
                "",
                f"Run at: {started.isoformat()}",
                f"User-Agent: `{USER_AGENT}`",
                f"TLS rung that completed a handshake: **{working_mode or 'NONE'}**",
                f"HTTP status from the first endpoint: **{reached_status or 'no response'}**",
                "",
                "Certificate verification was enabled on every attempt (ADR-016).",
                "No credentials were used.",
                "",
                "## Attempts",
                "",
                "```json",
                json.dumps(results, indent=2, default=str),
                "```",
                "",
                "## robots.txt",
                "",
                "```json",
                json.dumps(robots, indent=2, default=str),
                "```",
                "",
                "## Conclusions to record",
                "",
                "- Bearer token required? "
                + (
                    "No - an unauthenticated request returned 200."
                    if reached_status == 200
                    else f"Probably yes, or access is otherwise filtered - HTTP {reached_status}."
                    if reached_status in (401, 403)
                    else f"Unknown - HTTP {reached_status}."
                    if reached_status
                    else "Unknown - no HTTP response was received."
                ),
                "- TLS: "
                + (
                    f"`{working_mode}` completed a handshake with verification on. "
                    "Certificate verification was never disabled."
                    if working_mode
                    else "no rung completed a handshake; see the script output for options."
                ),
                "- robots.txt: see above. Per ADR-019 it does not govern API access, "
                "but the record is kept.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"\nEvidence written to {EVIDENCE.relative_to(_REPO)}")
    print("Commit that file - it turns an assumption into a record.")
    return 0 if working_mode else 1


if __name__ == "__main__":
    raise SystemExit(main())
