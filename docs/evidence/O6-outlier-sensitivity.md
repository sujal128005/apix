# Outlier screening — sensitivity analysis

**Run 11 September 2026 · 21 days of observations · `scripts/outlier_sensitivity.py`**

Written in response to an independent review that asked the obvious question:
*why k = 3.5?* Until now the answer was that it is a common robust-screening
threshold, which is not an answer.

## Result

| Threshold | Mean stratum index | Pairs rejected | Strata made insufficient |
|---|---|---|---|
| k = 2.5 | 110.2337 | 1,069 | 0 |
| k = 3.0 | 110.2337 | 760 | 0 |
| **k = 3.5 (in force)** | **110.2337** | **591** | **0** |
| k = 4.0 | 110.2337 | 486 | 0 |
| k = 5.0 | 110.2337 | 362 | 0 |
| no screening | 110.1795 | 191 | 0 |

Against the threshold in force: **0.000%** difference at every other threshold,
and **−0.049%** with screening effectively disabled.

## What this says

**The threshold is not load bearing on this data.** Between k = 2.5 and k = 5.0
the index does not move at the reported precision, even though the number of
rejected pairs varies by a factor of three. The geometric mean is already doing
the work the screen was added to do — which is the formal reason MoSPI moved to
GM at the elementary level, now visible empirically.

That is reassuring about the choice of k and slightly deflating about the screen:
it is removing observations without changing the answer.

**The screen is therefore an experimental estimator choice with a measured, small
effect** — not a CPI methodological inheritance, and not a hidden lever moving
the published number.

## A real defect this analysis exposed — now fixed

Investigating the 191 rejections that persisted at k = 1,000,000 turned up a
worse bug than the one being looked for, and in the opposite direction.

**When MAD was exactly zero, the screen stopped working entirely.**

Carriers on a route commonly move by the same factor, which makes the median
absolute deviation exactly zero. The original code returned every pair
unscreened in that case, on the reasoning that zero dispersion meant there was
nothing to screen. That reasoning is backwards. Demonstrated:

    A  5000 -> 5100     relative 1.020
    B  6000 -> 6120     relative 1.020
    C  7000 -> 7140     relative 1.020
    D  8000 -> 8160     relative 1.020
    E  5000 -> 21000    relative 4.200   <- survived at every threshold

A 4x outlier sat beside four identical relatives and was **kept at k = 3.5**.
The screen silently failed in precisely the case it existed for.

**Fixed** by falling back to mean absolute deviation where MAD is zero —
Iglewicz and Hoaglin's standard remedy, scaled by 1.253314 (the normal
consistency constant for meanAD, against 1.4826 for MAD). Taken from the
robust-statistics literature rather than picked, which was the point of running
this analysis at all. Four tests now cover it: the outlier is caught, genuinely
identical relatives are left alone, a normal spread is untouched, and the
fallback still respects the threshold rather than rejecting unconditionally.

An independent reviewer predicted this class of problem — "MAD can be zero or
nearly zero in discrete or highly concentrated samples" — before the analysis
was run.

## What the 191 rejections actually were, and why they are not a defect

Not a bug: the definition of a modified z-score.

As dispersion approaches zero, the scale term approaches zero and the score
diverges. An outlier in a stratum with near-zero dispersion genuinely is an
unbounded number of MADs from the median, so it exceeds any finite k. Measured:

    dispersion small but non-zero, one outlier present
      k = 3.5        rejected 1
      k = 1,000      rejected 1
      k = 1,000,000  rejected 0

The screen behaves correctly; "no screening" cannot be simulated by raising k,
because a sufficiently isolated point is unboundedly far out on any scale-based
measure. That is a property of the estimator, worth understanding rather than
engineering away.

## Caveats

**This is synthetic data.** The demo generator inserts a deliberate 4.2× anomaly
in roughly one quote per 180. Real airfare distributions may be far heavier in
the right tail, and the insensitivity found here may not survive contact with
them. The analysis must be re-run on live observations before k = 3.5 is
described as validated.

**The sensitivity figures above pre-date the MAD fix** and are unchanged by it:
the demo generator's brand premiums mean most strata have non-zero dispersion,
so the degenerate path is rarely taken here. On live data — where carriers
matching each other's fares exactly is ordinary — the fix will matter
considerably more than these numbers suggest.

**Small-n winsorisation is not tested by this.** The concern that winsorising at
n < 5 may suppress genuine market movement — a 300% relative move in airfare can
be entirely real — remains open. Every stratum here has six observations.
