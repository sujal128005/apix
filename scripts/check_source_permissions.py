#!/usr/bin/env python
"""Ask every source, for real, whether we may collect from it.

This project has been asserting since Phase 1 that OTA flight search is
disallowed and airline sites are "restricted by default". One of those claims
was checked. The rest were assumptions that hardened into documentation, and a
spot check found SpiceJet's robots.txt is in fact largely permissive - only
`/cgi-bin/`, `/api/v1`, `/public/` and `/externalBooking` are disallowed for
`User-agent: *`.

So this fetches each source's robots.txt and evaluates the exact paths an
adapter would request, using the same protego parser and the same user agent the
compliance gate uses. No assumptions, no cached answers.

**It collects no fares.** It requests one file per domain - `/robots.txt` - which
is the file every crawler is expected to read first. That is the lightest
possible question to ask, and asking it is not collection.

    .venv/Scripts/python scripts/check_source_permissions.py

Output goes to docs/evidence/O8-source-permissions.md. Commit it: a dated record
of what each site permitted, and what it said, is the evidence a compliance
review will want.

**robots.txt is not a licence.** A site that does not disallow a path has not
granted permission to collect from it commercially or at volume - terms of
service govern that, and for an official statistic affirmative permission is the
bar, not the absence of a prohibition. This script answers the narrow technical
question and nothing more.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compliance.config import ComplianceConfig
from compliance.robots import RobotsCache, RobotsOutcome

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "O8-source-permissions.md"


@dataclass(frozen=True, slots=True)
class SourceCheck:
    """A source, and the path an adapter would actually request."""

    code: str
    name: str
    tier: int
    base_url: str
    paths: tuple[str, ...]


# **Paths must be real.** The first version of this script tested invented paths
# such as "/booking/search", and reported Air India Express as permitting fare
# collection - when its robots.txt disallows "/flight-availability" by name. The
# invented path was "allowed" only because it does not exist.
#
# Where a real path is not yet known, it is marked UNKNOWN rather than guessed.
# A confident answer about a path nobody requests is worse than no answer.
SOURCES: tuple[SourceCheck, ...] = (
    # Confirmed from each site's own robots.txt on 13 September 2026: a path a
    # site names in a Disallow is a path that site has, and is the one that
    # matters. Paths still unconfirmed are listed as UNKNOWN.
    SourceCheck("indigo_web", "IndiGo", 3, "https://www.goindigo.in", ("/",)),
    SourceCheck("airindia_web", "Air India", 3, "https://www.airindia.com", ("/",)),
    SourceCheck(
        "aix_web", "Air India Express", 3, "https://www.airindiaexpress.com",
        # Named in their own robots.txt, so this is certainly a real path.
        ("/", "/flight-availability"),
    ),
    SourceCheck("akasa_web", "Akasa Air", 3, "https://www.akasaair.com", ("/",)),
    SourceCheck(
        "spicejet_web", "SpiceJet", 3, "https://www.spicejet.com",
        # All three named in their robots.txt, as malformed full-URL rules.
        ("/", "/api/v1", "/public/", "/externalBooking"),
    ),
    SourceCheck("makemytrip", "MakeMyTrip", 4, "https://www.makemytrip.com",
                ("/", "/air/search")),
    SourceCheck(
        "goibibo", "Goibibo", 4, "https://www.goibibo.com",
        # /flights/*?mode=* is disallowed; whether the fare query uses ?mode= is
        # the question a real adapter answers.
        ("/", "/air/search", "/flights/", "/flights/?mode=search"),
    ),
    SourceCheck("yatra", "Yatra", 4, "https://www.yatra.com", ("/",)),
    SourceCheck("easemytrip", "EaseMyTrip", 4, "https://www.easemytrip.com", ("/",)),
    SourceCheck("cleartrip", "Cleartrip", 4, "https://www.cleartrip.com", ("/",)),
    SourceCheck("ixigo", "Ixigo", 4, "https://www.ixigo.com",
                ("/", "/search/result/flight")),
)


def main() -> int:
    started = datetime.now(UTC)
    config = ComplianceConfig.from_env()

    if not config.has_contact:
        print("APIX_CONTACT_URL is not set.")
        print("This script identifies itself when fetching robots.txt, as any")
        print("well-behaved crawler should. Set a contact address and re-run.")
        return 1

    print(f"Source permission check - {started.isoformat()}")
    print(f"User-Agent: {config.user_agent}\n")

    cache = RobotsCache(config, write_snapshots=True)
    results: list[dict[str, object]] = []

    for source in SOURCES:
        print(f"[tier {source.tier}] {source.name}")
        document = cache.get(source.code, source.base_url, now=started)

        verdicts: list[dict[str, object]] = []
        for path in source.paths:
            allowed, rule = document.allows(path, config.user_agent)
            verdicts.append({"path": path, "allowed": allowed, "rule": rule})
            mark = "allowed" if allowed else "BLOCKED"
            print(f"    {path:<34} {mark}")

        delay = document.crawl_delay(config.user_agent)
        effective = config.effective_crawl_delay(delay)
        print(f"    robots.txt: {document.outcome}"
              f"{'' if delay is None else f', declared crawl-delay {delay}s'}"
              f", we would use {effective}s\n")

        results.append({
            "code": source.code,
            "name": source.name,
            "tier": source.tier,
            "base_url": source.base_url,
            "outcome": document.outcome,
            "http_status": document.http_status,
            "sha256": document.sha256,
            "snapshot": document.snapshot_path,
            "declared_crawl_delay": delay,
            "effective_crawl_delay": effective,  # already a float: seconds, not money
            "verdicts": verdicts,
            "body": document.body,
        })

    # Eleven independent sites refusing us identically is far more likely to be
    # one network refusing us eleven times. Saying so matters: a reader who takes
    # a blocked proxy for a compliance finding draws exactly the wrong conclusion
    # and records it as evidence.
    unreachable = [
        r for r in results
        if r["outcome"] in (RobotsOutcome.FORBIDDEN, RobotsOutcome.UNAVAILABLE)
    ]
    network_suspect = len(unreachable) == len(results)

    if network_suspect:
        print("!! Every source returned the same failure.")
        print("   That is unlikely to be eleven sites independently refusing us, and")
        print("   much more likely to be this machine unable to reach them - a proxy,")
        print("   a firewall, or no outbound access. The gate failed closed, which is")
        print("   correct, but these are NOT compliance findings.")
        print("   Re-run from a machine with direct internet access.\n")

    _write_evidence(started, config.user_agent, results, network_suspect=network_suspect)

    permitted = [] if network_suspect else [
        r for r in results
        if any(v["allowed"] for v in r["verdicts"] if v["path"] != "/")  # type: ignore[index,union-attr]
    ]
    if not network_suspect:
        print(f"Sources permitting a search path: {len(permitted)} of {len(results)}")
        for r in permitted:
            print(f"  - {r['name']}")
    print(
        "\nrobots.txt permission is necessary, not sufficient. Terms of service "
        "govern\nwhether collection is allowed, and for an official statistic the "
        "bar is\naffirmative permission rather than the absence of a prohibition."
    )
    print(f"\nEvidence written to {EVIDENCE.relative_to(EVIDENCE.parents[2])}")
    return 0


def _write_evidence(
    started: datetime,
    user_agent: str,
    results: list[dict[str, object]],
    *,
    network_suspect: bool = False,
) -> None:
    lines = [
        "# O-8 evidence - what each source's robots.txt actually permits",
        "",
        f"Checked: {started.isoformat()}",
        f"User-Agent: `{user_agent}`",
        "",
        "Produced by `scripts/check_source_permissions.py`, which fetches each",
        "domain's robots.txt and evaluates the exact paths an adapter would request,",
        "using the same protego parser and user agent as the compliance gate.",
        "",
        "**This replaces an assumption.** Phase 1 checked MakeMyTrip and inferred the",
        "rest. That inference became documentation and was repeated for weeks. A spot",
        "check found SpiceJet's robots.txt largely permissive, so every source is now",
        "checked rather than assumed.",
        "",
        "**A permitted path is not a known path.** An earlier run of this script",
        "tested invented paths and reported Air India Express as permitting fare",
        "collection, when its robots.txt disallows `/flight-availability` by name.",
        "The invented path was permitted only because it does not exist. Paths below",
        "are taken from each site's own Disallow rules where possible; the rest are",
        "limited to `/` until a real path is confirmed.",
        "",
        "**robots.txt is not a licence.** A site that does not disallow a path has not",
        "granted permission to collect from it at volume. Terms of service govern that,",
        "and for an official statistic the bar is affirmative permission, not the",
        "absence of a prohibition. Treat every `allowed` below as *technically not",
        "excluded*, pending legal review.",
        "",
    ]

    if network_suspect:
        lines += [
            "> **These results are not usable.** Every source returned the same",
            "> failure, which is far more likely to be one machine unable to reach",
            "> eleven sites than eleven sites independently refusing one machine.",
            "> The compliance gate failed closed, which is correct behaviour, but a",
            "> blocked proxy is not a compliance finding. Re-run from a machine with",
            "> direct internet access before citing anything below.",
            "",
        ]

    lines += [
        "## Summary",
        "",
        "| Source | Tier | robots.txt | Search path permitted | Crawl delay we would use |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        verdicts = r["verdicts"]  # type: ignore[index]
        search = [v for v in verdicts if v["path"] != "/"]  # type: ignore[index,union-attr]
        permitted = any(v["allowed"] for v in search)  # type: ignore[index]
        lines.append(
            f"| {r['name']} | {r['tier']} | `{r['outcome']}` | "
            f"{'yes' if permitted else '**no**'} | {r['effective_crawl_delay']}s |"
        )

    lines += ["", "## Per-source detail", ""]
    for r in results:
        lines += [
            f"### {r['name']} (`{r['code']}`, tier {r['tier']})",
            "",
            f"- `{r['base_url']}/robots.txt` &rarr; HTTP {r['http_status']}, "
            f"outcome `{r['outcome']}`",
            f"- sha256: `{r['sha256']}`",
            f"- snapshot: `{r['snapshot']}`",
            f"- declared crawl-delay: {r['declared_crawl_delay']}",
            "",
            "| Path | Verdict | Rule applied |",
            "|---|---|---|",
        ]
        for v in r["verdicts"]:  # type: ignore[index,union-attr]
            lines.append(
                f"| `{v['path']}` | {'allowed' if v['allowed'] else '**blocked**'} "  # type: ignore[index]
                f"| {v['rule']} |"  # type: ignore[index]
            )
        body = r["body"]
        if body:
            lines += ["", "<details><summary>robots.txt as fetched</summary>", "",
                      "```", str(body)[:4000], "```", "", "</details>"]
        lines.append("")

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
