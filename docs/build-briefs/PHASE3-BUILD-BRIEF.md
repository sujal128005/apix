# PHASE 3 BUILD BRIEF — Data Layer & Contracts
## Hand this entire file to the builder. It is self-contained.

---

# 0. YOUR ROLE

You are the **implementation engineer** on SIH 2026 Problem Statement 26056 — a Real-time Airfare Price Index (APIx) for India, built to augment MoSPI's Consumer Price Index.

Architecture, methodology and technology choices are **already frozen** by the chief architect. They are given below. Your job is to implement them exactly.

## Hard rules

1. **Do not make architectural decisions.** Stack, schema, constraints and naming are specified. If something is genuinely ambiguous or you believe a spec is wrong, **stop and ask** — do not improvise and do not "improve" it silently.
2. **Do not invent data.** No route weights, no passenger figures, no CPI weights, no fare values presented as real. Seed data is specified explicitly below; anything not specified stays `NULL` or absent.
3. **Do not build ahead.** No scrapers, no index engine, no API, no UI in this phase. If you finish early, write more tests.
4. **Do not claim something works until a test proves it.** "Should work" is not a status.
5. **Report deviations loudly.** If you had to depart from this brief anywhere, list it in your final report under a heading `DEVIATIONS`. An unreported deviation is the single worst outcome of this phase.
6. **No `# TODO` left behind.** Either implement it or list it in `DEFERRED` in your report.

---

# 1. CONTEXT YOU NEED

APIx collects airfare quotes from compliant sources, cleans them, and computes a daily/weekly/monthly price index using **MoSPI's own published CPI 2024 formulae**. Every published number must be traceable back to an individual fare quote, and every index value must be bit-for-bit reproducible.

Three properties drive the entire schema. Understand them before writing DDL:

**Traceability.** A judge must be able to go: headline index → route contribution → lead-time stratum → accepted observations → one fare quote → its source, collection timestamp, provenance and every cleaning rule that touched it. The foreign-key chain must support that traversal in one query.

**Immutability.** Raw payloads, compliance decisions, cleaning events and index observations are **append-only**. Corrections create new rows under a new version. They are never edited. This is enforced at the database role level, not by convention.

**Provenance.** Every observation carries a non-null provenance label. Simulated demo data must be structurally incapable of reaching a headline index value.

The index is **chained** (each value depends on its predecessor), which is why `index_observation` stores `prev_index_value`.

---

# 2. STACK — FIXED, DO NOT SUBSTITUTE

| Concern | Choice |
|---|---|
| Language | Python 3.12 |
| DB | PostgreSQL 16 |
| ORM | SQLAlchemy 2.0 (typed, `Mapped[]` style) |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Tests | pytest + testcontainers (or a local PG 16 instance) |
| Money | `Decimal` in Python, `NUMERIC(12,2)` in PG. **Never float.** |
| IDs | UUIDv7 primary keys |
| Time | Store `TIMESTAMPTZ` in UTC. Render IST at the edge only. |
| Lint/format | ruff + mypy (strict on `packages/schemas`) |

---

# 3. REPOSITORY STRUCTURE TO CREATE

```
apix/
├── db/
│   ├── migrations/            # alembic versions
│   ├── alembic.ini
│   └── seeds/
│       ├── airports.py
│       ├── routes.py
│       ├── lead_time_buckets.py
│       ├── sources.py
│       └── methodology.py
├── packages/
│   └── schemas/               # SQLAlchemy models + Pydantic contracts
│       ├── models/            # one module per domain group
│       ├── contracts/         # Pydantic v2
│       └── enums.py
├── tests/
│   ├── unit/                  # contract + enum tests
│   ├── integration/           # constraint tests against real PG
│   └── fixtures/
│       ├── golden_day/
│       └── adversarial/
├── scripts/
│   └── init_db.py
├── docker-compose.yml         # postgres:16 only for this phase
├── .env.example               # committed, NO values
├── pyproject.toml
└── README.md
```

---

# 4. ENUMS — create as Postgres `CHECK` constraints and Python `StrEnum`

```python
Provenance      = LIVE_COLLECTED | LICENSED_API | OFFICIAL_STATISTIC | PUBLIC_HISTORICAL | SIMULATED_DEMO
SourceTier      = 1..5   # 1 licensed API, 2 regulatory disclosure, 3 permitted crawl, 4 restricted, 5 official stats
ReviewVerdict   = APPROVED | REQUIRES_LEGAL_REVIEW | REJECTED
ComplianceDecision = ALLOWED | BLOCKED_ROBOTS | BLOCKED_UNREVIEWED | SKIPPED_DISABLED | DEFERRED_RATE_LIMIT
JobStatus       = PENDING | RUNNING | SUCCESS | PARTIAL | FAILED
MissingReason   = NONE | SCRAPER_FAILURE | SOURCE_BLOCKED | NO_FLIGHTS | SOLD_OUT | PARSE_FAILURE | PARTIAL_COMPONENTS | CHAIN_GAP
FareComponent   = BASE | TAX | UDF | CONVENIENCE | OTHER
Confidence      = HIGH | MEDIUM | LOW
QualityStatus   = COMPLETE | PARTIAL | SUSPICIOUS | UNUSABLE
IndexLevel      = STRATUM | ROUTE | HEADLINE
ImputationCode  = N | Y            # mirrors MoSPI's own CPI 2024 per-record flag
EvidenceRung    = 1..4             # 1 city-pair volumes, 2 DGCA popular-routes list, 3 airport-throughput proxy, 4 equal
Mode            = LIVE | STAGED | OFFLINE_DEMO
```

`ImputationCode` deliberately mirrors MoSPI's field name. Do not rename it.

---

# 5. TABLES

All tables: `id UUID PK`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
**IMM** = immutable (append-only, UPDATE/DELETE revoked from app role).

### Reference

**`airport`** — `iata CHAR(3) UK NOT NULL`, `icao CHAR(4) NULL`, `name TEXT NOT NULL`, `city TEXT NOT NULL`, `state TEXT NOT NULL`, `tz TEXT NOT NULL DEFAULT 'Asia/Kolkata'`, `active BOOL NOT NULL DEFAULT true`.
`CHECK (iata ~ '^[A-Z]{3}$')`

**`route`** — `code TEXT UK NOT NULL` (format `DEL-BOM`), `origin_id FK airport`, `destination_id FK airport`, `directional BOOL NOT NULL DEFAULT true`, `active BOOL NOT NULL DEFAULT true`.
`CHECK (origin_id <> destination_id)`, `CHECK (code ~ '^[A-Z]{3}-[A-Z]{3}$')`
**Routes are DIRECTIONAL** (ADR-017). Also create view `route_undirected` grouping A-B with B-A on `least(origin,dest) || greatest(origin,dest)`.

**`lead_time_bucket`** — `code TEXT UK` , `days INT NOT NULL UK`, `lambda NUMERIC(8,6) NOT NULL`, `cpi_comparable BOOL NOT NULL DEFAULT false`.
`CHECK (days > 0)`

**`source`** — `code TEXT UK`, `name TEXT`, `tier INT NOT NULL`, `transport TEXT NOT NULL` (`api`|`document`|`browser`), `adapter_key TEXT NOT NULL`, `base_url TEXT`, `enabled BOOL NOT NULL DEFAULT false`.
`CHECK (tier BETWEEN 1 AND 5)`. **Default `enabled = false`** — sources are opt-in, never opt-out.

**`source_review`** — **IMM** — `source_id FK`, `reviewer TEXT NOT NULL`, `reviewed_at TIMESTAMPTZ NOT NULL`, `robots_decision TEXT`, `tos_note TEXT`, `verdict ReviewVerdict NOT NULL`.

### Versioning

**`methodology_version`** — **IMM** — `version TEXT UK` (semver), `effective_from DATE NOT NULL`, `params JSONB NOT NULL`, `changelog TEXT NOT NULL`.

**`weight_set_version`** — **IMM** — `version TEXT UK`, `effective_from DATE NOT NULL`, `source_note TEXT NOT NULL`.

**`route_weight`** — **IMM** — `route_id FK`, `weight NUMERIC(10,8) NOT NULL`, `evidence_rung INT NOT NULL`, `evidence_ref TEXT NOT NULL`, `evidence_retrieved_at TIMESTAMPTZ NOT NULL`, `weight_set_version_id FK`.
`CHECK (weight > 0 AND weight <= 1)`, `CHECK (evidence_rung BETWEEN 1 AND 4)`, `UK(route_id, weight_set_version_id)`
**Deferred constraint trigger:** for each `weight_set_version_id`, `SUM(weight)` must equal 1 within 1e-9 at commit time.

### Collection

**`collection_job`** — `started_at`, `finished_at NULL`, `status JobStatus`, `requests_total INT DEFAULT 0`, `requests_ok INT DEFAULT 0`, `requests_blocked INT DEFAULT 0`, `parse_failures INT DEFAULT 0`. Index `(started_at DESC)`.

**`collection_request`** — **IMM** — `job_id FK`, `source_id FK`, `route_id FK`, `bucket_id FK`, `travel_date DATE NOT NULL`, `collected_date DATE NOT NULL`, `query_hash TEXT UK NOT NULL`.
`query_hash = sha256(source|route|bucket|travel_date|collected_date)` — prevents duplicate searches.

**`compliance_decision`** — **IMM** — `source_id FK`, `request_id FK NULL`, `path TEXT NOT NULL`, `user_agent TEXT NOT NULL`, `robots_sha256 TEXT NULL`, `matched_rule TEXT NULL`, `decision ComplianceDecision NOT NULL`, `decided_at TIMESTAMPTZ NOT NULL`. Index `(source_id, decided_at DESC)`.

**`raw_response`** — **IMM** — `request_id FK`, `payload_ref TEXT NOT NULL`, `sha256 TEXT NOT NULL`, `http_status INT`, `fetched_at TIMESTAMPTZ NOT NULL`. `UK(request_id, sha256)`

**`raw_quote`** — **IMM** — `raw_response_id FK`, `ordinal INT NOT NULL`, `payload JSONB NOT NULL`. `UK(raw_response_id, ordinal)`

### Derived

**`normalised_quote`** — `raw_quote_id FK NULL` (null only for imputed rows), `route_id FK`, `bucket_id FK`, `source_id FK`, `carrier CHAR(2) NOT NULL`, `flight_no TEXT NULL`, `departure_ts TIMESTAMPTZ NULL`, `arrival_ts TIMESTAMPTZ NULL`, `lead_time_days INT NOT NULL`, `fare_brand TEXT NULL`, `total_fare NUMERIC(12,2) NOT NULL`, `currency CHAR(3) NOT NULL DEFAULT 'INR'`, `collected_at TIMESTAMPTZ NOT NULL`, `collected_date DATE NOT NULL`, `provenance Provenance NOT NULL`, `quality_status QualityStatus NOT NULL`, `quality_score NUMERIC(4,3)`, `imputation_code ImputationCode NOT NULL DEFAULT 'N'`, `missing_reason MissingReason NOT NULL DEFAULT 'NONE'`, `component_confidence Confidence NULL`.

- `CHECK (total_fare > 0)` ← non-negotiable
- `CHECK (currency = 'INR')` for this phase
- `UK(source_id, carrier, flight_no, departure_ts, fare_brand, collected_date)` ← dedup key
- `CHECK (imputation_code = 'Y' OR raw_quote_id IS NOT NULL)` ← only imputed rows may lack a raw quote
- Index `(route_id, bucket_id, collected_date)`

**`fare_component`** — `quote_id FK`, `kind FareComponent NOT NULL`, `amount NUMERIC(12,2) NOT NULL`, `confidence Confidence NOT NULL`. `UK(quote_id, kind)`, `CHECK (amount >= 0)`

**`cleaning_event`** — **IMM** — `quote_id FK`, `rule_id TEXT NOT NULL`, `action TEXT NOT NULL`, `threshold NUMERIC NULL`, `observed NUMERIC NULL`, `reason TEXT NOT NULL`. Index `(quote_id)`

### Index

**`index_observation`** — **IMM** — `obs_date DATE NOT NULL`, `level IndexLevel NOT NULL`, `ref_id UUID NULL` (route or stratum; null for HEADLINE), `bucket_id FK NULL`, `index_value NUMERIC(12,6) NOT NULL`, `prev_index_value NUMERIC(12,6) NULL`, `base_period_id UUID NULL`, `methodology_version_id FK`, `weight_set_version_id FK`, `input_quote_count INT NOT NULL`, `excluded_count INT NOT NULL DEFAULT 0`, `imputed_count INT NOT NULL DEFAULT 0`, `routes_in_basket INT NULL`, `input_hash TEXT NOT NULL`, `computed_at TIMESTAMPTZ NOT NULL`.

- `UK(obs_date, level, ref_id, bucket_id, methodology_version_id)`
- `CHECK (index_value > 0)`
- **Trigger:** reject INSERT at `level='HEADLINE'` if any contributing quote has `provenance = 'SIMULATED_DEMO'`. See §6.

**`index_contribution`** — **IMM** — `index_observation_id FK`, `route_id FK`, `contribution NUMERIC(12,6) NOT NULL`. `UK(index_observation_id, route_id)`

**`benchmark_observation`** — **IMM** — `bench_source TEXT NOT NULL`, `period TEXT NOT NULL`, `ref TEXT NULL`, `value NUMERIC(14,4) NOT NULL`, `definition TEXT NOT NULL`, `citation_url TEXT NOT NULL`, `citation_page TEXT NULL`, `retrieved_at TIMESTAMPTZ NOT NULL`.
`CHECK (citation_url <> '')` ← an uncited benchmark cannot exist

**`backtest_run`** — **IMM** — `window_start DATE`, `window_end DATE`, `tier INT NOT NULL`, `metrics JSONB NOT NULL`, `limitations TEXT NOT NULL`, `input_hash TEXT NOT NULL`, `run_at TIMESTAMPTZ NOT NULL`. `CHECK (tier BETWEEN 1 AND 3)`, `CHECK (limitations <> '')`

**`system_event`** — `level TEXT`, `component TEXT`, `event TEXT`, `payload JSONB`. Index `(created_at DESC)`

---

# 6. THE FIVE CONSTRAINTS THAT MUST BE PROVEN BY TEST

These are the point of this phase. Each needs a test that feeds bad data and asserts the database **rejects** it.

| # | Constraint | Test must prove |
|---|---|---|
| **C1** | `route_weight.evidence_rung NOT NULL` | Inserting a weight without an evidence rung raises `IntegrityError` |
| **C2** | Weights sum to 1 ± 1e-9 per `weight_set_version` | Committing a version summing to 0.97 raises; summing to 1.0 commits |
| **C3** | Immutability | `app_rw` role attempting UPDATE or DELETE on each IMM table raises `InsufficientPrivilege` |
| **C4** | `total_fare > 0` and `provenance NOT NULL` | Fares of 0 and −100 both raise; null provenance raises |
| **C5** | Simulated data barred from headline | Inserting a HEADLINE `index_observation` derived from any `SIMULATED_DEMO` quote raises |

For **C3**, create two DB roles in the migration: `apix_migrator` (full DDL) and `apix_app` (DML, but `REVOKE UPDATE, DELETE` on all IMM tables). Tests connect as `apix_app`.

For **C5**, implement as a `BEFORE INSERT` trigger on `index_observation` that checks the contributing quote set. If you cannot express the contributing set at insert time, tell me — do not silently downgrade this to application-level validation.

---

# 7. SEED DATA

## Lead-time buckets — exactly six

| code | days | lambda | cpi_comparable |
|---|---|---|---|
| T1 | 1 | 0.166667 | false |
| T7 | 7 | 0.166667 | false |
| T15 | 15 | 0.166667 | false |
| **T21** | **21** | 0.166667 | **true** |
| T30 | 30 | 0.166667 | false |
| T45 | 45 | 0.166667 | false |

T+21 exists because **MoSPI's CPI 2024 collects domestic airfare at a 21-day advance-purchase window** (Expert Group Report §3.9). It is the only bucket directly comparable to the official CPI. Do not drop it, do not renumber it.

λ is uniform because no public Indian booking-lead-time distribution was found. This is a **labelled prototype assumption**, not a finding.

## Airports — seed these 10

DEL Delhi · BOM Mumbai · BLR Bengaluru · MAA Chennai · CCU Kolkata · HYD Hyderabad · AMD Ahmedabad · COK Kochi · PNQ Pune · GAU Guwahati
(IATA, name, city, state, tz = `Asia/Kolkata`)

## Routes — directional, 10 pairs = 20 rows

DEL-BOM, DEL-BLR, DEL-CCU, DEL-MAA, DEL-HYD, BOM-BLR, BOM-MAA, BLR-HYD, BOM-AMD, DEL-GAU — **plus the reverse of each**.

## Route weights — DO NOT SEED

⚠️ **Leave `route_weight` empty.** Weight evidence (open item O-5) is unresolved. Seeding placeholder weights is exactly the failure mode this project must avoid. Create the table, the constraints and the tests; insert no rows. Tests use synthetic weight sets created inside the test, clearly named `test_weight_set_*`.

## Sources — seed with correct tiers, all disabled

| code | tier | transport | enabled |
|---|---|---|---|
| mospi_cpi | 5 | api | false |
| amadeus | 1 | api | false |
| indigo_tariff, airindia_tariff, aix_tariff, akasa_tariff, spicejet_tariff | 2 | document | false |
| indigo_web, airindia_web, aix_web, akasa_web, spicejet_web | 3 | browser | false |
| makemytrip, yatra, easemytrip, cleartrip, ixigo, goibibo | 4 | browser | **false** |

Tier-4 sources are seeded so they are visible and auditable, and stay disabled because their robots.txt disallows automated flight-search collection. This is deliberate. Do not enable them.

## methodology_version — one row

`version = '1.0.0'`, `effective_from = today`, `changelog = 'Initial. Jevons short (chain-base) elementary; Young/Modified Laspeyres higher-level, weighted arithmetic.'`

```json
params = {
  "elementary_formula": "jevons_short",
  "higher_level_formula": "young_modified_laspeyres",
  "higher_level_aggregation": "weighted_arithmetic_mean",
  "outlier_method": "mad_log_relatives",
  "outlier_k": 3.5,
  "min_quotes_per_stratum": 3,
  "winsorise_below_n": 5,
  "winsorise_percentiles": [5, 95],
  "imputation": "carry_until_reappearance_no_weight_redistribution",
  "base_index_value": 100
}
```

---

# 8. FIXTURES

## `tests/fixtures/golden_day/`

One route (DEL-BOM), one bucket (T7), prior stratum index 100.000000, four matched pairs:

| pair | p(t-1) | p(t) |
|---|---|---|
| A | 5000 | 5000 |
| B | 5500 | 5610 |
| C | 6000 | 6300 |
| D | 6200 | 20000 |

D is an outlier that the Phase 9 engine must reject; the expected stratum index is **102.313**. **You are not building the engine this phase** — just persist the fixture and assert it round-trips through the schema with full lineage intact.

## `tests/fixtures/adversarial/`

Each of these must be **rejected or correctly flagged** — build one test per case:

zero fare · negative fare · duplicate quote on the dedup key · missing `provenance` · invalid IATA (`XX`, `DELH`, lowercase) · `origin = destination` · fare components summing above total · null `evidence_rung` on a weight · weight set summing to 0.97 · `SIMULATED_DEMO` quote reaching a headline row · UPDATE attempt on each IMM table · currency `USD` · `travel_date` before `collected_date` · departure timestamp with no timezone.

---

# 9. LINEAGE TEST — the one that matters most

Write `test_lineage_traversal` proving a single query walks:

```
index_observation (HEADLINE)
  → index_contribution → route
  → normalised_quote (route, bucket, collected_date)
  → raw_quote → raw_response → collection_request → compliance_decision → source
  → cleaning_event (all rules applied to that quote)
```

and returns, for one fare: its value, source, `collected_at`, provenance, and every cleaning rule that touched it. **This query is what the entire UI traceability feature depends on.** If the schema cannot support it in one reasonable query, the schema is wrong — tell me before working around it.

---

# 10. DEFINITION OF DONE

Do not report success until every line is true:

- [ ] `docker compose up` starts PG 16; `alembic upgrade head` runs clean from empty
- [ ] `alembic downgrade base` then `upgrade head` runs clean (migrations are reversible)
- [ ] All 21 tables exist with specified columns, types, keys, indexes and CHECKs
- [ ] Both DB roles exist; `apix_app` cannot UPDATE or DELETE any IMM table
- [ ] Constraint tests C1–C5 all pass, each by **provoking a failure**
- [ ] Every adversarial fixture case has a test and behaves as specified
- [ ] `test_lineage_traversal` passes
- [ ] Seeds load idempotently (running twice does not duplicate)
- [ ] `route_weight` is **empty** after seeding
- [ ] Pydantic contracts exist for every table and round-trip against SQLAlchemy models
- [ ] `ruff check` and `mypy --strict packages/schemas` are clean
- [ ] No float anywhere in a money path (`grep` and confirm)
- [ ] `.env.example` committed with **no real values**
- [ ] README documents setup in ≤5 commands

---

# 11. REPORT BACK IN THIS FORMAT

```
## STATUS
<one line: complete / blocked>

## TEST OUTPUT
<paste actual pytest output, full summary line>

## DEFINITION OF DONE
<the checklist above, each marked ✅ / ❌ with evidence>

## FILES CREATED
<tree>

## DEVIATIONS
<anything you did differently, and why. "None" if none.>

## DEFERRED
<anything not implemented>

## QUESTIONS FOR ARCHITECT
<ambiguities you hit>
```

Do not summarise the test run. **Paste it.** I verify against output, not description.

---

# 12. OUT OF SCOPE — DO NOT BUILD

Scrapers or adapters · compliance gate logic · index engine · REST API · frontend · Docker images beyond Postgres · CI pipelines · Amadeus or MoSPI integration.

Tables for these exist so the schema is complete. Their **logic** comes in later phases.
