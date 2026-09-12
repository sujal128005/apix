"""The release gate.

An official statistic is not published by a scheduler finishing successfully. It
is released by a named person, against a calendar, and once released it does not
change silently.

    computed  ->  PENDING  ->  APPROVED  ->  PUBLISHED
                                 |
                                 +-------->  WITHDRAWN

Four rules, each enforced rather than documented:

**Approval is attributed.** A figure released under no one's name is not an
approved figure. The database refuses an approval without an approver.

**Publication follows approval.** Nothing reaches the public API from PENDING.
The default query path returns published figures only, so forgetting to filter
shows nothing rather than showing something unapproved.

**A revision explains itself.** When a corrected figure supersedes a published
one, both are kept and the reason is required. "The number changed" is not a
reason a reader can evaluate.

**A withdrawal is a publication.** Retracting a figure is itself an act of
disclosure: the row stays, the state changes, and the reason is recorded. A
statistic that quietly disappears is worse than one that is publicly corrected.

The immutability of ``index_observation`` is what makes this trustworthy. The
figure cannot change while its status does, so "what was published on the 14th"
remains answerable after a revision on the 20th.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from schemas.enums import IndexLevel
from schemas.models.indexing import IndexObservation, Publication

__all__ = [
    "PublicationError",
    "PublicationState",
    "PublishedFigure",
    "approve",
    "current_published",
    "publish",
    "revise",
    "submit_for_approval",
    "withdraw",
]


class PublicationState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class PublicationError(RuntimeError):
    """An invalid transition in the release lifecycle.

    Raised rather than returned. Publishing an unapproved figure, or approving
    one twice, is not a condition to handle further up - it is a caller doing
    something that must not happen.
    """


@dataclass(frozen=True, slots=True)
class PublishedFigure:
    """A figure as released, with the provenance a reader needs to cite it."""

    obs_date: date
    level: str
    index_value: Decimal
    revision: int
    published_at: datetime
    approved_by: str
    methodology_version_id: UUID
    is_revised: bool
    revision_reason: str | None


def submit_for_approval(
    session: Session, observation: IndexObservation
) -> Publication:
    """Register a computed figure as pending. It is not public at this point."""
    existing = session.execute(
        sa.select(Publication).where(
            Publication.index_observation_id == observation.id
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise PublicationError(
            f"observation {observation.id} is already in the release lifecycle "
            f"(state {existing.state})"
        )

    record = Publication(index_observation_id=observation.id, state=PublicationState.PENDING)
    session.add(record)
    session.flush()
    return record


def approve(
    session: Session,
    record: Publication,
    *,
    approved_by: str,
    scheduled_release_at: datetime | None = None,
) -> Publication:
    """Sign a figure off for release.

    ``approved_by`` is required and is not defaulted. An automated approver
    would reproduce exactly the situation this gate exists to prevent: a
    statistic published because a job succeeded.
    """
    if not approved_by.strip():
        raise PublicationError(
            "approved_by is required. An official statistic is released by a "
            "named person; a figure approved by nobody is not approved."
        )
    if record.state != PublicationState.PENDING:
        raise PublicationError(
            f"only a PENDING figure can be approved; this one is {record.state}"
        )

    record.state = PublicationState.APPROVED
    record.approved_by = approved_by.strip()
    record.approved_at = datetime.now(UTC)
    record.scheduled_release_at = scheduled_release_at
    session.flush()
    return record


def publish(session: Session, record: Publication, *, now: datetime | None = None) -> Publication:
    """Make an approved figure public.

    Refuses before the scheduled release time. A publication calendar that can
    be jumped is not a calendar, and early release of a statistic used for
    monetary policy is a disclosure problem rather than a scheduling one.
    """
    now = now or datetime.now(UTC)
    if record.state != PublicationState.APPROVED:
        raise PublicationError(
            f"only an APPROVED figure can be published; this one is {record.state}"
        )
    if record.scheduled_release_at is not None and now < record.scheduled_release_at:
        raise PublicationError(
            f"scheduled for release at {record.scheduled_release_at.isoformat()}; "
            "publishing early would breach the release calendar"
        )

    record.state = PublicationState.PUBLISHED
    record.published_at = now
    session.flush()
    return record


def revise(
    session: Session,
    superseded: Publication,
    corrected: IndexObservation,
    *,
    reason: str,
    approved_by: str,
) -> Publication:
    """Issue a corrected figure superseding a published one.

    The superseded row is **not** modified. It stays PUBLISHED with its original
    value and timestamp, so the question "what was published on the 14th?"
    remains answerable after a correction on the 20th. The new row records what
    it supersedes and why.
    """
    if not reason.strip():
        raise PublicationError(
            "a revision must state its reason. 'The number changed' is not "
            "something a reader can evaluate."
        )
    if superseded.state != PublicationState.PUBLISHED:
        raise PublicationError(
            f"only a PUBLISHED figure can be revised; this one is {superseded.state}"
        )

    record = Publication(
        index_observation_id=corrected.id,
        state=PublicationState.APPROVED,
        approved_by=approved_by.strip(),
        approved_at=datetime.now(UTC),
        supersedes_id=superseded.index_observation_id,
        revision_reason=reason.strip(),
    )
    session.add(record)
    session.flush()
    return record


def withdraw(session: Session, record: Publication, *, reason: str) -> Publication:
    """Retract a published figure, publicly and with a reason.

    The row is never deleted. A statistic that quietly disappears is worse than
    one that is openly corrected: a reader who cited it deserves to find out
    what happened to it.
    """
    if not reason.strip():
        raise PublicationError("a withdrawal must state its reason")
    if record.state != PublicationState.PUBLISHED:
        raise PublicationError(
            f"only a PUBLISHED figure can be withdrawn; this one is {record.state}"
        )

    record.state = PublicationState.WITHDRAWN
    record.withdrawn_reason = reason.strip()
    session.flush()
    return record


def current_published(
    session: Session,
    *,
    level: str = IndexLevel.HEADLINE,
    ref_id: UUID | None = None,
    limit: int = 100,
) -> list[PublishedFigure]:
    """Published figures, most recent first, superseded revisions excluded.

    This is the only query the public API should use. Filtering on state here
    rather than at each call site means a forgotten filter shows *nothing*
    rather than showing something unapproved.
    """
    superseded = sa.select(Publication.supersedes_id).where(
        Publication.supersedes_id.is_not(None)
    )

    statement = (
        sa.select(IndexObservation, Publication)
        .join(Publication, Publication.index_observation_id == IndexObservation.id)
        .where(Publication.state == PublicationState.PUBLISHED)
        .where(IndexObservation.level == level)
        .where(IndexObservation.id.not_in(superseded))
        .order_by(IndexObservation.obs_date.desc())
        .limit(limit)
    )
    if ref_id is not None:
        statement = statement.where(IndexObservation.ref_id == ref_id)

    return [
        PublishedFigure(
            obs_date=obs.obs_date,
            level=obs.level,
            index_value=obs.index_value,
            revision=obs.revision,
            published_at=pub.published_at or pub.created_at,
            approved_by=pub.approved_by or "unattributed",
            methodology_version_id=obs.methodology_version_id,
            is_revised=pub.supersedes_id is not None,
            revision_reason=pub.revision_reason,
        )
        for obs, pub in session.execute(statement).all()
    ]
