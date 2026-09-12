"""Accessibility, to WCAG 2.1 Level AA.

GIGW 3.0 carries 88 mandatory checkpoints across Quality, Accessibility,
Cybersecurity and Lifecycle Management. Accessibility is 50 of them, adopted
wholesale from WCAG 2.1 Level AA, and it is the part that can be tested here
rather than by an external auditor.

These tests do not replace an STQC or CERT-In empanelled audit. They stop the
easy regressions - a colour tweaked below threshold, a table losing its header
scopes - reaching that audit at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "apps" / "api" / "static"
PAGES = ["index.html", "routes.html", "lead-time.html", "quality.html",
         "methodology.html", "operations.html"]


# --- contrast -------------------------------------------------------------


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(colour: str) -> float:
    h = colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(foreground: str, background: str) -> float:
    a, b = _luminance(foreground), _luminance(background)
    low, high = sorted((a, b))
    return (high + 0.05) / (low + 0.05)


def token(name: str) -> str:
    """Read a colour straight from the stylesheet, so the test tracks the source."""
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}})", css)
    assert match, f"{name} not found in style.css"
    return match.group(1)


@pytest.mark.parametrize(
    ("foreground", "background", "label"),
    [
        ("--ink", "--page", "body text on the page"),
        ("--ink", "--panel", "body text on a panel"),
        ("--ink-soft", "--panel", "secondary text"),
        ("--ink-faint", "--panel", "caption text on a panel"),
        ("--ink-faint", "--panel-alt", "caption text on an alternate panel"),
        ("--ink-faint", "--page", "caption text on the page"),
        ("--navy-800", "--panel-alt", "section headings"),
        ("--navy-800", "--navy-tint", "table headers"),
        ("--navy-800", "--panel", "statistic values"),
        ("--navy-500", "--panel", "links"),
        ("--ok", "--ok-tint", "success tag"),
        ("--warn", "--warn-tint", "warning tag"),
        ("--stop", "--stop-tint", "blocked tag"),
    ],
)
def test_text_meets_aa_contrast(foreground: str, background: str, label: str) -> None:
    """4.5:1 for normal text. Read from the stylesheet, so a colour tweak that
    drops below threshold fails here rather than at an audit."""
    ratio = contrast(token(foreground), token(background))
    assert ratio >= 4.5, f"{label}: {ratio:.2f}:1, needs 4.5:1"


def test_the_saffron_accent_meets_non_text_contrast() -> None:
    """3:1 for a graphical element that carries meaning."""
    assert contrast(token("--saffron"), token("--navy-800")) >= 3.0


# --- structure ------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_every_page_declares_its_language(page: str) -> None:
    assert 'lang="en"' in (STATIC / page).read_text(encoding="utf-8")


@pytest.mark.parametrize("page", PAGES)
def test_every_page_has_a_unique_descriptive_title(page: str) -> None:
    html = (STATIC / page).read_text(encoding="utf-8")
    match = re.search(r"<title>(.*?)</title>", html, re.S)
    assert match, f"{page} has no title"
    assert "APIx" in match.group(1)


def test_page_titles_are_distinct() -> None:
    """A screen-reader user moving between tabs needs them to differ."""
    titles = []
    for page in PAGES:
        html = (STATIC / page).read_text(encoding="utf-8")
        match = re.search(r"<title>(.*?)</title>", html, re.S)
        assert match
        titles.append(match.group(1).strip())
    assert len(set(titles)) == len(titles), f"duplicate titles: {titles}"


@pytest.mark.parametrize("page", PAGES)
def test_every_page_has_a_skip_target(page: str) -> None:
    """The skip link needs somewhere to skip to."""
    assert 'id="main"' in (STATIC / page).read_text(encoding="utf-8")


def test_the_skip_link_is_reachable_by_keyboard_and_hidden_until_focused() -> None:
    """Off-screen until focused, visible when tabbed to. A skip link that never
    becomes visible helps no one."""
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert ".skip-link" in css
    assert ".skip-link:focus" in css
    assert "left: -9999px" in css


def test_focus_is_always_visible() -> None:
    """Removing the focus ring without replacing it strands keyboard users."""
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "outline: none" not in css.replace(" ", "").replace("outline:none", "outline: none")
    assert ":focus" in css and "outline:" in css


def test_the_navigation_is_labelled_as_a_landmark() -> None:
    js = (STATIC / "apix.js").read_text(encoding="utf-8")
    assert 'aria-label="Primary"' in js
    assert 'aria-current="page"' in js


def test_the_text_sizer_controls_are_labelled_and_stateful() -> None:
    """Icon-only buttons need an accessible name and a pressed state."""
    js = (STATIC / "apix.js").read_text(encoding="utf-8")
    assert 'role="group"' in js
    assert 'aria-label="Text size"' in js
    assert "aria-pressed" in js
    assert "title=" in js


def test_no_page_carries_an_unlabelled_image() -> None:
    """Vacuously true today - the design uses no images at all - and asserted so
    that adding one without alt text fails."""
    for page in (*PAGES, "apix.js"):
        html = (STATIC / page).read_text(encoding="utf-8")
        for tag in re.findall(r"<img[^>]*>", html, re.I):
            assert "alt=" in tag, f"{page}: image without alt text: {tag}"


def test_text_can_be_resized_without_a_separate_stylesheet() -> None:
    """WCAG 1.4.4 requires text to scale to 200%. The whole page is sized from a
    single custom property, so the sizer scales everything together."""
    import re

    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "--font-scale" in css
    assert "calc(15px * var(--font-scale))" in css

    # Every font-size below the root must be relative, so the sizer moves it.
    # A px size is immune to the control and silently stays small.
    sizes = re.findall(r"font-size:\s*([^;]+);", css)
    fixed = [s for s in sizes if s.strip().endswith("px") and "calc(" not in s]
    assert not fixed, f"font sizes fixed in px ignore the text sizer: {fixed}"

    relative = [s for s in sizes if "rem" in s]
    assert len(relative) >= 15, "most sizes should be in rem"


def test_status_is_never_conveyed_by_colour_alone() -> None:
    """WCAG 1.4.1. Every status tag carries text as well as a colour."""
    js = (STATIC / "apix.js").read_text(encoding="utf-8")
    assert "esc(p)" in js, "the provenance tag renders its own label"
    for page in ("operations.html", "index.html"):
        html = (STATIC / page).read_text(encoding="utf-8")
        if "tag live" in html or "tag stop" in html:
            assert "esc(" in html, f"{page}: status tags must render text"
