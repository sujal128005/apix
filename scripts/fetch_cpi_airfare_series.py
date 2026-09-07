#!/usr/bin/env python
"""Fetch the official CPI 2024 **Airfare** index series (item 294).

O-2 established the code from MoSPI's own API:

    item_code 294 "Airfare"
    sub_class 125 · class 58 · group 24 · division 7 (Transport)

Airfare sits alone in class 58 and sub-class 125 - it is not pooled with rail,
bus or taxi - so the class-level index *is* the airfare index. That makes it a
direct comparator for APIx rather than the divisional proxy the backtest design
had assumed, and it is the strongest Tier-2 evidence available (ADR-015).

What this script does **not** do is claim comparability of levels. CPI 2024 is
based at 2024 = 100 with prices from calendar 2024; APIx will be based on its
own first thirty collection days. Only *movements* can be compared, and the
Backtest page has to say so. This script fetches the series and records it; the
comparison itself is Phase 10.

Run with the project venv:

    .venv/Scripts/python scripts/fetch_cpi_airfare_series.py
"""

from __future__ import annotations

import importlib.util
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
BASE = "https://api.mospi.gov.in"
USER_AGENT = "APIx-Research/0.1 (+https://github.com/sujal128005/apix; MoSPI SIH 2026 PS 26056)"
EVIDENCE = _REPO / "docs" / "evidence" / "O2b-cpi-airfare-series.md"

AIRFARE = {
    "item_code": "294",
    "item_name": "Airfare",
    "sub_class_code": "125",
    "class_code": "58",
    "group_code": "24",
    "division_code": "7",
}


def _load_tls():
    path = _REPO / "packages" / "collector" / "tls.py"
    spec = importlib.util.spec_from_file_location("apix_tls_standalone", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_tls = _load_tls()


def get(path: str, params: dict[str, str]) -> tuple[int | None, Any]:
    """One verified GET on the LEGACY rung (see O-1). Returns (status, payload)."""
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    context = _tls.build_ssl_context(_tls.TlsMode.LEGACY)
    try:
        with urllib.request.urlopen(request, timeout=45, context=context) as response:
            body = response.read().decode("utf-8")
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, {"non_json_body_head": body[:800]}
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": str(exc.reason), "body_head": exc.read()[:600].decode(
            "utf-8", errors="replace"
        )}
    except (urllib.error.URLError, ssl.SSLError, TimeoutError) as exc:
        return None, {"error": repr(exc)}


def count_records(payload: Any) -> int:
    """Best-effort count of data rows, without assuming a response shape."""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            return sum(len(v) for v in data.values() if isinstance(v, list))
    return 0


def _write_evidence(
    started: datetime,
    rows: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    *,
    ok: bool,
) -> None:
    """Record the run whether it succeeded or not.

    A failed fetch with a dated reason is evidence too - it is what lets the
    Backtest page say "we tried this, on this date, and here is what happened"
    rather than staying silent.
    """
    combined = [r for r in rows if str(r.get("sector")) == "Combined"]
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        "\n".join(
            [
                "# O-2b evidence - official CPI 2024 Airfare index series",
                "",
                f"Run at: {started.isoformat()}",
                f"Outcome: **{'SUCCESS' if ok else 'FAILED - do not use this data'}**",
                "Source: `api.mospi.gov.in/api/cpi/getCPIData`, LEGACY TLS rung, "
                "unauthenticated (see O-1).",
                "",
                "## The item",
                "",
                "```json",
                json.dumps(AIRFARE, indent=2),
                "```",
                "",
                "Sub-class 125 is *Passenger transport by air, **domestic***, COICOP",
                "`07.3.3.1.2.01`. MoSPI splits domestic from international at sub-class",
                "level, and APIx collects domestic routes only - so this is an exact scope",
                "match, not an approximation.",
                "",
                "## Pagination",
                "",
                "The endpoint defaults to 10 rows and caps `limit` at 100; asking for more",
                "returns HTTP 400 with an explicit message rather than a truncated page.",
                "Four differently-filtered queries all returned 10 rows, which is",
                "indistinguishable from a silently-ignored filter - so every row is checked",
                "to be item 294 before the data is used, and an empty result is treated as a",
                "failure rather than an empty series.",
                "",
                "```json",
                json.dumps(pages, indent=2),
                "```",
                "",
                f"Rows retrieved: **{len(rows)}** · Combined-sector months: "
                f"**{len(combined)}**",
                "",
                "## Series",
                "",
                "```json",
                json.dumps(rows, indent=2, ensure_ascii=False)[:200000],
                "```",
                "",
                "## Limits on how this may be used",
                "",
                "- CPI 2024 is based at **2024 = 100**, prices referenced to calendar 2024.",
                "- APIx will be based on its own first thirty collection days.",
                "- **Levels are therefore not comparable. Only movements are.**",
                "- Rural, Urban and Combined are published separately; APIx compares against",
                "  Combined and must say so.",
                "- The weight for item 294 is *not* in this endpoint. It must still be read",
                "  from Annexure 5.3 of the Expert Group Report, and two independent sources",
                "  must agree before any weight enters the repository.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    started = datetime.now(UTC)
    print(f"APIx O-2b - CPI 2024 Airfare series - {started.isoformat()}")
    print("Item 294 'Airfare' (division 7 / group 24 / class 58 / sub-class 125)\n")

    # The default page size is 10, so a single call returns three sectors and a
    # few months and looks deceptively like "the series". Paginate explicitly.
    all_rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    page = 1
    # The server caps this: {"error":"Limit parameter too large. Maximum allowed
    # is 100."} Measured 2026-09-07. Asking for more returns HTTP 400, not a
    # truncated page, so the cap has to be respected rather than discovered.
    limit = 100

    while page <= 20:  # bounded: 10k rows is far more than this item can have
        params = {
            "base_year": "2024",
            "item_code": AIRFARE["item_code"],
            "state_code": "1",
            "series_code": "Current",
            "limit": str(limit),
            "page": str(page),
        }
        print(f"[GET] page {page} (limit {limit})")
        status, payload = get("/api/cpi/getCPIData", params)
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        rows = rows if isinstance(rows, list) else []
        print(f"    -> HTTP {status}, {len(rows)} row(s)")
        pages.append({"page": page, "http_status": status, "rows": len(rows)})
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < limit:
            break
        page += 1

    # Every row must actually be the item we asked for. Four differently-filtered
    # queries returning identical counts is exactly how a silently-ignored filter
    # looks, so verify rather than assume.
    if not all_rows:
        print("\n!! No rows returned. This is a FAILURE, not an empty series.")
        print("   An integrity check that passes on zero rows reads like verification")
        print("   and provides none. Read the evidence file before retrying.")
        _write_evidence(started, [], pages, ok=False)
        return 1

    wrong = [r for r in all_rows if str(r.get("item", "")).strip().lower() != "airfare"]
    if wrong:
        print(f"\n!! {len(wrong)} of {len(all_rows)} rows are not Airfare.")
        print("   The item filter is not being applied. Filter client-side and record")
        print("   this as an API finding before using the data.")
        _write_evidence(started, all_rows, pages, ok=False)
        return 1

    print(f"\nAll {len(all_rows)} rows are Airfare. The item filter is applied server-side.")

    combined = [r for r in all_rows if str(r.get("sector")) == "Combined"]
    combined.sort(key=lambda r: (str(r.get("year")), str(r.get("month"))))
    print(f"Combined-sector months: {len(combined)}")
    if combined:
        first, last = combined[0], combined[-1]
        print(f"  range: {first.get('month')} {first.get('year')} .. "
              f"{last.get('month')} {last.get('year')}")
        imputed = sum(1 for r in combined if str(r.get("imputation")).upper() == "Y")
        print(f"  imputed months: {imputed} of {len(combined)}")

    _write_evidence(started, all_rows, pages, ok=True)
    benchmark = _REPO / "data" / "reference" / "cpi_airfare_benchmark.json"
    benchmark.write_text(
        json.dumps(
            {
                "_comment": "Official CPI 2024 domestic airfare index, item 294 "
                "(COICOP 07.3.3.1.2.01). Tier-2 benchmark for ADR-015. Fetched from "
                "MoSPI's open API; see docs/evidence/O2b-cpi-airfare-series.md.",
                "_usage": "Compare MOVEMENTS only. CPI is 2024=100; APIx is based on its "
                "own first 30 collection days. Levels are not comparable.",
                "provenance": "OFFICIAL_STATISTIC",
                "source_url": f"{BASE}/api/cpi/getCPIData",
                "retrieved_at": started.isoformat(),
                "item": AIRFARE,
                "rows": all_rows,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Evidence written to {EVIDENCE.relative_to(_REPO)}")
    print(f"Benchmark written to {benchmark.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
