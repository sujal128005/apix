#!/usr/bin/env python
"""Resolve open item O-2: the CPI 2024 item code and weight for air fare.

O-1 established that ``api.mospi.gov.in`` answers unauthenticated requests over
the LEGACY TLS rung. This script uses that to ask MoSPI directly for the CPI 2024
item list, rather than reading a 252-page PDF annexure.

It prints every item whose name looks transport-related and dumps the full list
to evidence, so the airfare item can be identified by eye rather than by a
regex that might quietly match the wrong thing. Naming it wrong would be worse
than leaving it UNKNOWN: a plausible but incorrect item code would put a real
number on the Methodology page that nobody would think to question.

Run with the project venv, since certifi is needed:

    .venv/Scripts/python scripts/find_cpi_airfare_item.py
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
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
BASE = "https://api.mospi.gov.in"
USER_AGENT = "APIx-Research/0.1 (+https://github.com/sujal128005/apix; MoSPI SIH 2026 PS 26056)"
EVIDENCE = _REPO / "docs" / "evidence" / "O2-cpi-airfare-item.md"

# Words that suggest an item might be the airfare one. Deliberately broad: this
# narrows what a human reads, it does not decide anything.
TRANSPORT_HINTS = (
    "air", "fare", "flight", "travel", "transport", "aviation",
    "passenger", "ticket", "journey", "conveyance",
)


def _load_tls():
    """Load collector/tls.py by path, without importing the collector package."""
    path = _REPO / "packages" / "collector" / "tls.py"
    spec = importlib.util.spec_from_file_location("apix_tls_standalone", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_tls = _load_tls()


def get(url: str) -> Any:
    """One verified GET on the LEGACY rung. Certificate checking stays on."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    context = _tls.build_ssl_context(_tls.TlsMode.LEGACY)
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def walk_for_items(node: Any, found: list[dict[str, Any]]) -> None:
    """Find item-shaped dicts anywhere in the response.

    The endpoint returns filter options for several dimensions at once and the
    exact nesting is not documented, so this walks the whole structure rather
    than assuming a path that might change.
    """
    if isinstance(node, dict):
        keys = {k.lower() for k in node}
        if any("item" in k for k in keys) and any(
            k.endswith(("_name", "_code", "name", "code")) for k in keys
        ):
            found.append(node)
        for value in node.values():
            walk_for_items(value, found)
    elif isinstance(node, list):
        for entry in node:
            walk_for_items(entry, found)


def main() -> int:
    started = datetime.now(UTC)
    print(f"APIx O-2 - CPI 2024 item lookup - {started.isoformat()}\n")

    payloads: dict[str, Any] = {}
    for label, url in (
        (
            "items",
            f"{BASE}/api/cpi/getCpiFilterByLevelAndBaseYear"
            "?base_year=2024&level=Item&series_code=Current",
        ),
        (
            "groups",
            f"{BASE}/api/cpi/getCpiFilterByLevelAndBaseYear"
            "?base_year=2024&level=Group&series_code=Current",
        ),
    ):
        print(f"[GET] {label}")
        try:
            payloads[label] = get(url)
            print("    -> OK")
        except urllib.error.HTTPError as exc:
            print(f"    -> HTTP {exc.code}")
            payloads[label] = {"error": f"HTTP {exc.code}"}
        except (urllib.error.URLError, ssl.SSLError, TimeoutError) as exc:
            print(f"    -> FAILED {exc!r}")
            payloads[label] = {"error": repr(exc)}

    items: list[dict[str, Any]] = []
    walk_for_items(payloads.get("items"), items)
    print(f"\nItem-shaped records found: {len(items)}")

    def text_of(record: dict[str, Any]) -> str:
        return " ".join(str(v) for v in record.values()).lower()

    candidates = [r for r in items if any(hint in text_of(r) for hint in TRANSPORT_HINTS)]

    print(f"Transport-related candidates: {len(candidates)}\n")
    for record in candidates:
        print(f"  {json.dumps(record, ensure_ascii=False)}")

    if not candidates:
        print("  (none matched - read the full dump in the evidence file)")

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        "\n".join(
            [
                "# O-2 evidence - CPI 2024 item code for air fare",
                "",
                f"Run at: {started.isoformat()}",
                "Source: `api.mospi.gov.in`, LEGACY TLS rung, unauthenticated (see O-1).",
                "",
                "## Status",
                "",
                "**Do not record an item code from this file until a human has read the",
                "candidate list and confirmed which entry is air fare.** A plausible but",
                "wrong code would put an unquestioned number on the Methodology page.",
                "",
                f"Item-shaped records returned: {len(items)}",
                f"Transport-related candidates: {len(candidates)}",
                "",
                "## Candidates",
                "",
                "```json",
                json.dumps(candidates, indent=2, ensure_ascii=False),
                "```",
                "",
                "## Full item list",
                "",
                "```json",
                json.dumps(items, indent=2, ensure_ascii=False),
                "```",
                "",
                "## Raw responses",
                "",
                "```json",
                json.dumps(payloads, indent=2, ensure_ascii=False)[:60000],
                "```",
                "",
                "## Still needed",
                "",
                "The *weight* is not in this endpoint. Once the item code is confirmed,",
                "cross-check the weight against Annexure 5.3 of the MoSPI Expert Group",
                "Report before it enters the repository - two independent sources must",
                "agree, per the Phase 1.5 verification rule.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"\nEvidence written to {EVIDENCE.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
