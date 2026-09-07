"""Compliance configuration, read from the environment.

Every value here can be overridden, but **only in the direction that makes the
crawler more conservative**. The crawl delay may be raised and never lowered;
the daily budget may be lowered and never raised. An override that would make
APIx crawl faster or more often than its own floor raises at load time.

That asymmetry is deliberate. A setting that can be relaxed under deadline
pressure is not a safeguard, it is a suggestion. The floors below are the
promise the project makes to the sites it collects from, and no environment
variable can withdraw it.

The user agent identifies APIx and carries a contact URL. ``APIX_CONTACT_URL``
has no default: if it is unset the gate refuses every fetch. Crawling
anonymously is not a mode this system supports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

from compliance.errors import ComplianceConfigError

# --------------------------------------------------------------------------
# Floors. These are not defaults - they are limits on how far a default may be
# moved. See the module docstring.
# --------------------------------------------------------------------------
MIN_CRAWL_DELAY_SECONDS: Final[float] = 5.0
MAX_DAILY_REQUEST_BUDGET: Final[int] = 200

USER_AGENT_TEMPLATE: Final[str] = "APIx-Research/0.1 (+{contact}; MoSPI SIH 2026 PS 26056)"


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ComplianceConfigError(f"{key} must be a number, got {raw!r}") from exc


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ComplianceConfigError(f"{key} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True, slots=True)
class ComplianceConfig:
    """Settings for the gate, the robots cache and the capability token."""

    token_ttl_seconds: int
    robots_cache_ttl_hours: int
    robots_stale_max_days: int
    default_crawl_delay: float
    daily_request_budget: int
    robots_fetch_timeout: float
    contact_url: str

    @classmethod
    def from_env(cls) -> ComplianceConfig:
        """Build from the environment, refusing any override that relaxes a floor."""
        default_crawl_delay = _env_float("APIX_DEFAULT_CRAWL_DELAY", MIN_CRAWL_DELAY_SECONDS)
        if default_crawl_delay < MIN_CRAWL_DELAY_SECONDS:
            raise ComplianceConfigError(
                f"APIX_DEFAULT_CRAWL_DELAY={default_crawl_delay} is below the "
                f"{MIN_CRAWL_DELAY_SECONDS}s floor. The delay may be raised, never lowered."
            )

        daily_request_budget = _env_int("APIX_DAILY_REQUEST_BUDGET", MAX_DAILY_REQUEST_BUDGET)
        if daily_request_budget > MAX_DAILY_REQUEST_BUDGET:
            raise ComplianceConfigError(
                f"APIX_DAILY_REQUEST_BUDGET={daily_request_budget} exceeds the "
                f"{MAX_DAILY_REQUEST_BUDGET} ceiling. The budget may be lowered, never raised."
            )
        if daily_request_budget < 0:
            raise ComplianceConfigError("APIX_DAILY_REQUEST_BUDGET cannot be negative.")

        return cls(
            token_ttl_seconds=_env_int("APIX_TOKEN_TTL_SECONDS", 300),
            robots_cache_ttl_hours=_env_int("APIX_ROBOTS_CACHE_TTL_HOURS", 24),
            robots_stale_max_days=_env_int("APIX_ROBOTS_STALE_MAX_DAYS", 7),
            default_crawl_delay=default_crawl_delay,
            daily_request_budget=daily_request_budget,
            robots_fetch_timeout=_env_float("APIX_ROBOTS_FETCH_TIMEOUT", 10.0),
            contact_url=os.environ.get("APIX_CONTACT_URL", "").strip(),
        )

    @property
    def user_agent(self) -> str:
        """The identifying user agent, or a placeholder when no contact is configured.

        The placeholder is never sent: the gate refuses before any fetch when
        ``contact_url`` is empty. It exists so that a refusal can still record
        *something* in the audit row.
        """
        contact = self.contact_url or "UNCONFIGURED"
        return USER_AGENT_TEMPLATE.format(contact=contact)

    @property
    def has_contact(self) -> bool:
        return bool(self.contact_url)

    def effective_crawl_delay(self, declared: float | None) -> float:
        """Reconcile a site's declared crawl-delay with our own floor.

        A site asking us to wait *longer* is obeyed. A site permitting a shorter
        delay - or declaring none - still gets our floor. Permission to crawl
        faster is not an obligation to.
        """
        if declared is None:
            return self.default_crawl_delay
        return max(float(declared), self.default_crawl_delay)
