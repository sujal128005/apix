"""TLS context construction (ADR-016).

The official NSO client for ``api.mospi.gov.in`` sets ``check_hostname = False``,
``verify_mode = CERT_NONE`` and ``session.verify = False``, with a comment
explaining that the server requires legacy SSL renegotiation. We do not copy
that. A government-facing service that accepts any certificate is trivially
intercepted, and "the reference client did it" is not a defence.

Legacy renegotiation and certificate verification are **independent concerns**.
The official client bundles them; it does not follow that both are required. So
this module climbs a ladder, keeping verification on at every rung:

    1. STANDARD    default context, verification on
    2. LEGACY      OP_LEGACY_SERVER_CONNECT enabled, verification still on
    3. PINNED      an explicit CA bundle, verification still on

There is deliberately no fourth rung. If all three fail, the answer is that we
cannot reach the host safely and the source is unavailable - which is a fact to
report, not a check to switch off.

**Trust anchors come from certifi, not the operating system.** ``create_default_
context()`` reads whatever the host happens to trust, which is neither
reproducible nor portable: Windows ships many roots on demand, so a root can be
absent from the local store until something triggers a fetch from Windows
Update. That is how ``api.mospi.gov.in`` - anchored to ``emSign Root CA - G1``,
a root certifi has carried for years - can fail verification on a Windows box
whose own chain engine trusts it perfectly well. Pinning to certifi makes the
answer the same on a laptop, in CI and on a server, which is what an auditable
index needs.

Which rung worked is recorded, so the Command Center can show it and a reviewer
can ask why. Silently succeeding at rung 2 without anyone noticing would be
almost as bad as rung 4 existing.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

import certifi

__all__ = ["TlsAttempt", "TlsLadder", "TlsMode", "build_ssl_context"]

# OpenSSL's flag for servers that do not support RFC 5746 secure renegotiation.
# Enabling it relaxes a *renegotiation* requirement. It says nothing about
# certificate validation, which is the whole point of this module.
OP_LEGACY_SERVER_CONNECT: Final[int] = 0x4


class TlsMode(StrEnum):
    """Rungs of the ladder, in the order they are tried."""

    STANDARD = "STANDARD"
    LEGACY = "LEGACY"
    PINNED = "PINNED"


@dataclass(frozen=True, slots=True)
class TlsAttempt:
    """What happened on one rung, for the audit trail."""

    mode: TlsMode
    succeeded: bool
    detail: str


def build_ssl_context(mode: TlsMode, *, ca_bundle: Path | None = None) -> ssl.SSLContext:
    """Build a verifying SSL context for the given rung.

    Every branch returns a context with ``check_hostname`` and
    ``verify_mode = CERT_REQUIRED`` intact. ``tests/unit/test_tls_ladder.py``
    asserts that for each mode, so a future edit that relaxes one cannot pass
    review unnoticed.
    """
    # certifi, explicitly - see the module docstring on why not the OS store.
    context = ssl.create_default_context(cafile=certifi.where())
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    if mode is TlsMode.LEGACY:
        # Permit renegotiation with a server that predates RFC 5746. The
        # certificate is still checked, and the hostname is still matched.
        context.options |= OP_LEGACY_SERVER_CONNECT

    elif mode is TlsMode.PINNED:
        if ca_bundle is None or not ca_bundle.exists():
            raise FileNotFoundError(
                f"PINNED mode needs a CA bundle; {ca_bundle} is missing. "
                "Fetch the server certificate and commit it to "
                "data/reference/ before using this rung."
            )
        context.options |= OP_LEGACY_SERVER_CONNECT
        # Additive: the pinned bundle supplements certifi rather than replacing
        # it, so pinning one host's anchor cannot quietly narrow trust for every
        # other host the process talks to.
        context.load_verify_locations(cafile=str(ca_bundle))

    return context


@dataclass(frozen=True, slots=True)
class TlsLadder:
    """Tries each rung in order and reports which one worked."""

    ca_bundle: Path | None = None

    def modes(self) -> tuple[TlsMode, ...]:
        if self.ca_bundle is not None and self.ca_bundle.exists():
            return (TlsMode.STANDARD, TlsMode.LEGACY, TlsMode.PINNED)
        return (TlsMode.STANDARD, TlsMode.LEGACY)

    def contexts(self) -> list[tuple[TlsMode, ssl.SSLContext]]:
        return [(mode, build_ssl_context(mode, ca_bundle=self.ca_bundle)) for mode in self.modes()]
