"""APIx compliance layer.

Nothing reaches the network without a :class:`ComplianceToken`, and only
:mod:`compliance.gate` can mint one. See ADR-018 and the module docstrings in
``gate.py`` and ``token.py``.

Note what is *not* exported here: ``compliance.token._MINT_KEY``. It is the
private capability that makes the token unforgeable, and re-exporting it - even
for convenience in a test - would quietly dissolve the guarantee.
"""

from __future__ import annotations

from compliance.config import ComplianceConfig
from compliance.errors import (
    ComplianceConfigError,
    ComplianceError,
    ComplianceTokenExpiredError,
    ComplianceTokenForgeryError,
    ComplianceTokenMismatchError,
    ComplianceTokenReusedError,
    UnknownSourceError,
)
from compliance.gate import Allowed, ComplianceGate, GateResult, Refused, evaluate
from compliance.robots import RobotsCache, RobotsDocument, RobotsOutcome
from compliance.token import ComplianceToken, TokenRegistry

__all__ = [
    "Allowed",
    "ComplianceConfig",
    "ComplianceConfigError",
    "ComplianceError",
    "ComplianceGate",
    "ComplianceToken",
    "ComplianceTokenExpiredError",
    "ComplianceTokenForgeryError",
    "ComplianceTokenMismatchError",
    "ComplianceTokenReusedError",
    "GateResult",
    "Refused",
    "RobotsCache",
    "RobotsDocument",
    "RobotsOutcome",
    "TokenRegistry",
    "UnknownSourceError",
    "evaluate",
]
