# Deferred requirements

Work identified during a phase but deliberately not built in it. Each entry
says which phase owns it and why it was not solved where it was found.

---

## D-1 — Fuzzy near-duplicate detection for quotes with a NULL `flight_no`

**Owner: Phase 7 (cleaning layer). Raised in Phase 3 review.**

`uq_normalised_quote_dedup` covers
`(source_id, carrier, flight_no, departure_ts, fare_brand, collected_date)` and
uses PostgreSQL's default `NULLS DISTINCT`. That is deliberate and stays:

- imputed rows legitimately carry a NULL `flight_no`, and several may coexist in
  one stratum;
- two partial extractions are not *provably* the same offer, so collapsing them
  on a unique key would destroy distinct observations.

The gap it leaves is real, though. Near-duplicate rows with a NULL `flight_no`
inflate the stratum count `n` and bias the Jevons geometric mean, because the
same offer effectively votes twice.

A database constraint cannot solve this cleanly — the decision is probabilistic,
and a unique index is not. It belongs in the cleaning layer.

**Requirement.** Phase 7 must detect near-duplicates on
`(source, carrier, departure_ts, fare_brand, total_fare, collected_date)` and
resolve them before the stratum is formed. Every collapse must be recorded as a
`cleaning_event` so the decision is auditable and reversible in analysis, in
keeping with the rule that nothing is silently discarded.

---

## D-2 — Nullability of six columns left to implementer judgement

**Owner: architect. Raised in Phase 3 review.
Status: RESOLVED — ruled: approved as reasoned, review round 2.**

Kept as a record rather than deleted: the reasoning below is the kind of thing
the public Methodology page will need to state later.

Build brief §5 marks `NOT NULL` and `NULL` explicitly on most columns but is
silent on six. All six were implemented nullable, and all six were approved:

| Column | Type | Why it was left nullable |
|---|---|---|
| `source.base_url` | `TEXT` | §7's seed table supplies no URLs, and URLs are open item O-4. `NOT NULL` would have forced 18 invented values. |
| `source_review.robots_decision` | `TEXT` | A review may record a ToS finding with no robots.txt rule to cite. |
| `source_review.tos_note` | `TEXT` | A review may record a robots.txt rule with no ToS note. |
| `raw_response.http_status` | `INT` | A transport-level failure produces no HTTP status at all. |
| `normalised_quote.quality_score` | `NUMERIC(4,3)` | Assigned by the Phase 8 cleaning pipeline; a freshly normalised quote has not been scored. |
| `system_event.payload` | `JSONB` | Many events carry no structured detail beyond level, component and message, and no default is specified. |

All other unmarked columns were made `NOT NULL` by structural necessity:
foreign keys, natural keys, enum/status columns, money columns and counters.

Notes from the ruling worth keeping:

- `source_review.robots_decision` / `.tos_note` — a ToS finding with no robots
  rule to cite is a real case, and forcing an empty string would be worse.
- `raw_response.http_status` — a DNS or TLS failure genuinely has no status, and
  that distinction matters for source-health diagnostics later.
- `normalised_quote.quality_score` — unscored and zero-scored must be
  distinguishable.
