# APIx — Real-time Airfare Price Index for India

SIH 2026, Problem Statement 26056. A daily airfare price index built to augment
MoSPI's Consumer Price Index, using MoSPI's own published CPI 2024 formulae.

**This repository is at Phase 3: the data layer and its contracts.** There is no
collector, no index engine, no API and no UI yet. What exists is the schema every
later phase is built on, and the tests that prove it holds.

---

## Setup

Five commands. On Windows use `py -3.12`; on Linux or macOS use `python3.12`.

```bash
docker compose up -d                      # 1. PostgreSQL 16 on 127.0.0.1:5433
py -3.12 -m venv .venv                    # 2. Python 3.12 virtual environment
.venv/Scripts/pip install -e ".[dev]"     # 3. install APIx and its dev tools
.venv/Scripts/python scripts/init_db.py   # 4. create, migrate and seed the database
.venv/Scripts/pytest                      # 5. run the suite
```

On Linux or macOS, replace `.venv/Scripts/` with `.venv/bin/`.

`.env` is optional against the bundled container: `db/settings.py` falls back to
the same local development values `docker-compose.yml` uses. For anything else,
copy `.env.example` to `.env` and fill it in. `.env.example` is committed with no
values in it, and `.env` is git-ignored.

The container publishes **5433**, not 5432, so APIx does not collide with another
PostgreSQL already bound to the conventional port. Override with `APIX_DB_PORT`.

### Migrations on their own

```bash
.venv/Scripts/alembic -c db/alembic.ini upgrade head
.venv/Scripts/alembic -c db/alembic.ini downgrade base
```

Migrations bootstrap as the superuser because revision 0003 creates two
cluster-global roles. After that they can run as `apix_migrator`. The
application always connects as `apix_app`.

### Checks

```bash
.venv/Scripts/ruff check .
.venv/Scripts/mypy --strict packages/schemas
.venv/Scripts/pytest -m "constraint or adversarial"   # just the barrier tests
```

---

## What is in the database after setup

| | |
|---|---|
| 10 airports | DEL BOM BLR MAA CCU HYD AMD COK PNQ GAU |
| 20 routes | 10 city pairs, both directions (ADR-017) |
| 6 lead-time buckets | T1 T7 T15 **T21** T30 T45 |
| 18 sources | all disabled |
| 1 methodology version | 1.0.0 |
| **0 route weights** | correct — see below |
| **0 base periods** | correct — see below |

---

## Things that look like bugs and are not

**`route_weight` is empty.** Weight evidence (open item O-5) is unresolved. A
placeholder weight would be indistinguishable from a sourced one in every chart,
API response and export downstream, so no row is written until real evidence
exists. Tests build their own weight sets, named `test_weight_set_*`.

**Every source is disabled.** Sources are opt-in, never opt-out. The six Tier-4
OTAs are seeded so they are visible and auditable in the compliance register, and
they stay disabled: their robots.txt disallows automated flight-search
collection. A source absent from the register cannot be *shown* as blocked; one
present and disabled can be.

**There are six lead-time buckets, not five.** T+21 exists because MoSPI's CPI
2024 collects domestic airfare at a 21-day advance-purchase window (Expert Group
Report §3.9), which makes it the only bucket directly comparable to the official
index.

**λ is the same for every bucket.** A labelled prototype assumption, not a
finding: no public Indian booking-lead-time distribution was located. It is
recorded in the data so the assumption is visible rather than buried in code.

**Elementary strata are geometric and everything above them is arithmetic.**
Jevons short (chain-base) below, Young / modified Laspeyres above. That asymmetry
is MoSPI's deliberate structure, not an inconsistency.

**`airport.icao` is NULL for all ten rows.** The build brief's seed
specification does not supply ICAO codes, and anything it does not specify stays
NULL. The same applies to `source.base_url`: the URLs are unverified open items
(O-4), so all eighteen are NULL.

**`base_period` is empty.** The reference period an index is 100 against is
established in Phase 9 from real collection dates. Inventing one now would put a
fabricated reference point underneath every index value ever published — the same
failure mode as a placeholder route weight.

**`base_period` is the one versioned definition that is *not* append-only.** It
is a definition, not an observation, and Phase 9 may refine it before anything is
published. Reproducibility is protected by the reference rather than the
definition: `index_observation` is append-only, so a published row can never be
repointed at a different base period.

**`adapter_key` is not one-to-one with `code`.** One adapter serves a whole
family: five airline tariff sheets share `airline_tariff_doc_v1`, five airline
sites share `airline_web_v1`, six OTAs share `ota_web_v1`.

---

## The five barriers

Each is enforced by PostgreSQL, and each has a test that provokes the failure.

| | Barrier | Where it lives |
|---|---|---|
| **C1** | A weight cannot exist without stating its evidence | `NOT NULL` on `route_weight.evidence_rung` |
| **C2** | Weights sum to 1 ± 1e-9 per weight set | deferred constraint trigger, fires at `COMMIT` |
| **C3** | 13 append-only tables cannot be updated or deleted | `UPDATE`/`DELETE` revoked from `apix_app` |
| **C4** | A fare is positive and always says where it came from | `CHECK` + `NOT NULL` |
| **C5** | `SIMULATED_DEMO` can never reach a headline index value | `BEFORE INSERT` triggers on `index_observation` and `index_contribution` |

C5 fails closed. On a date where simulated demo quotes exist at all, no headline
value can be written — whether or not the engine would in fact have selected
them. Simulated data is a separate lineage, not a degraded form of live data.

That costs nothing in practice: `LIVE` mode should contain no `SIMULATED_DEMO`
quotes at all, and `OFFLINE_DEMO` mode runs on frozen previously-collected *real*
data carrying `LIVE_COLLECTED` or `PUBLIC_HISTORICAL`. `SIMULATED_DEMO` is for
development fixtures only, so the trigger never blocks a demo.

A sixth barrier joined them in the Phase 3 review:
`uq_index_observation_identity` is `UNIQUE NULLS NOT DISTINCT`, so two HEADLINE
values for the same date and methodology version are impossible. Without it,
`ref_id` and `bucket_id` being NULL on a headline row would let PostgreSQL treat
the duplicates as distinct and break reproducibility.

---

## Traceability

The point of the schema is that a published number can be walked back to a single
fare in **one query**:

```
index_observation (HEADLINE)
  → index_contribution → route
  → normalised_quote (route, bucket, collected_date)
  → raw_quote → raw_response → collection_request → compliance_decision → source
  → cleaning_event (every rule that touched the quote)
```

The query, and the proof that it returns a fare's value, source, collection time,
provenance and cleaning history, are in
`tests/integration/test_lineage_traversal.py`.

---

## Layout

```
db/
  alembic.ini            migrations config; the URL is never stored here
  migrate.py             programmatic upgrade/downgrade
  settings.py            connection settings, read from the environment
  migrations/versions/
    0001_initial_schema.py            21 tables, uuidv7(), route_undirected view
    0002_constraint_triggers.py       C2 and C5
    0003_roles_and_privileges.py      C3: apix_migrator and apix_app
    0004_base_period_identity_key.py  base_period table; identity key made
                                      NULLS NOT DISTINCT; strict travel-date check
    0005_base_period_mutable.py       base_period is a definition, not an
                                      observation, so it is not append-only
  seeds/                 airports, routes, buckets, sources, methodology
packages/schemas/
  enums.py               controlled vocabularies, mirrored into CHECK constraints
  uuid7.py               RFC 9562 UUIDv7, twin of the PL/pgSQL uuidv7()
  hashing.py             collection_request.query_hash
  models/                SQLAlchemy 2.0, one module per domain group
  contracts/             Pydantic v2, one contract per table
scripts/init_db.py       create, migrate, seed, report
tests/
  unit/                  enums, contracts, identifiers, the no-float scan
  integration/           schema shape, migrations, C1–C5, adversarial, lineage
  fixtures/              the golden day and the adversarial manifest
```

---

## Conventions that are not negotiable

- **Money is `Decimal` and `NUMERIC`.** Never float. Enforced by a test that
  parses the source and fails on any `float` annotation or conversion.
- **Timestamps are `TIMESTAMPTZ`, stored UTC.** IST is applied when rendering,
  never in storage. The database is pinned to UTC by migration 0001, and the
  contracts reject naive datetimes.
- **Primary keys are UUIDv7.** Time-ordered, so rows read back in creation order.
- **Corrections are new rows under a new version.** Never an edit. That applies
  to the migrations too: revision 0004 amends 0001 rather than rewriting it.

---

## Open items

`docs/deferred.md` records work identified but deliberately not built here —
currently the Phase 7 fuzzy near-duplicate requirement (D-1) and the pending
nullability ruling on six columns (D-2).
