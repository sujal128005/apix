# ADR-019 — The governing compliance document depends on the source type

**Status:** Accepted (Phase 4C)
**Supersedes nothing. Constrains ADR-005 and ADR-006.**

---

## Context

Phase 4A built a gate in which `BLOCKED_ROBOTS` is terminal, with no override anywhere in the codebase. That is right for a crawler.

Phase 4C then hit the consequence. MoSPI publishes an **official open API** at `api.mospi.gov.in`, an **official Python client** (`nso-india/mospi-esankhyiki`, MIT-licensed), and an **official MCP server**. It is the sanctioned way to obtain CPI data, and Phase 1.5 already established that we must consume it rather than scrape the eSankhyiki SPA.

During Phase 1 research, a compliant automated fetcher was refused by `api.mospi.gov.in`'s robots policy.

So the gate as built would refuse to call the official API of the ministry that set the problem, using that ministry's own published client, on the grounds that its robots.txt discourages crawlers. That is not compliance. It is a category error wearing compliance as a costume.

## Decision

**The governing compliance document is determined by the source tier, and is recorded on every decision row.**

| Tier | Source kind | Governing document | Checked by |
|---|---|---|---|
| 1 | Licensed API (Amadeus) | API terms of service | Human review, recorded in `source_review` |
| 2 | Regulatory disclosure (tariff sheets) | robots.txt + Rule 135(2) publication duty | Gate, at runtime |
| 3 | Permitted crawl (airline pages) | robots.txt | Gate, at runtime |
| 4 | Restricted (OTA search) | robots.txt | Gate, at runtime — and these stay blocked |
| 5 | Official statistics API (MoSPI) | API terms + published client | Human review, recorded in `source_review` |

For tiers 1 and 5, robots.txt is still **fetched and recorded** for transparency, but a disallow does not block the request. For tiers 2, 3 and 4, robots.txt governs absolutely and `BLOCKED_ROBOTS` remains terminal.

Every `compliance_decision` records which basis was applied, so the audit trail answers "why was this allowed?" rather than merely "it was allowed".

## Why this is not the override flag ADR-006 forbids

Four properties distinguish them, and all four must hold:

1. **It is not a flag.** There is no argument, environment variable or config key that changes a source's tier at call time. The tier is a column on a row, set by a migration or a seed, visible in the database and on the Sources page.
2. **It requires a human.** Tiers 1 and 5 still need an `APPROVED` `source_review`, and that review must cite the API terms in `tos_note`. A source with no review is refused regardless of tier.
3. **It cannot reach a crawl target.** The tier of every web-scraped source is 2, 3 or 4, and for those robots.txt is absolute. There is no path by which an OTA becomes tier 5.
4. **It is recorded, not assumed.** The basis appears on every decision row and in the UI.

An override flag says "ignore the rule this time". This says "apply the rule that actually governs this kind of access". The distinction is real, but it is exactly the kind of distinction that gets abused, which is why properties 1–4 are enforced by test rather than asserted here.

## Alternatives considered

**Give MoSPI tier 3 and hope robots permits it.** Dishonest, and fragile — it would break the moment their robots.txt changed.

**Add an `ignore_robots` flag for API sources.** This is the thing ADR-006 exists to prevent. Once such a flag exists, someone uses it on an OTA at 2am.

**Do not use the MoSPI API at all.** Forfeits the only official benchmark, and therefore Tier 2 of the backtest design (ADR-015). Unacceptable.

**Ask MoSPI for written clarification.** Correct, and worth doing before any real deployment. It does not unblock a hackathon prototype, so it is recorded as a limitation rather than a blocker.

## Consequences

- `ComplianceDecision.matched_rule` now states the basis, e.g. `api terms (tier 5): robots.txt is not the governing document for API access`.
- The Sources page must show the basis per source, not just a green or red badge.
- The Methodology and Compliance pages must state this openly. It is the kind of thing that looks like a loophole if a judge discovers it themselves, and like careful reasoning if we raise it first.

## Risks

**The distinction is abused later.** Mitigated by the tier-integrity test: no source with `transport = browser` may be tier 1 or 5, and every tier-1/5 source must have a review whose `tos_note` is non-empty.

**We are wrong about the law.** Possible. robots.txt is a technical directive, not a licence, and terms of service are a legal question we are not qualified to settle. Stated as a limitation in `docs/scraping-compliance.md`, and the honest position — that API consumption under a published contract is not crawling — is written down where it can be challenged.

## Reversal cost

Low. Changing a tier is a data change; if the tier-based rule is rejected, MoSPI access is disabled and the backtest falls back to Tier 1 and Tier 3 evidence only.
