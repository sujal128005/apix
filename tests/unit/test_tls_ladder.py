"""ADR-016: certificate verification is never disabled, on any rung.

The official NSO client sets CERT_NONE and check_hostname=False. These tests
exist so that decision can never be copied into this codebase by someone
reasonable-sounding under time pressure.
"""

from __future__ import annotations

import ast
import ssl
from pathlib import Path

import pytest

from collector.tls import OP_LEGACY_SERVER_CONNECT, TlsLadder, TlsMode, build_ssl_context

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = [REPO_ROOT / "packages", REPO_ROOT / "db", REPO_ROOT / "scripts"]


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_DIRS:
        if root.exists():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return files


# -- every rung verifies ---------------------------------------------------


@pytest.mark.parametrize("mode", [TlsMode.STANDARD, TlsMode.LEGACY])
def test_every_rung_keeps_hostname_checking_on(mode: TlsMode) -> None:
    assert build_ssl_context(mode).check_hostname is True


@pytest.mark.parametrize("mode", [TlsMode.STANDARD, TlsMode.LEGACY])
def test_every_rung_requires_a_certificate(mode: TlsMode) -> None:
    assert build_ssl_context(mode).verify_mode == ssl.CERT_REQUIRED


def test_the_pinned_rung_also_verifies(tmp_path: Path) -> None:
    bundle = tmp_path / "ca.pem"
    bundle.write_text((ssl.get_default_verify_paths().cafile and "") or "", encoding="utf-8")
    # Use the system bundle so load_verify_locations has something real to read.
    import certifi

    bundle.write_text(Path(certifi.where()).read_text(encoding="utf-8"), encoding="utf-8")
    context = build_ssl_context(TlsMode.PINNED, ca_bundle=bundle)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


# -- what the rungs actually differ in -------------------------------------


def test_the_legacy_rung_relaxes_renegotiation_and_nothing_else() -> None:
    """Legacy renegotiation and certificate validation are separate concerns.

    The official client bundles them. This test records that we unbundled them
    deliberately, so a future reader knows it was a decision rather than luck.
    """
    standard = build_ssl_context(TlsMode.STANDARD)
    legacy = build_ssl_context(TlsMode.LEGACY)

    assert not standard.options & OP_LEGACY_SERVER_CONNECT
    assert legacy.options & OP_LEGACY_SERVER_CONNECT
    assert legacy.check_hostname == standard.check_hostname
    assert legacy.verify_mode == standard.verify_mode


def test_the_pinned_rung_refuses_to_run_without_a_bundle() -> None:
    with pytest.raises(FileNotFoundError, match="CA bundle"):
        build_ssl_context(TlsMode.PINNED, ca_bundle=None)


# -- the ladder ------------------------------------------------------------


def test_the_ladder_stops_at_two_rungs_without_a_pin() -> None:
    assert TlsLadder().modes() == (TlsMode.STANDARD, TlsMode.LEGACY)


def test_there_is_no_fourth_rung() -> None:
    """If all rungs fail, the host is unreachable safely. That is a fact to
    report, not a check to switch off."""
    assert len(list(TlsMode)) == 3


# -- the guard -------------------------------------------------------------


def test_certificate_verification_is_never_disabled_anywhere() -> None:
    """No CERT_NONE, no check_hostname=False, no verify=False. Anywhere."""
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(REPO_ROOT).as_posix()

        for node in ast.walk(tree):
            # ssl.CERT_NONE referenced as a value
            if isinstance(node, ast.Attribute) and node.attr == "CERT_NONE":
                offenders.append(f"{rel}:{node.lineno}: references ssl.CERT_NONE")

            # check_hostname = False  /  self.x.check_hostname = False
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    name = (
                        target.attr
                        if isinstance(target, ast.Attribute)
                        else target.id
                        if isinstance(target, ast.Name)
                        else ""
                    )
                    if (
                        name in {"check_hostname", "verify"}
                        and isinstance(node.value, ast.Constant)
                        and node.value.value is False
                    ):
                        offenders.append(f"{rel}:{node.lineno}: sets {name} = False")

            # verify=False passed as a keyword
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (
                        kw.arg == "verify"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is False
                    ):
                        offenders.append(f"{rel}:{node.lineno}: passes verify=False")

    assert not offenders, (
        "ADR-016 forbids disabling certificate verification in any environment:\n"
        + "\n".join(offenders)
    )


# -- trust anchors are reproducible, not host-dependent ---------------------


def test_trust_anchors_come_from_certifi_not_the_host() -> None:
    """The same certificate must verify identically everywhere.

    ``create_default_context()`` with no cafile reads whatever the host trusts.
    On Windows that is a local snapshot which omits roots until something
    triggers an on-demand fetch, so a chain the OS accepts can fail in Python.
    An index whose values must be reproducible cannot have its network layer
    depend on which roots a particular laptop happens to have cached.
    """
    import certifi

    source = (REPO_ROOT / "packages" / "collector" / "tls.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_default_context"
    ]
    assert calls, "expected create_default_context to be used"
    for call in calls:
        assert any(kw.arg == "cafile" for kw in call.keywords), (
            f"line {call.lineno}: create_default_context() must be given an explicit "
            "cafile, or trust becomes host-dependent"
        )

    # And the bundle we depend on must actually contain the anchor MoSPI uses.
    bundle = Path(certifi.where()).read_text(encoding="utf-8")
    assert "emSign Root CA - G1" in bundle, (
        "certifi no longer carries the root that anchors api.mospi.gov.in; "
        "the PINNED rung is now required for that host"
    )
