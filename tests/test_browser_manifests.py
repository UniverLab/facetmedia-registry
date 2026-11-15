"""The pinned Chromium the three rendering packages share.

hyperframes, mermaid and deck declare the same ``[browser]`` table: the
Chrome for Testing build ``facet pull`` installs once into the facet home,
so a fresh machine renders without a host Chrome. Each runner reads the
executable from ``FACET_BROWSER``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("hyperframes", "mermaid", "deck")
EXPECTED = {
    "channel": "chromium",
    "revision": "1254",
    "version": "158.0.8127.18",
    "sha256": "c6cb06e1574ac2f6c5c38e31551157fbcaa67e6366c89974084553c5a5772592",
}


@pytest.mark.parametrize("name", PACKAGES)
def test_the_package_declares_the_shared_pinned_chromium(name: str) -> None:
    manifest = tomllib.loads(
        (ROOT / "packages" / name / "package.toml").read_text(encoding="utf-8")
    )
    assert manifest["browser"] == EXPECTED
