#!/usr/bin/env python
"""Watch a human search for a flight, and record what the site actually does.

Building an adapter needs three things: the URL a search lands on, the shape of
the response carrying fares, and a way to locate fares in the rendered page.
All three are discoverable by reading a network trace, which is fiddly, or by
searching once while something watches - which is this.

It opens a real browser. **You drive it.** Navigate, fill in the search form,
press search, wait for results. The script records:

  - every XHR or fetch response that looks like it carries fares
  - the URL the search landed on
  - candidate CSS selectors for price-shaped text in the rendered page
  - a screenshot and the final HTML, for reference

Then it writes a report an adapter can be built from.

**This is browsing, not collection.** One human-driven session at human speed,
in a real browser, on pages the site serves to anyone. Nothing is scheduled,
nothing is repeated, and no fare is stored as an observation. The compliance
gate governs *collection*; this is the reconnaissance that decides whether
collection is worth proposing at all.

    .venv/Scripts/python -m playwright install chromium
    .venv/Scripts/python scripts/discover_source.py --url https://www.akasaair.com

Close the browser window when the results are on screen. The report is written
to docs/evidence/.
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages"))
sys.path.insert(0, str(REPO))

from schemas.environment import require_not_production  # noqa: E402

require_not_production("Source discovery")

OUT = REPO / "docs" / "evidence"

#: Words that suggest a response carries fares rather than, say, analytics.
FARE_HINTS = (
    "fare", "price", "amount", "total", "journey", "flight", "segment",
    "itinerary", "availability", "trip",
)

#: Rupee amounts as they appear in rendered pages.
PRICE_PATTERN = re.compile(r"(?:₹|Rs\.?|INR)\s?[\d,]{3,}")


def looks_like_fares(url: str, body: str) -> bool:
    """Whether a response plausibly carries fare data.

    Deliberately loose. A false positive costs a line in a report; a false
    negative means the endpoint that matters never appears.
    """
    if len(body) < 200:
        return False
    haystack = (url + body[:4000]).lower()
    hits = sum(1 for hint in FARE_HINTS if hint in haystack)
    return hits >= 3 and bool(PRICE_PATTERN.search(body[:20000]) or '"amount"' in haystack)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="the site to open")
    parser.add_argument("--name", default=None, help="short name for the report file")
    parser.add_argument(
        "--timeout", type=int, default=600, help="seconds before giving up (default 600)"
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Run:")
        print("  .venv/Scripts/pip install playwright")
        print("  .venv/Scripts/python -m playwright install chromium")
        return 1

    name = args.name or re.sub(r"[^a-z0-9]+", "_", args.url.lower()).strip("_")[:40]
    started = datetime.now(UTC)
    captured: list[dict[str, Any]] = []
    navigations: list[str] = []

    print(f"Opening {args.url}")
    print()
    print("  Search for a flight in the window that opens: DEL to BOM, about a week")
    print("  out, one adult, one way. Wait for the fares to appear.")
    print("  Then close the browser window.")
    print()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        # A normal browser identity. Pretending to be something else would be
        # the beginning of evasion, and this project does not do that - the
        # collector identifies itself honestly and so does this.
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        def on_response(response: Any) -> None:
            try:
                if response.request.resource_type not in ("xhr", "fetch"):
                    return
                body = response.text()
            except Exception:
                return
            if not looks_like_fares(response.url, body):
                return
            captured.append({
                "url": response.url,
                "method": response.request.method,
                "status": response.status,
                "content_type": response.headers.get("content-type", ""),
                "post_data": response.request.post_data,
                "body_head": body[:60000],
                "body_length": len(body),
            })
            print(f"  captured  {response.request.method} {response.url[:96]}")

        page.on("response", on_response)
        page.on("framenavigated", lambda frame: (
            navigations.append(frame.url) if frame == page.main_frame else None
        ))

        page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)

        # Either ending is fine: the user closes the window once fares are up, or
        # the timeout expires.
        with contextlib.suppress(Exception):
            page.wait_for_event("close", timeout=args.timeout * 1000)

        # Snapshot whatever is on screen when the session ends.
        final_url, html, prices = "", "", []
        try:
            final_url = page.url
            html = page.content()
            OUT.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(OUT / f"discovery-{name}.png"), full_page=True)
            prices = _price_selectors(page)
        except Exception:
            pass

        browser.close()

    _write_report(name, args.url, started, captured, navigations, final_url, html, prices)

    print()
    print(f"  {len(captured)} candidate fare response(s)")
    print(f"  {len(prices)} candidate price selector(s)")
    print(f"\nReport: docs/evidence/discovery-{name}.md")
    if not captured and not prices:
        print("\nNothing captured. Either the search did not complete, or fares arrive")
        print("in a form this script does not recognise. Both are worth knowing.")
    return 0


def _price_selectors(page: Any) -> list[dict[str, Any]]:
    """Find elements whose text looks like a rupee amount.

    Returns the element's tag, classes and text, so an adapter author can see
    what to select on without guessing from a screenshot.
    """
    script = """
    () => {
      const out = [];
      const re = /(?:₹|Rs\\.?|INR)\\s?[\\d,]{3,}/;
      for (const el of document.querySelectorAll('*')) {
        if (el.children.length) continue;
        const text = (el.textContent || '').trim();
        if (!text || text.length > 40 || !re.test(text)) continue;
        out.push({
          tag: el.tagName.toLowerCase(),
          className: (el.className || '').toString().slice(0, 120),
          id: el.id || '',
          text: text,
          path: (() => {
            const parts = [];
            let node = el;
            while (node && node.nodeType === 1 && parts.length < 5) {
              let part = node.tagName.toLowerCase();
              if (node.id) { parts.unshift('#' + node.id); break; }
              const cls = (node.className || '').toString().trim().split(/\\s+/)[0];
              if (cls) part += '.' + cls;
              parts.unshift(part);
              node = node.parentElement;
            }
            return parts.join(' > ');
          })(),
        });
        if (out.length >= 40) break;
      }
      return out;
    }
    """
    try:
        return list(page.evaluate(script))
    except Exception:
        return []


def _write_report(
    name: str,
    url: str,
    started: datetime,
    captured: list[dict[str, Any]],
    navigations: list[str],
    final_url: str,
    html: str,
    prices: list[dict[str, Any]],
) -> None:
    lines = [
        f"# Source discovery — {name}",
        "",
        f"Site: {url}",
        f"Session: {started.isoformat()}",
        "",
        "Recorded by `scripts/discover_source.py` during one human-driven browsing",
        "session. **No fare here is an observation** — nothing was stored, scheduled",
        "or repeated. This is the reconnaissance that decides whether collection is",
        "worth proposing, not collection.",
        "",
        "## Where the search landed",
        "",
        f"`{final_url or 'not captured'}`",
        "",
    ]

    if navigations:
        lines += ["<details><summary>Navigation history</summary>", "", "```"]
        lines += list(dict.fromkeys(navigations))[:20]
        lines += ["```", "", "</details>", ""]

    lines += [
        f"## Candidate fare responses ({len(captured)})",
        "",
        "Responses that plausibly carry fares. An adapter would request one of",
        "these directly rather than driving a browser, if the site permits it.",
        "",
    ]
    if not captured:
        lines += [
            "None captured. Either the search did not complete, or fares arrive in a",
            "form this script does not recognise — server-rendered HTML, a WebSocket,",
            "or an encoding it did not detect. Worth checking manually before",
            "concluding the site cannot be read.",
            "",
        ]
    for i, response in enumerate(captured, start=1):
        lines += [
            f"### {i}. `{response['method']} {response['url'][:140]}`",
            "",
            f"- status {response['status']}, {response['body_length']:,} bytes",
            f"- content-type: `{response['content_type']}`",
            "",
        ]
        if response["post_data"]:
            lines += ["Request payload:", "", "```json",
                      str(response["post_data"])[:1500], "```", ""]
        lines += ["Response head:", "", "```json", response["body_head"], "```", ""]

    lines += [
        f"## Candidate price selectors ({len(prices)})",
        "",
        "Leaf elements whose text reads as a rupee amount. Useful if fares must be",
        "read from the rendered page rather than an endpoint.",
        "",
    ]
    if prices:
        lines += ["| Text | Tag | Class | Path |", "|---|---|---|---|"]
        for p in prices[:25]:
            lines.append(
                f"| `{p['text']}` | `{p['tag']}` | `{p['className'][:40]}` | "
                f"`{p['path'][:60]}` |"
            )
        lines.append("")

    lines += [
        "## Before building an adapter",
        "",
        "1. Run `scripts/check_source_permissions.py` against the **exact path**",
        "   above. A path permitted in general is not the path this search used.",
        "2. Read the site's terms of service. robots.txt governs crawling; terms",
        "   govern automated access, and they are different questions.",
        "3. For an official statistic, neither is sufficient — the bar is",
        "   affirmative permission. See `docs/DATA-REQUEST.md`.",
        "",
    ]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"discovery-{name}.md").write_text("\n".join(lines), encoding="utf-8")
    if html:
        (OUT / f"discovery-{name}.html").write_text(html[:2_000_000], encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
