"""The release gate.

Every test here is about a refusal or an act of disclosure. An official
statistic that can be published by a job finishing successfully, changed
silently, or withdrawn without explanation is not an official statistic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from pipeline.publication import (
    PublicationError,
    PublicationState,
    approve,
    current_published,
    publish,
    revise,
    submit_for_approval,
    withdraw,
)
from schemas.enums import IndexLevel
from schemas.models.indexing import IndexObservation
from schemas.models.versioning import MethodologyVersion, WeightSetVersion
from tests.support.builders import SeedRefs

DAY = date(2026, 9, 15)


def observation(
    session: Session, *, value: str = "110.5", revision: int = 1
) -> IndexObservation:
    methodology = session.execute(sa.select(MethodologyVersion).limit(1)).scalar_one()
    weights = session.execute(sa.select(WeightSetVersion).limit(1)).scalar_one_or_none()
    if weights is None:
        weights = WeightSetVersion(version=f"t-{revision}", effective_from=DAY, source_note="test")
        session.add(weights)
        session.flush()

    row = IndexObservation(
        obs_date=DAY,
        level=IndexLevel.HEADLINE,
        ref_id=None,
        bucket_id=None,
        index_value=Decimal(value),
        prev_index_value=Decimal("100"),
        revision=revision,
        methodology_version_id=methodology.id,
        weight_set_version_id=weights.id,
        input_quote_count=120,
        excluded_count=0,
        imputed_count=0,
        routes_in_basket=20,
        input_hash=f"hash-{revision}",
        computed_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


# -- the lifecycle ---------------------------------------------------------


def test_a_computed_figure_starts_unpublished(app_session: Session, refs: SeedRefs) -> None:
    """Computing is not publishing."""
    record = submit_for_approval(app_session, observation(app_session))
    assert record.state == PublicationState.PENDING
    assert current_published(app_session) == []


def test_publication_requires_approval_first(app_session: Session, refs: SeedRefs) -> None:
    record = submit_for_approval(app_session, observation(app_session))
    with pytest.raises(PublicationError, match="only an APPROVED figure"):
        publish(app_session, record)


def test_approval_must_be_attributed(app_session: Session, refs: SeedRefs) -> None:
    """A figure approved by nobody is not approved.

    An automated approver would reproduce exactly what this gate prevents: a
    statistic published because a job succeeded.
    """
    record = submit_for_approval(app_session, observation(app_session))
    with pytest.raises(PublicationError, match="named person"):
        approve(app_session, record, approved_by="   ")


def test_an_approved_figure_publishes_and_becomes_visible(
    app_session: Session, refs: SeedRefs
) -> None:
    record = submit_for_approval(app_session, observation(app_session))
    approve(app_session, record, approved_by="Director, Price Statistics")
    publish(app_session, record)

    figures = current_published(app_session)
    assert len(figures) == 1
    assert figures[0].index_value == Decimal("110.500000")
    assert figures[0].approved_by == "Director, Price Statistics"


def test_a_figure_cannot_be_approved_twice(app_session: Session, refs: SeedRefs) -> None:
    record = submit_for_approval(app_session, observation(app_session))
    approve(app_session, record, approved_by="Director")
    with pytest.raises(PublicationError, match="only a PENDING figure"):
        approve(app_session, record, approved_by="Someone Else")


# -- the release calendar --------------------------------------------------


def test_a_figure_cannot_be_released_before_its_scheduled_time(
    app_session: Session, refs: SeedRefs
) -> None:
    """A publication calendar that can be jumped is not a calendar.

    Early release of a statistic used for monetary policy is a disclosure
    problem, not a scheduling inconvenience.
    """
    record = submit_for_approval(app_session, observation(app_session))
    release_at = datetime.now(UTC) + timedelta(hours=6)
    approve(app_session, record, approved_by="Director", scheduled_release_at=release_at)

    with pytest.raises(PublicationError, match="release calendar"):
        publish(app_session, record)

    publish(app_session, record, now=release_at + timedelta(seconds=1))
    assert record.state == PublicationState.PUBLISHED


# -- revisions -------------------------------------------------------------


def test_a_revision_keeps_the_original_figure(app_session: Session, refs: SeedRefs) -> None:
    """The question "what was published on the 14th?" must stay answerable.

    The superseded row is not modified: it keeps its value, its timestamp and
    its PUBLISHED state. Only the reader's *current* view changes.
    """
    first = observation(app_session, value="110.5", revision=1)
    original = submit_for_approval(app_session, first)
    approve(app_session, original, approved_by="Director")
    publish(app_session, original)
    original_published_at = original.published_at

    corrected = observation(app_session, value="112.9", revision=2)
    revision = revise(
        app_session, original, corrected,
        reason="A late fare correction was received from the source for 15 September.",
        approved_by="Director",
    )
    publish(app_session, revision)

    assert original.state == PublicationState.PUBLISHED, "the original is not altered"
    assert original.published_at == original_published_at
    assert first.index_value == Decimal("110.500000")

    current = current_published(app_session)
    assert len(current) == 1
    assert current[0].index_value == Decimal("112.900000")
    assert current[0].revision == 2
    assert current[0].is_revised is True
    assert "late fare correction" in (current[0].revision_reason or "")


def test_a_revision_must_state_its_reason(app_session: Session, refs: SeedRefs) -> None:
    first = observation(app_session, revision=1)
    original = submit_for_approval(app_session, first)
    approve(app_session, original, approved_by="Director")
    publish(app_session, original)

    with pytest.raises(PublicationError, match="must state its reason"):
        revise(
            app_session, original, observation(app_session, revision=2),
            reason="  ", approved_by="Director",
        )


def test_both_revisions_are_retained_in_the_database(
    app_session: Session, refs: SeedRefs
) -> None:
    """Nothing is edited and nothing is lost."""
    first = observation(app_session, value="110.5", revision=1)
    original = submit_for_approval(app_session, first)
    approve(app_session, original, approved_by="Director")
    publish(app_session, original)
    revise(
        app_session, original, observation(app_session, value="112.9", revision=2),
        reason="late correction", approved_by="Director",
    )

    rows = app_session.execute(
        sa.select(IndexObservation).where(IndexObservation.obs_date == DAY)
    ).scalars().all()
    assert {r.revision for r in rows} == {1, 2}
    assert {r.index_value for r in rows} == {Decimal("110.500000"), Decimal("112.900000")}


# -- withdrawal ------------------------------------------------------------


def test_a_withdrawal_is_recorded_not_deleted(app_session: Session, refs: SeedRefs) -> None:
    """A statistic that quietly disappears is worse than one openly corrected.

    A reader who cited it deserves to find out what happened to it.
    """
    record = submit_for_approval(app_session, observation(app_session))
    approve(app_session, record, approved_by="Director")
    publish(app_session, record)

    withdraw(app_session, record, reason="Collection error affecting six routes.")

    assert record.state == PublicationState.WITHDRAWN
    assert "Collection error" in (record.withdrawn_reason or "")
    assert current_published(app_session) == [], "a withdrawn figure is not current"

    still_there = app_session.execute(
        sa.select(sa.func.count()).select_from(IndexObservation)
    ).scalar_one()
    assert still_there >= 1, "the observation itself is never deleted"


def test_a_withdrawal_must_state_its_reason(app_session: Session, refs: SeedRefs) -> None:
    record = submit_for_approval(app_session, observation(app_session))
    approve(app_session, record, approved_by="Director")
    publish(app_session, record)
    with pytest.raises(PublicationError, match="must state its reason"):
        withdraw(app_session, record, reason="")


# -- the safe default ------------------------------------------------------


def test_unapproved_figures_are_invisible_by_default(
    app_session: Session, refs: SeedRefs
) -> None:
    """A forgotten filter must show nothing, not something unapproved."""
    submit_for_approval(app_session, observation(app_session))
    assert current_published(app_session) == []


def test_a_figure_cannot_enter_the_lifecycle_twice(
    app_session: Session, refs: SeedRefs
) -> None:
    row = observation(app_session)
    submit_for_approval(app_session, row)
    with pytest.raises(PublicationError, match="already in the release lifecycle"):
        submit_for_approval(app_session, row)
