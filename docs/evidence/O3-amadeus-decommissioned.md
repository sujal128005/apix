# O-3 — CLOSED. Amadeus Self-Service no longer exists.

**Resolved 11 September 2026.**

## The finding

Amadeus **decommissioned its Self-Service developer portal on 17 July 2026**.

- February 2026 — Amadeus notified developers the portal would close.
- Spring 2026 — new self-service registration paused; no new keys issued.
- **17 July 2026** — portal decommissioned, existing API keys deactivated.
- The `amadeus4dev` GitHub organisation was archived the same day.

`developers.amadeus.com` now serves only the Enterprise API Portal, which
requires a commercial relationship and a sales conversation. There is no
self-signup path and no free tier.

Sources: Amadeus' own site banner; PhocusWire, February 2026; the archived
`amadeus4dev` GitHub organisation.

## What this means for APIx

**Tier 1 — licensed API — is not available to this project.** ADR-001's
preferred ingestion path does not exist for a team without an Amadeus commercial
account.

**No architectural change is required**, which is the point worth noting. ADR-001
deliberately chose a hybrid ingestion layer so that *which* sources feed the
index would be a configuration outcome rather than a structural one. The decision
rule written into that ADR anticipated this branch: with 0–1 carriers available,
Tier 2 and Tier 3 carry the index.

The Amadeus adapter (`packages/collector/adapters/amadeus.py`) remains written,
fixture-tested and registered. It stays disabled. If the project later obtains
Enterprise access, enabling it is a configuration change.

## Consequence: Tier 2 is now the primary path

Airline **published route-wise tariff sheets**, under:

- **Rule 135(2), Aircraft Rules 1937** — established tariff shall be published on
  the airline's website.
- **DGCA Air Transport Circular 02 of 2010** — scheduled domestic airlines must
  display route-wise tariff sheets across their network in various fare
  categories, and furnish the same to DGCA on the first day of each month.

Confirmed to exist in practice: IndiGo has stated it publishes a sector-wise
tariff sheet on `goindigo.in`, and dated IndiGo tariff sheet documents circulate
publicly. The Federation of Indian Airlines agreed that member websites would
display tariff sheets showing the range of fares on all routes.

**Open item O-4 — locating each carrier's current tariff-sheet URL — is now the
critical path**, not a nice-to-have.

## The limitation this inherits

A declared tariff is a fare **band**, not a transacted price. It cannot feed the
index as though it were an observed fare, and `TariffSheetAdapter` marks every
record `is_transacted_price: False` so the pipeline can enforce that rather than
relying on anyone remembering.

Tariff sheets give APIx: validation that observed fares fall within declared
bands, carrier-level context, and anomaly detection. They do not give it a
transacted-price series.

## Status of live collection

Without Tier 1, and until O-4 resolves, APIx has **no live transacted-price
source**. All observations remain `SIMULATED_DEMO`, the database continues to
refuse a published headline index, and the dashboard continues to say so.

That is the correct behaviour. It is also, now, a documented external constraint
rather than an incomplete implementation.
