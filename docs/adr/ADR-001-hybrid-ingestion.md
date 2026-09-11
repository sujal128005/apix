# ADR-001 — Hybrid ingestion, with the source mix as configuration

**Status: Accepted (Phase 2). Vindicated and amended (Phase 18, O-3 closure).**

## Context

Open item O-3 — whether Amadeus carried Indian low-cost-carrier content — was
unresolved when the ingestion layer was designed. An API-first architecture that
turned out to have thin coverage would be unusable; a crawler-first architecture
that ignored an available licensed feed would be needlessly non-compliant.

## Decision

Hybrid. One `SourceAdapter` interface over heterogeneous transports (licensed
API, regulatory document, permitted crawl, official statistics). Which sources
actually feed the index is **runtime configuration plus compliance-gate
outcome**, not a structural property.

## Amendment — 11 September 2026

O-3 resolved, and not as any of the three branches anticipated. **Amadeus
decommissioned its Self-Service portal entirely on 17 July 2026**; existing keys
were deactivated and no self-signup path remains. Tier 1 is unavailable to this
project. See `docs/evidence/O3-amadeus-decommissioned.md`.

The architecture required no change. That is the whole argument for this ADR,
tested against an outcome it did not predict: a source disappearing outright is a
harsher case than thin coverage, and it still amounted to leaving one adapter
disabled.

**Tier 2 — airline published tariff sheets under Rule 135(2) and DGCA Circular
02/2010 — is now the primary path**, and open item O-4 (locating each carrier's
tariff-sheet URL) becomes the critical path.

## Consequences

- The Amadeus adapter stays written, tested and disabled. Enabling it later is a
  config change.
- APIx has no live transacted-price source until O-4 resolves.
- Tariff sheets supply fare *bands*, not transacted prices, and cannot substitute
  for observed quotes. `TariffSheetAdapter` enforces this with
  `is_transacted_price: False` on every record.

## Reversal cost

Low. Collapsing to a single transport later is deletion, not redesign.
