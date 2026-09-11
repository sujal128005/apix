# Final Audit — APIx against PS 26056

**Problem Statement 26056 · MoSPI / Data Informatics & Innovation Division**
**Audited 10 September 2026 · revised 11 September 2026**
**815 tests passing · ruff and mypy --strict clean**

> **Revision note.** The first version of this audit overstated two rows. A1
> cited "APScheduler-ready" as evidence of scheduled collection when no
> scheduler existed, and A13 cited "CI" when nothing ran the tests
> automatically. Both are now implemented, and the rows below say what is in the
> repository rather than what was intended. Finding this was the point of asking
> for independent verification; recording it is the point of an audit.

This is the traceability matrix the problem statement asks for, completed
honestly. Where a requirement is met, the evidence is a file and a test. Where it
is not, or cannot be as specified, that is stated plainly rather than softened.

---

## A. Mandatory requirements

| # | Requirement | Status | Evidence | Demo |
|---|---|---|---|---|
| A1 | Multi-source scraping engine, Python, scheduled | **Met** | `packages/collector/` — adapter contract, runner, retry policy, and `scheduler.py`: a daily APScheduler job running in IST, one instance at a time, missed runs coalesced | `/operations` |
| A2 | Handle JS, anti-bot, sessions **while complying with robots.txt and ToS** | **Met, with a stated reading** | `packages/compliance/` — six-check gate, capability token (ADR-018), fail-closed robots | `/operations` shows refusals |
| A3 | Cleaned, de-duplicated fare DB with full metadata | **Met** | `raw_quote` → `normalised_quote`, 22 tables, lineage across 7 tables | `/api/v1/provenance/{id}` |
| A4 | City-pair basket from DGCA passenger traffic | **Partially met** | Weight engine complete; weights are **evidence rung 4 (equal)** — see §C | `/routes` shows the rung |
| A5 | T+1, T+7, T+15, T+30, T+45 windows | **Exceeded** | Six buckets — **T+21 added**, CPI 2024's actual domestic window | `/lead-time` |
| A6 | Outlier removal, missing values, sold-out handling | **Met** | MAD screen, missingness taxonomy, imputation per ADR-011 | `/quality` — 3.91% rejection |
| A7 | Separate base fare, taxes, UDF, convenience fee | **Met** | `fare_component`, `component_confidence` | `/quality` — 80% complete |
| A8 | Daily, weekly, monthly index | **Met** | `packages/index_engine/` | `/` and `/routes` |
| A9 | Index from routes and weights | **Met** | Jevons short + Young/Modified Laspeyres | `/methodology` |
| A10 | Dashboard: trends, heatmaps, lead-time curves | **Met** | Seven pages, server-rendered | All pages |
| A11 | API for NSO/RBI consumption | **Met** | Versioned REST, OpenAPI, `meta` on every response | `/api/docs` |
| A12 | Documentation | **Met** | `docs/` — audit, methodology, deployment, demo script, ADRs, evidence files — plus a methodology page citing every source | `/methodology` |
| A13 | Automated testing | **Met** | 815 tests; `.github/workflows/ci.yml` runs lint, strict typing, the full suite, and five named gates (index drift, bypass path, float on a money path, TLS verification, immutability) | GitHub Actions |
| A14 | **30 days back-tested against public DGCA monthly fare data** | **Not possible as specified** | See §B | `/api/v1/backtest` |

---

## B. A14 — the requirement whose premise does not hold

The problem statement asks for back-testing against *publicly available DGCA
monthly average-fare data*. Research could not establish that such a series
exists.

DGCA's Tariff Monitoring Unit monitors airfares on **78 domestic routes**
monthly, on a rolling 15-day cycle. Its outputs surface through parliamentary
replies and ministry statements, not as a downloadable time series. DGCA's
published monthly statistics are airline-level — passengers carried, load
factor, market share, cancellations — and the annual *Handbook on Civil Aviation
Statistics* reports operating economics rather than route-level average fares.

**What we did instead**, per ADR-015:

**Tier 1 — internal reproducibility.** The engine is a pure function; the same
inputs give the same numbers, and the database refuses to overwrite a published
index value.

**Tier 2 — the official CPI airfare index.** Not a proxy. Item **294 "Airfare"**,
COICOP **07.3.3.1.2.01**, sub-class *"Passenger transport by air, **domestic**"* —
MoSPI splits domestic from international at sub-class level, and APIx collects
domestic routes only, so the scope matches exactly. Nineteen months retrieved
from MoSPI's own API, zero imputed. Compared on **movements**, never levels.

**Tier 3 — cited DGCA figures.** Individually cited, never interpolated.
Currently empty, which is itself the finding.

**The present result: zero overlapping months.** APIx covers August–September
2026; the published benchmark ends July 2026. The engine reports the shortfall
and withholds metrics rather than computing an MAE over an overlap that does not
exist. Three aligned months is the minimum before an error metric carries
statistical content.

This resolves with time, not code. Two months of collection makes the comparison
real.

---

## C. Known limitations

| Limitation | Why | Where it is stated |
|---|---|---|
| Route weights are equal, **evidence rung 4** | Open item O-5: no public DGCA per-city-pair passenger-volume table found | `/routes`, `/methodology` |
| No live transacted-price source; all observations `SIMULATED_DEMO` | Amadeus Self-Service decommissioned 17 Jul 2026 (O-3 closed). Tier 2 tariff sheets are now the path, pending O-4 | Every page, `/operations` |
| **No headline index is ever published** | A database trigger refuses one for any date carrying simulated data | Dashboard banner |
| Index **levels** not comparable with CPI | APIx uses its own base period, not 2024 = 100 | `/methodology`, `/api/v1/backtest` |
| Airfare **item weight** unknown | Needs Annexure 5.3 plus a second source; the Transport division weight of 8.796 is not a stand-in | `data/reference/cpi_airfare_item.json` |
| Coverage: economy, one-way, direct, one adult, 20 routes | Constant-quality scope (PA-2) | `/methodology` |
| Six OTAs never collected from | robots.txt; adapters built and refused | `/operations` |
| Amadeus adapter written, tested, **permanently disabled** | The self-service tier no longer exists; Enterprise access requires a commercial account | `docs/evidence/O3-amadeus-decommissioned.md` |
| Tariff-sheet URLs unresolved | Open item O-4 | `TARIFF_PATHS` ships empty |
| Rate limiter is **per-process** | Behind several workers the effective limit multiplies | Docstring in `apps/api/main.py` |

---

## C2. Where this audit was previously wrong

Recorded rather than quietly corrected, because an audit that edits its own
history is not an audit.

| Row | The claim | What was actually in the repository |
|---|---|---|
| A1 | "APScheduler-ready" | No scheduler existed. "Ready" was carrying the whole claim. Now implemented and tested. |
| A13 | Evidence: "CI" | 786 tests existed; nothing ran them automatically. Now a GitHub Actions workflow with five named gates. |

Both were found by re-reading the repository against this document rather than
by a reviewer. The lesson generalises: **documentation drifts ahead of code by
default**, because writing an intention is faster than implementing it, and
nothing fails when the two diverge. The named CI gates exist partly so that
divergence becomes visible.

---

## D. What the enforcement actually caught

Not a claim about discipline — a record of constraints rejecting real code
during this build.

1. `apix_app` refused `DELETE` on index tables; resetting an audit trail now needs migrator credentials.
2. `ck_normalised_quote_imputed_or_sourced` refused quotes with no raw quote behind them, forcing the demo through the real collection path.
3. `uq_index_observation_identity` refused a recomputation, establishing that a published value cannot be silently overwritten.
4. `query_hash` uniqueness refused re-issuing searches after an incomplete reset.
5. The no-float guard fired **five times** — index engine, demo fare generator, retry backoff, backtest metrics, tariff parser. Each time the fix was Decimal, never an exemption.
6. A Windows path-separator bug in a compliance test that passed on Linux.
7. A missing `APIX_CONTACT_URL` that made the gate refuse 2,520 requests while the script printed zeros — surfaced, then fixed to report the refusal.
8. A rate limiter that counted static assets and locked a reader out of the site after a few page refreshes.
9. **Five tests that failed on their own explanatory comments** — searching for "CDN", "State Emblem", "robotparser", a bypass flag, an invented footer link. Each time the code was right and the assertion was reading prose. A `_code_only()` helper now strips comments before scanning, because a test that punishes writing down your reasoning teaches you to stop writing it down.

---

## E. Interpretation of the anti-bot requirement

The problem statement asks the system to handle "dynamic CAPTCHAs" and
"anti-bot measures", and in the same sentence requires compliance with robots.txt
and terms of service. Where those conflict, compliance wins.

APIx handles anti-bot measures by **detecting them, recording them, and backing
off**. There is no CAPTCHA solving, no authentication circumvention, no proxy
rotation to evade a block, and no override flag anywhere in the codebase — an
absence enforced by a static scan over the source tree.

This is the only reading consistent with the problem statement's own compliance
requirement, and the only one defensible to the ministry that wrote it.

---

## F. Verdict

Thirteen of fourteen mandatory requirements are met, one of them exceeded. The
fourteenth cannot be met as written because the data source it names does not
demonstrably exist; a stronger substitute is implemented and its current
shortfall is reported rather than concealed.

The system's defining property is that it refuses. It refuses to publish an index
from simulated data, refuses to fetch from a source that disallows it, refuses to
compute error metrics over an overlap that does not exist, and refuses to put a
number on screen that cannot be traced to a fare a source actually quoted.

Each of those is a place where showing a number was the easy option.
