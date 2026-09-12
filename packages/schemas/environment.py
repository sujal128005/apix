"""Which environment this process is running in, and what that forbids.

A prototype should be forgiving: a fresh checkout works with no configuration,
demo data is one command away, and a missing variable falls back to something
sensible. Every one of those conveniences is a hazard in a system publishing an
official statistic, where a silent fallback means a figure computed from the
wrong database or seeded with development data.

So the environment is explicit, and production removes the conveniences:

    development   local defaults apply; demo tooling available   (default)
    staging       credentials must be explicit; demo tooling available
    production    credentials must be explicit; demo tooling refuses to load

The default is ``development`` deliberately. A misconfigured deployment that
believes it is development will fail to find its database and stop, which is
loud. A misconfigured deployment that believes it is production while running on
a laptop would let demo tooling through, which is silent. Between two failure
modes, choose the one that announces itself.

Set ``APIX_ENV=production`` in the deployed environment. Nothing else enables it.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Final

__all__ = [
    "DEMO_ONLY_MODULES",
    "Environment",
    "current_environment",
    "is_production",
    "require_not_production",
]


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


#: Modules that must never load in production. Importing one is not a
#: configuration mistake to be logged - it is a synthetic-data path inside a
#: system that publishes official figures, and it stops the process.
DEMO_ONLY_MODULES: Final[tuple[str, ...]] = (
    "collector.mock_adapter",
    "scripts.run_demo_pipeline",
)


class ProductionSafetyError(RuntimeError):
    """Something that must not exist in production was reached anyway.

    Raised rather than logged. A warning about synthetic data in a statistical
    production system is a warning nobody reads until after the figure is
    published.
    """


def current_environment() -> Environment:
    """The declared environment. Unrecognised values are a hard error.

    A typo such as ``APIX_ENV=prod`` must not silently resolve to development
    and re-enable every convenience production is meant to remove.
    """
    raw = os.environ.get("APIX_ENV", "").strip().lower()
    if not raw:
        return Environment.DEVELOPMENT
    try:
        return Environment(raw)
    except ValueError as exc:
        permitted = ", ".join(e.value for e in Environment)
        raise ProductionSafetyError(
            f"APIX_ENV={raw!r} is not a recognised environment. Use one of: "
            f"{permitted}. An unrecognised value is refused rather than treated "
            "as development, because a typo would silently restore every "
            "convenience production removes."
        ) from exc


def is_production() -> bool:
    return current_environment() is Environment.PRODUCTION


def requires_explicit_credentials() -> bool:
    """True in staging and production. Local dev defaults apply only in dev."""
    return current_environment() is not Environment.DEVELOPMENT


def require_not_production(what: str) -> None:
    """Refuse to proceed if this is production.

    Called at import time by demo tooling, so the failure happens when the
    module is loaded rather than when it is used - by which point the caller may
    already have a database session open.
    """
    if is_production():
        raise ProductionSafetyError(
            f"{what} cannot be used in production. It exists to exercise the "
            "pipeline with synthetic data, and there must be no path from "
            "synthetic data to a published statistic. If this is reaching "
            "production, the deployment is wrong, not this check."
        )
