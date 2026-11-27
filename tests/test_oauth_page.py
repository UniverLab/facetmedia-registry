"""Tests for the shared facetMedia-branded OAuth callback HTML page."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "lib" / "oauth_page.py"
_SPEC = importlib.util.spec_from_file_location("oauth_page", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
render = _MOD.render


def test_render_success_page_contains_brand_tokens_and_phrase() -> None:
    raw = render(True, "LinkedIn")
    assert isinstance(raw, bytes)
    html_text = raw.decode("utf-8")
    assert html_text.startswith("<!doctype html>")
    assert "#F6F3EC" in html_text
    assert "#E8C547" in html_text
    assert "facetMedia" in html_text
    assert "Signed in" in html_text
    assert "LinkedIn" in html_text
    assert "signed in; return to the terminal" in html_text
    assert "close this tab" in html_text


def test_render_failure_page_escapes_html_and_shows_badge() -> None:
    raw = render(False, "X", '<script>alert("xss")</script>')
    html_text = raw.decode("utf-8")
    assert "#F6F3EC" in html_text
    assert "#E8C547" in html_text
    assert "Sign-in failed" in html_text
    assert "signed in; return to the terminal" not in html_text
    assert "<script>" not in html_text
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in html_text
