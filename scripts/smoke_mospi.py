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

Nothing here is destructive and no credentials are used. Run:

    py -3.12 scripts/smoke_mospi.py

Output goes to docs/evidence/O1-mospi-api.md, which should be committed.
"""

from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))

from collector.tls import TlsLadder, TlsMode, build_ssl_context

BASE = "https://api.mospi.gov.in"
ENDPOINTS = [
    "/api/cpi/getCpiBaseYear",
    "/api/cpi/getCpiFilterByLevelAndBaseYear?base_year=2024&level=Item&series_code=Current",
]
USER_AGENT = "APIx-Research/0.1 (+https://github.com/sujal128005/apix; MoSPI SIH 2026 PS 26056)"
EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "O1-mospi-api.md"


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

    for mode in TlsLadder().modes():
        print(f"[TLS {mode}] {ENDPOINTS[0]}")
        record = attempt(f"{BASE}{ENDPOINTS[0]}", mode)
        results.append(record)
        if record.get("ok"):
            status = "OK"
        else:
            detail = record.get("error") or record.get("reason") or "unknown"
            status = f"FAILED: {detail}"
        print(f"    -> {status}")
        if record.get("ok"):
            working_mode = mode
            break

    if working_mode is None:
        print("\nNo TLS rung reached the host with verification on.")
        print("Per ADR-016 we do NOT disable verification. Options, in order:")
        print("  1. Retry from a network without TLS interception (VPN/AV off).")
        print("  2. Export the server certificate and use the PINNED rung.")
        print("  3. Record the host as unreachable and rely on Tier 1/3 evidence.")
    else:
        print(f"\nWorking TLS rung: {working_mode}")
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
                f"Working TLS rung: **{working_mode or 'NONE - host not safely reachable'}**",
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
                    "No - an unauthenticated request succeeded."
                    if working_mode
                    else "Unknown - the host was not reached."
                ),
                "- TLS: "
                + (
                    f"`{working_mode}` works with verification on."
                    if working_mode
                    else "no verifying rung succeeded; see options in the script output."
                ),
                "- robots.txt: see above. Per ADR-019 it does not govern API access, "
                "but the record is kept.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"\nEvidence written to {EVIDENCE.relative_to(EVIDENCE.parents[2])}")
    print("Commit that file - it turns an assumption into a record.")
    return 0 if working_mode else 1


if __name__ == "__main__":
    raise SystemExit(main())
