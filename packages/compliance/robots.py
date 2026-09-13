"""robots.txt retrieval, caching and evaluation.

Parsing uses **protego**, the parser Scrapy uses. Python's stdlib
``urllib.robotparser`` is not used anywhere: it resolves ``Allow``/``Disallow``
precedence by rule order rather than by specificity, so a broad ``Disallow``
followed by a narrow ``Allow`` is evaluated wrongly. On a project whose whole
claim is that it respects site directives, using a parser that misreads them
would be self-defeating.

**Everything here fails closed.** When robots.txt cannot be retrieved, cannot be
parsed, or cannot be trusted, the answer is "do not crawl". The only case that
opens access is an explicit 404 or 410, which RFC 9309 defines as meaning no
restrictions exist. A 403 on robots.txt itself is treated as a full disallow:
if a site will not show us its rules, we do not guess at them.

Snapshots of every fetch are written to ``data/reference/robots-snapshots/`` and
hashed, so a reviewer can see exactly which bytes a past decision rested on.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import urlparse

from protego import Protego

from compliance.config import ComplianceConfig

__all__ = [
    "SNAPSHOT_ROOT",
    "HttpxRobotsFetcher",
    "RobotsCache",
    "RobotsDocument",
    "RobotsFetcher",
    "RobotsOutcome",
]

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SNAPSHOT_ROOT: Final[Path] = REPO_ROOT / "data" / "reference" / "robots-snapshots"


class RobotsOutcome:
    """Why a robots document is in the state it is in. Values are audit strings."""

    OK = "OK"
    ABSENT = "ABSENT"  # 404/410 - no restrictions exist
    FORBIDDEN = "FORBIDDEN"  # 401/403 on robots.txt itself
    UNAVAILABLE = "UNAVAILABLE"  # 5xx, timeout, connection error
    MALFORMED = "MALFORMED"  # retrieved but unparseable
    STALE = "STALE"  # served from a cache older than the TTL


@dataclass(frozen=True, slots=True)
class RobotsDocument:
    """A retrieved robots.txt, plus the verdict machinery for one user agent."""

    source_code: str
    base_url: str
    outcome: str
    body: str | None
    sha256: str | None
    fetched_at: datetime
    http_status: int | None
    snapshot_path: str | None

    @property
    def permits_anything(self) -> bool:
        """False whenever the document cannot be trusted. Fail closed."""
        return self.outcome in (RobotsOutcome.OK, RobotsOutcome.ABSENT, RobotsOutcome.STALE)

    def allows(self, path: str, user_agent: str) -> tuple[bool, str | None]:
        """Whether ``path`` may be fetched, and which rule decided it.

        Malformed full-URL Disallow rules are honoured by intent before the
        parser is consulted - see :func:`malformed_disallow_paths`.
        """
        """Decide whether ``path`` may be fetched, and name the rule that decided it.

        Returns ``(allowed, matched_rule)``. ``matched_rule`` is a short audit
        string recorded on the compliance_decision row so a reviewer can see the
        reason, not just the verdict.
        """
        if self.outcome == RobotsOutcome.ABSENT:
            return True, "no robots.txt published: no restrictions to apply"
        if self.outcome == RobotsOutcome.FORBIDDEN:
            return False, "robots.txt returned 401/403: rules unverifiable, refusing"
        if self.outcome == RobotsOutcome.UNAVAILABLE:
            return False, "robots.txt unreachable: refusing until it can be read"
        if self.outcome == RobotsOutcome.MALFORMED:
            return False, "robots.txt unparseable: refusing rather than guessing"

        if self.body is None:
            return False, "no robots.txt body available: refusing"

        for intended in malformed_disallow_paths(self.body):
            if path == intended or path.startswith(intended.rstrip("/") + "/"):
                return False, (
                    f"disallowed by intent: robots.txt contains a malformed rule "
                    f"for {intended!r} written as a full URL. A strict parser "
                    "ignores it; we do not exploit the mistake."
                )

        try:
            parser = Protego.parse(self.body)
        except Exception:
            return False, "robots.txt failed to parse: refusing rather than guessing"

        target = path if path.startswith("http") else f"{self.base_url.rstrip('/')}{path}"
        allowed = bool(parser.can_fetch(target, user_agent))
        if allowed:
            note = "allowed by robots.txt"
            if self.outcome == RobotsOutcome.STALE:
                note += " (from a stale cached copy)"
            return True, note
        return False, f"disallowed by robots.txt for {user_agent.split('/')[0]}"

    def crawl_delay(self, user_agent: str) -> float | None:
        """The site's declared crawl-delay, if any. The caller applies our floor."""
        if self.body is None or self.outcome not in (RobotsOutcome.OK, RobotsOutcome.STALE):
            return None
        try:
            declared = Protego.parse(self.body).crawl_delay(user_agent)
        except Exception:
            return None
        return float(declared) if declared is not None else None


class RobotsFetcher(Protocol):
    """Transport for robots.txt. Swapped for a stub in tests; no network there."""

    def fetch(
        self, base_url: str, *, user_agent: str, timeout: float
    ) -> tuple[int | None, str | None]:
        """Return ``(http_status, body)``. Status is None for a transport failure."""
        ...


class HttpxRobotsFetcher:
    """The real transport. Certificate verification stays on (ADR-016)."""

    def fetch(
        self, base_url: str, *, user_agent: str, timeout: float
    ) -> tuple[int | None, str | None]:
        import httpx

        url = f"{base_url.rstrip('/')}/robots.txt"
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                max_redirects=3,
                verify=True,  # ADR-016: certificate verification is never disabled
            ) as client:
                response = client.get(url, headers={"User-Agent": user_agent})
        except Exception:
            return None, None
        return response.status_code, response.text


def _write_snapshot(source_code: str, body: str, fetched_at: datetime) -> str:
    """Persist the exact bytes a decision rested on."""
    directory = SNAPSHOT_ROOT / source_code
    directory.mkdir(parents=True, exist_ok=True)
    stamp = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{stamp}.txt"
    path.write_text(body, encoding="utf-8")
    return str(path.relative_to(REPO_ROOT))


def malformed_disallow_paths(body: str | None) -> tuple[str, ...]:
    """Disallow rules written as full URLs rather than paths.

    RFC 9309 says a Disallow value is a path. A site that writes

        Disallow: https://www.example.com/api/v1

    has expressed an unmistakable intention to exclude ``/api/v1``, and a strict
    parser honours none of it: the value is read as a path beginning ``https:``,
    which matches nothing, so the rule silently permits exactly what it was
    written to forbid.

    SpiceJet's robots.txt does this three times - ``/api/v1``, ``/public/`` and
    ``/externalBooking``.

    Collecting from those paths because someone typed a URL where a path belonged
    is not compliance. It is finding a loophole in a request not to crawl, and
    for a statistic published under a ministry's name it would be indefensible.
    So the paths are extracted and treated as disallowed regardless of what the
    parser makes of them.
    """
    if not body:
        return ()

    paths: list[str] = []
    for line in body.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped.lower().startswith("disallow:"):
            continue
        value = stripped.split(":", 1)[1].strip()
        if not value.lower().startswith(("http://", "https://")):
            continue
        # Take the path component of the URL that was written.
        remainder = value.split("://", 1)[1]
        path = "/" + remainder.split("/", 1)[1] if "/" in remainder else "/"
        paths.append(path)
    return tuple(paths)


def _looks_like_html(body: str | None) -> bool:
    """True when a body is a web page rather than a robots.txt.

    Single-page applications commonly answer every unmatched path with their
    index document and HTTP 200. ``api.mospi.gov.in/robots.txt`` does exactly
    that, returning a swagger-ui page. Parsing it as robots.txt yields no
    directives and therefore allows everything - the right outcome by accident,
    but the audit row would then read "allowed by robots.txt" for a site that
    publishes none. A compliance record that states something untrue is worse
    than one that says "absent".
    """
    if not body:
        return False
    head = body.lstrip()[:400].lower()
    return head.startswith(("<!doctype", "<html", "<?xml")) or "<head>" in head


def _classify(status: int | None, body: str | None = None) -> str:
    if status is None:
        return RobotsOutcome.UNAVAILABLE
    if status in (404, 410):
        return RobotsOutcome.ABSENT
    if status in (401, 403):
        return RobotsOutcome.FORBIDDEN
    if 200 <= status < 300:
        # A soft-404: HTTP says OK, the body says "here is a web page".
        return RobotsOutcome.ABSENT if _looks_like_html(body) else RobotsOutcome.OK
    return RobotsOutcome.UNAVAILABLE


class RobotsCache:
    """In-process robots cache with a TTL and a bounded stale fallback.

    A fresh copy is preferred. A copy inside the TTL is reused. Past the TTL we
    refetch; if that refetch fails we may fall back to a copy up to
    ``robots_stale_max_days`` old, marked STALE so the staleness is recorded on
    the decision row rather than hidden.
    """

    def __init__(
        self,
        config: ComplianceConfig,
        fetcher: RobotsFetcher | None = None,
        *,
        write_snapshots: bool = True,
    ) -> None:
        self._config = config
        self._fetcher: RobotsFetcher = fetcher or HttpxRobotsFetcher()
        self._entries: dict[str, RobotsDocument] = {}
        self._write_snapshots = write_snapshots

    def get(
        self,
        source_code: str,
        base_url: str,
        *,
        now: datetime | None = None,
    ) -> RobotsDocument:
        now = now or datetime.now(UTC)
        cached = self._entries.get(source_code)
        ttl = timedelta(hours=self._config.robots_cache_ttl_hours)

        if cached is not None and now - cached.fetched_at < ttl:
            return cached

        status, body = self._fetcher.fetch(
            base_url,
            user_agent=self._config.user_agent,
            timeout=self._config.robots_fetch_timeout,
        )
        outcome = _classify(status, body)

        if outcome == RobotsOutcome.UNAVAILABLE and cached is not None:
            stale_limit = timedelta(days=self._config.robots_stale_max_days)
            if now - cached.fetched_at < stale_limit and cached.body is not None:
                document = RobotsDocument(
                    source_code=cached.source_code,
                    base_url=cached.base_url,
                    outcome=RobotsOutcome.STALE,
                    body=cached.body,
                    sha256=cached.sha256,
                    fetched_at=cached.fetched_at,
                    http_status=cached.http_status,
                    snapshot_path=cached.snapshot_path,
                )
                self._entries[source_code] = document
                return document

        sha256: str | None = None
        snapshot_path: str | None = None
        if body is not None and outcome == RobotsOutcome.OK:
            sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
            if self._write_snapshots:
                snapshot_path = _write_snapshot(source_code, body, now)

        document = RobotsDocument(
            source_code=source_code,
            base_url=base_url,
            outcome=outcome,
            body=body if outcome == RobotsOutcome.OK else None,
            sha256=sha256,
            fetched_at=now,
            http_status=status,
            snapshot_path=snapshot_path,
        )
        self._entries[source_code] = document
        return document

    def invalidate(self, source_code: str) -> None:
        self._entries.pop(source_code, None)


def base_url_of(url: str) -> str:
    """Reduce a URL to scheme://host[:port], where robots.txt lives."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Cannot derive a robots.txt base from {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"
