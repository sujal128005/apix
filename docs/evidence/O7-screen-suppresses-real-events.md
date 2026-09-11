# The outlier screen suppresses genuine price events

**Measured 11 September 2026.** Follow-up to an independent reviewer's concern
that winsorisation at small *n* "may be actively suppressing the phenomenon you
were built to measure."

The concern is correct, and the problem is worse at n ≥ 5 than below it.

## What was measured

Three scenarios, all of them **real market behaviour, not data errors**.

### A. A market-wide surge (n = 4)

Every fare on the route doubles — a festival week, or a capacity withdrawal.

| | |
|---|---|
| Index reported | **200.000000** |
| Truth | 200.000000 |
| Winsorised pairs | 0 |

**No suppression.** Uniform movement has no outlier relative to the group, so
nothing is touched. Half the reviewer's concern is answered: the screen does not
flatten broad price moves.

### B. A single genuine spike (n = 4, winsorisation path)

Three fares flat, one triples — an ordinary last-seat event.

| | |
|---|---|
| Index with winsorisation | 126.295613 |
| Index without | 131.607401 |
| **Suppression** | **−4.04%** |

The event is dampened but survives.

### C. The same shape at n = 6 (MAD path)

| | |
|---|---|
| Index reported | **100.000000** |
| Pairs rejected | 1 |

**Total suppression.** The stratum reports that *nothing happened* on a day when
one fare tripled. This is the serious case, and it is the common one — six
observations per stratum is the norm in this basket, not the exception.

## Why this happens

The screen cannot distinguish a **data error** from a **real price event**,
because they are statistically identical: a value far from its neighbours.

Outlier screening in price statistics exists to catch errors — a parse failure,
a currency mix-up, a misplaced decimal. It is not meant to smooth genuine
volatility. But a last-seat airfare at 3× the cabin's going rate is not an
error. It is the exact phenomenon a real-time airfare index exists to observe,
and the screen discards it.

## Why this matters more than it appears

The sensitivity analysis (`O6`) found that removing screening entirely moves the
index by **−0.049%** on the current data. So the screen is:

- doing almost nothing to the published number, **and**
- capable of erasing a tripled fare from a stratum completely

That is the worst combination available. A control that changes little and
occasionally deletes the signal is not earning its place.

## Options

**1. Widen k.** Cheap, and wrong for the right reason: it trades one arbitrary
threshold for another, and a sufficiently isolated genuine event is still
rejected at any finite k (see O6).

**2. Remove statistical screening; screen for plausibility instead.** Reject only
what cannot be a real fare — non-positive, absurd magnitudes, currency mismatch —
and let the geometric mean absorb genuine volatility, which O6 shows it already
does. This matches what outlier screening is *for* in price statistics.

**3. Flag rather than reject.** Keep the observation in the index, record it as
extreme, and surface the count on the Data Quality page. Nothing is erased, and
a reader can see how much of a movement came from extreme observations.

## Recommendation

**Option 3, with option 2's plausibility bounds beneath it.**

Errors are rejected on impossibility, not on being unusual. Unusual-but-possible
observations enter the index and are counted, so an operator can see when a
stratum is being driven by one extreme fare. Nothing that could be a real price
is discarded for being surprising.

This is a methodology change and is **not yet implemented**. It needs a new
`methodology_version`, recomputation, and an entry on the Methodology page
explaining why the screen changed.

## Resolved — methodology 1.1.0

Option 3 implemented on 12 September 2026.

**What changed.** Statistically extreme observations stay in the index and are
counted. Only *impossible* relatives are removed — outside 0.01x to 100x, which
is a misplaced decimal or a parse failure rather than a market event. Scenario C
now reports **120.09 with one flagged observation** where 1.0.0 reported
100.000 and no movement at all.

**An unexpected result.** Re-running the sensitivity analysis under 1.1.0:

| Threshold | Mean index | Rejected |
|---|---|---|
| k = 2.5 | 110.2337 | 0 |
| k = 3.0 | 110.2337 | 0 |
| k = 3.5 | 110.2337 | 0 |
| k = 4.0 | 110.2337 | 0 |
| k = 5.0 | 110.2337 | 0 |
| no screening | 110.2337 | 0 |

**The threshold no longer affects the published number at all.** Under 1.0.0,
`k` silently moved the index; the sensitivity analysis existed to measure by how
much. Under 1.1.0 it governs only what is *counted and reported*, so the
question "why 3.5?" stops being a question about the index and becomes a
question about how sensitive the Data Quality page should be.

That is a better place for an arbitrary constant to live. A judge can disagree
with 3.5 without disagreeing with any published figure.

**Both versions remain testable.** `ScreenMode.REJECT` is retained and the 1.0.0
golden values are still asserted, so a methodology revision can never be
confused with a correction.
