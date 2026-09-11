# Demo Script

## Setup, before anyone is watching

```powershell
docker compose up -d
$env:APIX_CONTACT_URL="https://github.com/sujal128005/apix"
$env:PYTHONPATH="apps"
.venv\Scripts\python scripts\run_demo_pipeline.py --days 21 --reset
.venv\Scripts\python -m uvicorn api.main:app --port 8000
```

Have open: the dashboard, and a terminal with the test suite ready to run.

---

## Five minutes

**1 · The problem, in one table.** Open `/lead-time`. Booking tomorrow costs
**210% of the T+21 fare**; booking six weeks out costs 92%. A monthly collection
at a single horizon cannot see any of that.

**2 · The gold bar.** T+21 is highlighted because that is where MoSPI actually
collects domestic airfare — Expert Group Report §3.9. Everything either side of
it is currently invisible to CPI.

**3 · The headline that isn't there.** Back to `/`. The banner explains that the
database refused to compute a headline index, because the data is simulated.
*"Most systems would show a plausible number here. Ours refuses, and the refusal
is a database trigger, not a policy."*

**4 · The blocked source.** `/operations`. MakeMyTrip's adapter exists, is
tested, and the compliance gate refuses to run it. There is no override flag —
a static scan over the source tree enforces that.

**5 · The honest backtest.** `/api/v1/backtest`. The PS asks for comparison
against public DGCA monthly fare data; that series does not demonstrably exist.
We substitute the official CPI domestic-airfare index — item 294, COICOP
07.3.3.1.2.01, an exact scope match — and report that even that does not yet
overlap.

---

## Ten minutes, technical

**Methodology.** `/methodology`. Jevons short at the elementary level, Young by
weighted arithmetic mean above it — both cited to the Expert Group Report.
Geometric below, arithmetic above is deliberate CPI structure. The outlier rule
is labelled **"Ours. MoSPI prescribes no outlier rule for airfare."**

**One fare to one index number.** Run the golden test. Five matched pairs, one at
₹20,000 scoring a modified z of 40 and being rejected with a `cleaning_event`,
giving 102.484143 → 100.414024 → 100.103506, contributions summing exactly to the
movement. CI fails on any drift.

**Matched pairs.** Show `test_a_cheaper_competitor_does_not_masquerade_as_a_price_fall`.
Yesterday's cheapest was IndiGo at ₹6,000, today's a SpiceJet promo at ₹4,000.
Naive pairing reports a 33% fall; in fact IndiGo rose 5% and a different airline
appeared. Nothing downstream would catch it.

**Lineage.** `/api/v1/provenance/{id}` walks one observation back through raw
quote, raw response, collection request, compliance decision and source.

**Enforcement.** The database refused five pieces of my own bad code during this
build — see `docs/AUDIT.md` §D. That's the argument: the guarantees aren't
documentation, they're enforced, and they demonstrably caught real mistakes.

---

## Questions you will get

**"Why is there no headline number?"**
Because the data is simulated and the database refuses to publish an index from
simulated observations. Enable a real source and it appears.

**"Your route weights are equal — isn't that arbitrary?"**
Yes, and it's labelled evidence rung 4 everywhere the weight appears. We could
not find a public DGCA per-city-pair passenger-volume table. The Expert Group
Report §4.6.3.3 sanctions passenger-count proxy weights, so the method is right;
the data is what's missing.

**"You didn't do the DGCA backtest."**
It could not be done as specified. That series does not demonstrably exist, and
we say so on the page rather than manufacturing one.

**"Isn't this just a scraper?"**
It collects nothing without a capability token that only the compliance gate can
mint. An adapter author cannot write a fetch that skips the gate — not by policy,
but because the object cannot be constructed.

**"How do I know the numbers are right?"**
Every index value stores the methodology version, weight-set version, its
predecessor, and a hash of its inputs. The engine is a pure function. The golden
test asserts hand-calculated arithmetic.
