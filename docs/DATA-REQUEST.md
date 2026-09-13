# Data request to MoSPI / DGCA

**What APIx needs to produce a live index, from whom, and in what form.**
**12 September 2026.**

---

## Why this document exists

APIx has no live data source, and the reason is not that one was not looked for.

Amadeus closed its self-service tier on **17 July 2026**. The six OTAs named in
PS 26056 were checked individually against their own robots.txt on **13
September 2026**, using the compliance gate's own parser
(`docs/evidence/O8-source-permissions.md`): **one of eleven** sources leaves a
plausible fare-search path undisallowed, and even that one blocks the query
pattern a fare search would use. Two airline sites could not be reached at all,
which is itself a signal.

Automated collection from public airline and OTA portals is therefore **not
available to this project** on terms an official statistic could rest on. That is
a finding, not an obstacle to be worked around: the alternative is collecting
from sources that have asked us not to, which would make the resulting statistic
indefensible whatever its accuracy.

**The data APIx needs already exists inside government.** This document asks for
it.

---

## What is requested, in order of value

### 1. MoSPI's existing airfare price quotes — *the strongest option*

MoSPI already collects airfares from online platforms for CPI 2024 (CPI 2024
FAQ, Q27). If APIx consumes those same quotes, it is aligned with CPI **by
construction** rather than by argument, and raises no new legal ground at all.

| | |
|---|---|
| **Holder** | Price Statistics Division / Regional Offices |
| **Frequency needed** | Every collection round, as collected |
| **Format** | Any tabular export; the contract below is what APIx validates against |
| **Legal basis** | Already collected under existing CPI authority |
| **Unblocks** | A live index, and direct comparability with the CPI airfare item |

### 2. DGCA city-pair passenger volumes — *fixes the largest weakness*

Route weights are currently a **gravity proxy on AAI airport throughput**
(evidence rung 3), which overstates Delhi and Mumbai because those figures
include international passengers. Airport throughput is not city-pair traffic.

City-pair volumes take the weights to rung 1 and close the audit's only
outstanding **NOT MET** requirement that could be closed with data.

| | |
|---|---|
| **Holder** | DGCA |
| **Frequency needed** | Annual is sufficient |
| **Format** | Origin, destination, passengers, period |
| **Unblocks** | Requirement A4. Days of work, not weeks — the weight engine already accepts this shape |

### 3. The DGCA popular-routes list used for CPI airfare collection

The Expert Group Report (§4.5.3.1) records that DGCA supplies MoSPI a list of
popular routes for CPI airfare collection. Aligning APIx's basket to that list
makes the two **directly** comparable rather than approximately so.

### 4. DGCA Tariff Monitoring Unit observations

78 routes, monthly, already collected. Monthly frequency suits **validation**
rather than a daily index — but it is the series PS 26056's back-testing
requirement assumes exists, and it would make that requirement satisfiable.

### 5. Airline tariff sheets furnished under ATC 02/2010

Airlines already furnish these to DGCA monthly. They are **fare bands, not
transacted prices**, and APIx marks them as such: they can bound and validate the
index but must never feed it.

---

## The interchange contract

APIx validates supplied data against the contract below
(`packages/collector/supply.py`). **If your format differs, say so** — the
mapping is one function, and changing it is a morning's work. What should not
change is the meaning of these fields, because the rest of the pipeline depends
on it.

### Required — a row without these is rejected

| Field | Type | Notes |
|---|---|---|
| `collected_date` | date | When the price was observed. ISO 8601 preferred; DD/MM/YYYY accepted |
| `travel_date` | date | Departure date. With `collected_date`, gives the advance-purchase window |
| `origin` | 3-letter IATA | e.g. `DEL` |
| `destination` | 3-letter IATA | e.g. `BOM` |
| `carrier` | 2-letter IATA | e.g. `6E`, `AI`, `SG`, `QP`, `IX` |
| `total_fare` | decimal | What a traveller pays, all-inclusive |
| `currency` | text | `INR` only; foreign currency is refused, not converted |

### Requested — improves quality, absence does not invalidate a row

`flight_number`, `departure_time`, `cabin`, `fare_brand`, `base_fare`, `taxes`,
`udf`, `convenience_fee`, `baggage_kg`, `refundability`, `changeability`,
`source_platform`.

`fare_brand`, `cabin`, `baggage_kg`, `refundability` and `changeability` matter
more than they may appear: they are how APIx establishes that two observations
are the *same product* before comparing their prices. Without them, matching
falls back to weaker identifiers and the index measures product substitution
alongside price change.

### How refusals are reported

Every rejected row is returned with its **row number and reason**. A supplier is
entitled to know exactly which rows were not used — "1,204 of 50,000 rejected"
with no detail is not something anyone can act on. A file rejecting more than
20% of its rows is flagged as unusable rather than partially ingested, because
that pattern signals a format mismatch, and ingesting the remainder would build
an index on whichever rows happened to parse.

---

## Decisions needed from the ministry

These block work and cannot be taken by a development team.

1. **Which source**, and who signs the instrument.
2. **Is this an official statistic or experimental statistics?** — confirmed as
   official. Noted here because it sets the validation bar in item 4.
3. **Named statistical owner** empowered to approve the methodology and sign off
   each release. The publication gate requires an attributed approver; it will
   refuse to publish without one.
4. **Acceptance of the parallel-run requirement.** At least two full quarters
   computing APIx alongside the CPI airfare item before publishing. This is
   calendar time and cannot be compressed.
5. **Target publication frequency** and the release calendar.
6. **Hosting environment**, and confirmation of who commissions the STQC and
   CERT-In engagements.

---

## What is ready and waiting

| Component | Status |
|---|---|
| Ingestion and validation | Built and tested against this contract |
| Compliance gate | Built; refuses anything not permitted, no override exists |
| Index engine | Built. CPI 2024 formulae, Decimal-exact, golden test in CI |
| Weight engine | Built. Accepts city-pair volumes directly — currently a rung-3 proxy |
| Publication control | Built. Named approval, release calendar, revisions, withdrawals |
| Dissemination | Built. SDMX structure, bulk CSV and JSON, versioned API |
| Dashboard | Built. Seven pages, WCAG 2.1 AA tested |
| Production configuration | Built. Fails closed; demo tooling cannot load in production |

**968 tests, CI on every push.**

Integration is **one to two weeks per source** once data and an agreement exist.
The critical path is the agreement, not the code.
