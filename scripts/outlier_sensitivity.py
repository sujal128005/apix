#!/usr/bin/env python
"""How much does the outlier rule change the index?

"Why k = 3.5?" is the obvious follow-up to admitting the MAD screen is our own
choice rather than something inherited from CPI, and until now the honest answer
was that we picked a common robust-screening threshold. That is not an answer a
statistician accepts.

This recomputes the index over the stored observations at several thresholds and
with screening disabled entirely, and reports how far the result moves. It turns
a tuning constant into a measured sensitivity.

Two things worth watching in the output:

**If the index barely moves across thresholds**, the choice of k is not load
bearing and the screen is doing little harm - reassuring, though it also means
the screen is doing little work.

**If it moves a great deal**, the screen is a substantive modelling decision and
must be presented as one, because a reader is entitled to know that a different
defensible threshold would have produced a visibly different index.

    .venv/Scripts/python scripts/outlier_sensitivity.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.settings import DbSettings
from index_engine.jevons import jevons_short
from pipeline.normalise import ObservedQuote, StratumKey, build_matched_pairs
from schemas.models.derived import NormalisedQuote

# A very large k disables rejection in practice without a separate code path -
# the same screen runs, nothing exceeds the threshold.
THRESHOLDS: list[tuple[str, Decimal]] = [
    ("2.5", Decimal("2.5")),
    ("3.0", Decimal("3.0")),
    ("3.5 (in force)", Decimal("3.5")),
    ("4.0", Decimal("4.0")),
    ("5.0", Decimal("5.0")),
    ("no screening", Decimal("1000000")),
]


def load(session) -> dict[date, dict[StratumKey, list[ObservedQuote]]]:
    rows = session.execute(
        sa.select(NormalisedQuote).order_by(NormalisedQuote.collected_date)
    ).scalars().all()
    by_day: dict[date, dict[StratumKey, list[ObservedQuote]]] = defaultdict(dict)
    for row in rows:
        key = StratumKey(
            route_id=row.route_id, bucket_id=row.bucket_id, collected_date=row.collected_date
        )
        by_day[row.collected_date].setdefault(key, []).append(
            ObservedQuote(
                stratum=key,
                pair_key=f"{row.carrier}|{row.flight_no or '?'}|{row.fare_brand or '?'}",
                total_fare=row.total_fare,
                provenance=row.provenance,
            )
        )
    return dict(by_day)


def run(
    by_day: dict[date, dict[StratumKey, list[ObservedQuote]]], k: Decimal
) -> tuple[Decimal | None, int, int, int]:
    """Chain every stratum through the whole window at one threshold.

    Returns (mean final stratum index, strata computed, pairs rejected,
    strata that became insufficient because screening removed too much).
    """
    days = sorted(by_day)
    running: dict[tuple, Decimal] = {}
    rejected = insufficient = 0

    for i, day in enumerate(days):
        if i == 0:
            for key in by_day[day]:
                running[(key.route_id, key.bucket_id)] = Decimal("100")
            continue

        previous = by_day[days[i - 1]]
        for key, quotes in by_day[day].items():
            prior_key = StratumKey(
                route_id=key.route_id, bucket_id=key.bucket_id, collected_date=days[i - 1]
            )
            pairs, _, _ = build_matched_pairs(previous.get(prior_key, []), quotes)
            prev_value = running.get((key.route_id, key.bucket_id))
            if prev_value is None:
                running[(key.route_id, key.bucket_id)] = Decimal("100")
                continue
            result = jevons_short(pairs, prev_value, k=k)
            rejected += result.rejected
            if result.index_value is None:
                insufficient += 1
            else:
                running[(key.route_id, key.bucket_id)] = result.index_value

    if not running:
        return None, 0, rejected, insufficient
    mean = sum(running.values(), Decimal(0)) / len(running)
    return mean.quantize(Decimal("0.0001")), len(running), rejected, insufficient


def main() -> int:
    engine = sa.create_engine(DbSettings.from_env().app_url(), future=True)
    with sessionmaker(bind=engine)() as session:
        by_day = load(session)

    if not by_day:
        print("No observations. Run scripts/run_demo_pipeline.py first.")
        return 1

    print(f"Outlier sensitivity — {len(by_day)} day(s) of observations\n")
    header = (
        f"{'threshold':>16}  {'mean index':>12}  {'strata':>7}"
        f"  {'rejected':>9}  {'insufficient':>12}"
    )
    print(header)
    print("-" * 66)

    baseline: Decimal | None = None
    for label, k in THRESHOLDS:
        mean, strata, rejected, insufficient = run(by_day, k)
        if "in force" in label:
            baseline = mean
        print(f"{label:>16}  {mean!s:>12}  {strata:>7}  {rejected:>9}  {insufficient:>12}")

    print()
    if baseline:
        for label, k in THRESHOLDS:
            mean, *_ = run(by_day, k)
            if mean is None or "in force" in label:
                continue
            drift = (mean - baseline) / baseline * 100
            print(f"  {label:>16}: {drift:+.3f}% against the threshold in force")

    print(
        "\nRead this as: how much of the published index is the outlier rule's doing.\n"
        "A small spread means k is not load bearing. A large one means the screen is\n"
        "a substantive modelling choice and must be presented as one."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
