# APIx — Real-time Airfare Price Index for India

**Smart India Hackathon 2026 · Problem Statement 26056**
**Ministry of Statistics and Programme Implementation · Data Informatics & Innovation Division**

A daily airfare price index for India, computed with MoSPI's own published CPI 2024
formulae and built to augment the Consumer Price Index.

`920 tests passing · ruff clean · mypy --strict clean · CI on every push`

---

## Why this exists

MoSPI's CPI 2024 series already collects airfares from online platforms, at a
**21-day advance-purchase window**, priced **weekly**. Indian airfares do not
behave weekly. On the routes in this basket, booking tomorrow costs **210% of
the 21-day fare**; booking six weeks out costs **92%**.

APIx is the collection and index layer that makes that visible: daily, route-level,
across six booking horizons, with every published number traceable to an individual
fare quote.

It is not a replacement for CPI, and it does not replicate MoSPI's estimator.
APIx adopts the **CPI 2024 compilation framework** — Jevons short at the
elementary level, Young / Modified Laspeyres above it — and applies it to a
higher-frequency collection design of its own.

Same formula family, different estimator. MoSPI's airfare sampling uses State
and UT capital Regional Offices, popular routes supplied by DGCA, and specific
airline selection. APIx uses twenty routes with equal weights and daily
collection. Those are not the same statistical population, and the difference is
not cosmetic.

---

## Quick start

Five commands. Windows shown; on Linux or macOS use `python3.12` and replace
`.venv/Scripts/` with `.venv/bin/`.

```powershell
docker compose up -d                              # PostgreSQL 16 on 127.0.0.1:5433
py -3.12 -m venv .venv                            # Python 3.12 only
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python scripts\init_db.py           # migrate and seed
.venv\Scripts\pytest -q                           # expect 920 passed
```

Then populate it and start the site:

```powershell
$env:APIX_CONTACT_URL="https://github.com/your-name/apix"
$env:PYTHONPATH="apps"
.venv\Scripts\python scripts\run_demo_pipeline.py --days 21 --reset
.venv\Scripts\python -m uvicorn api.main:app --port 8000
```

Open **http://127.0.0.1:8000**.

`APIX_CONTACT_URL` is required. The compliance gate refuses to crawl anonymously:
every request must carry a contact address a site operator could reach. Without it
you get an explicit refusal rather than silent zeros.

---

## What you can look at

| Page | What it answers |
|---|---|
| `/` | Current index, route movements, benchmark, source compliance |
| `/routes` | Per-route index history, basket weight and the evidence behind it |
| `/lead-time` | Fare by booking horizon, T+21 marked as the CPI-comparable window |
| `/quality` | Outlier rejections, imputation rate, decomposition completeness |
| `/methodology` | Every formula cited to source; every assumption labelled |
| `/operations` | Pipeline health, source status, collection runs, alerts |
| `/api/docs` | OpenAPI documentation |

---

## Methodology

APIx does not invent an index formula. It implements what MoSPI specifies for
CPI 2024, sourced from the **Expert Group Report on Comprehensive Updation of the
Consumer Price Index** (January 2026, Price Statistics Division, NSO).

**Elementary level — Jevons short (chain-base):**

```
I(t) = GM( p(t) / p(t-1) ) × I(t-1)
```

Matched pairs only, on a **product specification**: route, carrier, cabin, trip
type, routing, departure-time band, fare brand, baggage, refundability,
changeability and passenger type. Comparing "cheapest today" with "cheapest
yesterday" would record a change of airline as a change of price.

Flight number is excluded deliberately — it is operational metadata, and a
schedule change that renumbers a flight leaves the product unchanged. Departure
band is included instead, because a dawn and a late-evening departure are not the
same product.

**Route and headline — Young / Modified Laspeyres**, the weighted arithmetic mean
of lower-level indices.

Geometric below, arithmetic above. That asymmetry is deliberate CPI structure: the
report records that CPI 2024 moved house rent *from* weighted geometric *to*
weighted arithmetic specifically to align it with every other item.

| Decision | Source |
|---|---|
| Jevons short at elementary level | Expert Group Report §4.6.1 |
| Young / Modified Laspeyres | Expert Group Report §4.6.2 |
| 21-day domestic advance-purchase window | Expert Group Report §3.9 |
| Impute and carry until reappearance; never redistribute weights | Expert Group Report §4.6.4 |
| Passenger counts as proxy weights | Expert Group Report §4.6.3.3 |
| Airfares collected from online platforms | MoSPI CPI 2024 FAQ, Q27 |
| Comparator: item 294, COICOP 07.3.3.1.2.01, *domestic* | MoSPI open API, verified 7 Sep 2026 |
| Outlier screening — extreme observations flagged, not rejected | **Ours.** MoSPI prescribes no outlier rule for airfare. Only impossible relatives (outside 0.01–100x) are removed; `k` affects what is reported, not the index. `docs/evidence/O7-...` |

Full detail at `/methodology` and in `docs/`.

---

## Compliance

Collection is governed by a gate that runs before any adapter and cannot be
bypassed.

`ComplianceToken` requires a module-private sentinel to construct, so only the
gate can mint one — and every network-touching function requires one. An adapter
author cannot write a fetch that skips the gate, not because a rule forbids it
but because the object cannot be built. A static scan over the source tree
asserts there is no override flag, no permissive environment variable, and no
second place that mints tokens.

- `BLOCKED_ROBOTS` is terminal. No retry, no override.
- robots.txt handling fails closed: 404 means allowed, but 403 on robots.txt
  itself means disallow everything.
- Crawl-delay floor of 5s even where a site permits faster.
- Config overrides run one direction only — more conservative, never less.
- The six OTAs named in the problem statement have adapters that are **built,
  registered, and never executed**, because their terms disallow collection.

Detail in `docs/scraping-compliance.md` and ADR-005, ADR-006, ADR-018, ADR-019.

---

## Publication control

A computed figure is not a published one. It enters a release lifecycle —
`PENDING → APPROVED → PUBLISHED`, with `WITHDRAWN` as a public act rather than a
deletion — and becomes visible only when a named person approves it against a
release calendar.

A correction creates a new **revision** beside the original rather than replacing
it, and must state its reason. Both are retained, so the question *what was
published on the 14th?* remains answerable after a correction on the 20th.

---

## Provenance

Every observation carries a non-null provenance label, enforced by database
constraint. A trigger refuses to compute a headline index for any date carrying
`SIMULATED_DEMO` observations, so development data cannot become a published
statistic whatever happens upstream.

Any single number can be walked back to the fare that produced it:

```
GET /api/v1/provenance/{quote_id}
```

returns the observation, its raw quote, the raw response and its hash, the
collection request, the compliance decision that permitted it, and the source.

---

## Architecture

```
source registry → compliance gate → adapters → raw storage
               → normalisation → matched pairs → index engine
               → API → dashboard
```

| Layer | Package |
|---|---|
| Schema, models, enums | `packages/schemas` |
| Compliance gate, token, robots | `packages/compliance` |
| Adapter contract, runner, TLS ladder | `packages/collector` |
| Normalisation, imputation, weights, orchestrator, backtest | `packages/pipeline` |
| Jevons and Young, pure and Decimal-exact | `packages/index_engine` |
| API and dashboard | `apps/api` |

**Stack:** Python 3.12, PostgreSQL 16, SQLAlchemy 2.0, Alembic, Pydantic v2,
FastAPI, server-rendered HTML. No Node toolchain and no CDN — every asset is
served by this process, so a demo cannot fail because a stylesheet did not
download.

**920 tests** — 490 unit, 430 integration. The count is not the point; what it
covers is:

| Kind | What it protects |
|---|---|
| Golden | Hand-calculated index values. CI fails on any drift. |
| Constraint | Each database guarantee proven by *provoking* a failure, not confirming a success |
| Static scan | No bypass around the compliance gate, no float on a money path, no disabled TLS verification |
| Regression | Adapter parsers replay frozen fixtures offline |
| Contract | Every API response carries its methodology and weight-set version |

Money is `Decimal` end to end — deterministic high-precision decimal arithmetic
with controlled rounding, not mathematical exactness: logarithms and exponentials
still approximate. A test scans the source tree and fails the build on any
`float` in a money path; it caught five genuine cases during development.

---

## Validation

`GET /api/v1/backtest` — three tiers, per ADR-015.

The problem statement asks for back-testing against *publicly available DGCA
monthly average-fare data*. **Research could not establish that such a series
exists.** DGCA's Tariff Monitoring Unit covers 78 routes monthly, but its output
surfaces through parliamentary replies rather than as a downloadable time series.

**That statement needs care.** DGCA plainly holds airfare data — its Tariff
Monitoring Unit monitors 78 routes monthly, and parliamentary answers have
published DGCA-derived average fares across dozens of sectors. What this project
could not locate is a continuously downloadable, route-level monthly series in a
form suitable for the back-test the problem statement describes.

APIx compares instead against the **official CPI 2024 domestic-airfare index** —
item 294, COICOP 07.3.3.1.2.01. That is the **same conceptual CPI item, not the
same underlying sample**: MoSPI's collection design and APIx's twenty-route
basket are different statistical populations. Comparison is on **movements**,
never levels, because the base periods differ.

The current result is **zero overlapping months**, and the endpoint reports that
shortfall instead of computing an error metric over an overlap that does not
exist. It resolves with collection time, not with code.

---

## Known limitations

Stated here rather than left to be discovered.

| Limitation | Status |
|---|---|
| No live transacted-price source; all observations are `SIMULATED_DEMO` | **Amadeus Self-Service was decommissioned 17 Jul 2026**; Tier 2 is now the path |
| **Route weighting is a proxy.** Derived from AAI airport throughput (evidence rung 3), not DGCA city-pair traffic. Overstates Delhi and Mumbai, whose figures include international passengers | Open item O-5 — still the largest weakness |
| No headline index is ever published | By design, while data is simulated |
| Index **levels** not comparable with CPI — only movements | Permanent, by construction |
| Airfare *item* weight unknown; Transport's 8.796 is not a stand-in | Needs Annexure 5.3 |
| Coverage: economy, one-way, direct, one adult, 20 routes | Constant-quality scope |
| Amadeus adapter written, tested, **permanently disabled** | Self-service tier no longer exists; Enterprise requires a commercial account |
| Tariff-sheet URLs unresolved | Open item O-4 — **now the critical path** |
| Rate limiter is per-process | Adequate for a prototype; documented |

---

## Repository

```
apps/api/              FastAPI application and dashboard
packages/              schemas · compliance · collector · pipeline · index_engine
db/migrations/         Alembic revisions
scripts/               pipeline runner, MoSPI smoke tests, CPI series fetch
tests/                 unit · integration · fixtures
docs/                  AUDIT.md · DEMO-SCRIPT.md · adr/ · evidence/
data/reference/        CPI item identity, benchmark series, robots snapshots
```

`docs/AUDIT.md` is the requirement-by-requirement traceability matrix.
`docs/DEPLOYMENT.md` covers environment, roles, scheduling and health checks.
`docs/DEMO-SCRIPT.md` is the demo walkthrough.

---

## Scripts

```powershell
.venv\Scripts\python scripts\init_db.py                     # migrate and seed
.venv\Scripts\python scripts\run_demo_pipeline.py --days 21 --reset
.venv\Scripts\python scripts\smoke_mospi.py                 # verify MoSPI API reachability
.venv\Scripts\python scripts\fetch_cpi_airfare_series.py    # refresh the benchmark
```

`--reset` needs migrator credentials, because index observations are append-only
and `UPDATE`/`DELETE` are revoked from the application role. Clearing an audit
trail is an administrative act and has the friction to match.

---

## Attribution

Built for SIH 2026. CPI data is retrieved from MoSPI's open API at
`api.mospi.gov.in` and is Government of India official statistics; APIx stores it
with its source URL and retrieval timestamp, and never presents it as its own
output.
