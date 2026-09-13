# The last-minute premium, on first contact with real data

**13 September 2026 — first live collection.**

## The claim this project has been making

PS 26056 states that Indian airfares "can vary by 200-400% within a single day
depending on advance-booking window". APIx has been built around that, and every
demo figure quoted so far came from synthetic observations produced by
`scripts/run_demo_pipeline.py` — including the "210% of the T+21 fare" that
appeared on the lead-time page and in walkthrough notes.

**That figure measured the demo generator, not the market.** The generator was
written with a hard-coded multiplier of 2.10 for T+1, so the page reported 210%
because it had been told to.

## What the first real data shows

84 fares from Akasa Air, DEL–BOM and BOM–DEL, collected 13 September 2026:

| Window | Mean fare |
|---|---|
| T+1 | ₹7,105 |
| T+21 | ₹7,570 |

**Booking tomorrow was cheaper than booking three weeks out.** The opposite of
the assumed direction.

## Why this is not yet a finding about airfares

**The comparison is confounded.** T+1 was Monday 14 September; T+21 was Sunday
4 October. Sunday departures carry higher demand. This compares a Monday flight
with a Sunday flight as much as it compares booking horizons.

That confound is a good argument for the T+21 bucket existing at all: CPI
collects at a *fixed* advance-purchase window precisely so that day-of-week and
seasonal effects do not masquerade as booking-horizon effects.

**The sample is tiny.** One carrier, two routes, one collection date, three
windows, 84 observations. Nothing about the Indian airfare market can be
established or refuted from it.

**Last-minute discounting is real.** Carriers do drop prices on unsold seats
close to departure. The assumed monotonic premium is a simplification of revenue
management, not a law.

## What was changed

A test asserting that nearer departures are dearer was **removed**, not adjusted.
It asserted a fact about the market rather than about our code, so it failed the
moment reality disagreed — which makes it a bad test, not a bad market. Ordering
and completeness of the profile are still asserted, because those are properties
of the software.

## What must not be said until it is measured

The lead-time premium is **the central empirical claim of this project**, and it
is currently unmeasured. Until a fixed-day comparison across several weeks and
more than one carrier says otherwise:

- do not quote "210%" or any figure derived from the demo generator as though it
  described real fares;
- state the premium as the phenomenon APIx exists to *measure*, not as something
  it has already established.

## How to measure it properly

Collect all six windows daily for at least four weeks, then compare fares for
the **same departure date** observed at different horizons — which is the
comparison the premium is actually about. Comparing different departure dates
observed on the same day, as this first run did, answers a different question.
