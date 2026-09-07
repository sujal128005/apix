"""The most important test in Phase 4A.

Every other test here proves the gate behaves correctly *today*. This one is
about the code that has not been written yet. It scans the repository for the
shapes a bypass would take - an override flag, a permissive environment
variable, a second place that mints tokens - and fails the build if one appears.

The point is not that the current authors would add such an escape. It is that
the safeguard should not depend on their restraint at 2am the night before a
demo.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPLIANCE_DIR = REPO_ROOT / "packages" / "compliance"
SOURCE_DIRS = [REPO_ROOT / "packages", REPO_ROOT / "db", REPO_ROOT / "scripts"]

BYPASS_ENV_PATTERN = re.compile(
    r"IGNORE_ROBOTS|SKIP_COMPLIANCE|FORCE_(CRAWL|FETCH)|DISABLE_GATE|NO_ROBOTS",
    re.IGNORECASE,
)
BYPASS_PARAM_NAMES = frozenset({"force", "skip_gate", "bypass", "override", "ignore_robots"})


def _rel(path: Path) -> str:
    """Repo-relative path with forward slashes on every platform.

    ``Path.relative_to`` yields backslashes on Windows, so an assertion written
    against a POSIX-looking string passes on Linux and fails on Windows. The
    scan is about *which module* a thing lives in, not about how the host spells
    a path separator.
    """
    return path.relative_to(REPO_ROOT).as_posix()


def _python_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def test_no_bypass_environment_variable_exists() -> None:
    """No env var in the codebase could switch the gate off."""
    offenders: list[str] = []
    for path in _python_files(SOURCE_DIRS):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if BYPASS_ENV_PATTERN.search(line) and not line.lstrip().startswith("#"):
                if "BYPASS_ENV_PATTERN" in line or "re.compile" in line:
                    continue
                offenders.append(f"{_rel(path)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "A bypass-shaped environment variable exists. The gate must not be "
        "switchable off:\n" + "\n".join(offenders)
    )


def test_no_compliance_function_accepts_an_override_parameter() -> None:
    """No function in the compliance package takes force/bypass/override."""
    offenders: list[str] = []
    for path in _python_files([COMPLIANCE_DIR]):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            args = node.args
            names = {a.arg for a in (*args.args, *args.posonlyargs, *args.kwonlyargs)}
            bad = names & BYPASS_PARAM_NAMES
            if bad:
                offenders.append(f"{_rel(path)}:{node.lineno}: {node.name}() accepts {sorted(bad)}")
    assert not offenders, "Override-shaped parameters found:\n" + "\n".join(offenders)


def test_mint_key_lives_in_exactly_one_module() -> None:
    """_MINT_KEY is defined once and never re-exported."""
    definitions: list[str] = []
    for path in _python_files(SOURCE_DIRS):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if re.match(r"\s*_MINT_KEY\s*[:=]", line):
                definitions.append(f"{_rel(path)}:{lineno}")
    assert len(definitions) == 1, f"_MINT_KEY must be defined exactly once, found: {definitions}"
    assert definitions[0].startswith("packages/compliance/token.py"), definitions


def test_mint_key_is_not_in_any_public_surface() -> None:
    """_MINT_KEY is in no __all__, and no __init__.py references it in code.

    Checked over the parsed tree rather than raw text: a docstring explaining
    why the sentinel is private is documentation, not exposure, and a test that
    cannot tell the difference would punish the explanation.
    """
    for path in _python_files(SOURCE_DIRS):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = _rel(path)

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                assert "_MINT_KEY" not in ast.literal_eval(node.value), f"{rel} exports it"

        if path.name != "__init__.py":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "_MINT_KEY":
                pytest.fail(f"{rel}:{node.lineno} references _MINT_KEY in code")
            if isinstance(node, ast.Attribute) and node.attr == "_MINT_KEY":
                pytest.fail(f"{rel}:{node.lineno} reaches for _MINT_KEY")
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    assert alias.name != "_MINT_KEY", f"{rel}:{node.lineno} imports _MINT_KEY"


def test_tokens_are_minted_in_exactly_one_place() -> None:
    """Only token.mint() constructs a ComplianceToken, and only the gate calls it."""
    constructions: list[str] = []
    for path in _python_files(SOURCE_DIRS):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ComplianceToken"
            ):
                constructions.append(f"{_rel(path)}:{node.lineno}")
    assert len(constructions) == 1, (
        f"ComplianceToken must be constructed in exactly one place, found: {constructions}"
    )
    assert constructions[0].startswith("packages/compliance/token.py"), constructions


def test_stdlib_robotparser_is_not_imported_anywhere() -> None:
    """protego only. urllib.robotparser resolves Allow/Disallow precedence wrongly.

    Import-based, not text-based. robots.py names the stdlib parser in its
    docstring to record why it was rejected; that is exactly the kind of
    reasoning we want written down, so the test looks at imports instead.
    """
    offenders: list[str] = []
    for path in _python_files(SOURCE_DIRS):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = _rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "robotparser" in alias.name:
                        offenders.append(f"{rel}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "robotparser" in module or any(
                    a.name == "RobotFileParser" for a in node.names
                ):
                    offenders.append(f"{rel}:{node.lineno}: from {module}")
    assert not offenders, "stdlib robotparser imported in:\n" + "\n".join(offenders)


@pytest.mark.parametrize("module", ["compliance", "compliance.gate", "compliance.robots"])
def test_mint_key_is_not_importable_from_public_modules(module: str) -> None:
    """The sentinel cannot be reached through the package's public surface."""
    imported = __import__(module, fromlist=["*"])
    assert not hasattr(imported, "_MINT_KEY"), f"{module} leaks _MINT_KEY"
