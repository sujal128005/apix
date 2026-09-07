"""Exceptions raised by the compliance layer.

A refused fetch is **not** an exception. The gate returns a ``Refused`` result as
data, because a source whose robots.txt disallows collection is the system
working correctly, not an error condition.

Everything here signals a *programming* fault: an attempt to forge, reuse,
misuse or outlive a capability token, or a configuration that would make the
crawler less conservative than its own floor allows.
"""

from __future__ import annotations


class ComplianceError(Exception):
    """Base class for every compliance-layer fault."""


class ComplianceTokenForgeryError(ComplianceError):
    """A ComplianceToken was constructed outside the gate.

    The token is a capability: holding one is proof that the gate approved this
    exact fetch. Constructing one directly would forge that proof, so the
    constructor refuses any caller that cannot present the gate's private mint
    key.
    """


class ComplianceTokenReusedError(ComplianceError):
    """A ComplianceToken was presented more than once.

    Tokens authorise a single fetch. Reuse would let one gate evaluation
    authorise an unbounded number of requests, defeating the crawl-delay and
    daily-budget checks.
    """


class ComplianceTokenExpiredError(ComplianceError):
    """A ComplianceToken was presented after its TTL elapsed.

    An approval is a statement about conditions at a moment in time. robots.txt
    may have changed; the crawl delay has certainly moved on. Past the TTL the
    caller must return to the gate.
    """


class ComplianceTokenMismatchError(ComplianceError):
    """A ComplianceToken was presented for a different source or path.

    Tokens are bound to the exact fetch they authorise. Using one issued for
    ``/a`` to fetch ``/b`` would let a permitted path launder an unpermitted
    one.
    """


class ComplianceConfigError(ComplianceError):
    """Configuration would make the crawler less conservative than its floor.

    Settings may be overridden only in the direction of greater restraint. An
    override that crawls faster, or more often, than the built-in floor is
    rejected at load time rather than honoured.
    """


class UnknownSourceError(ComplianceError):
    """A gate evaluation named a source_id that does not exist.

    This is a caller fault, not a compliance outcome. Refusals are returned as
    data because they are decisions *about a source*; an unknown id names no
    source, so there is nothing to decide and nothing to attribute an audit row
    to. The compliance_decision foreign key says the same thing in SQL, and it
    is right: a decision that cannot be attributed is not evidence.
    """
