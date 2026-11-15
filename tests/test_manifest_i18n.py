"""Every capability carries a Spanish summary; the index labels every facet.

univerlab.org builds its facet page from these fields instead of hardcoding
Spanish in its own source, so the registry pins them here: one
``[capabilities.<cap>.i18n.es]`` summary per capability and one English plus
one Spanish label per facet in ``index.toml``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Core rejects longer es summaries (manifest/i18n.py SUMMARY_LIMIT).
SUMMARY_LIMIT = 200

#: Every facet the index must declare, with its English and Spanish labels.
FACET_LABELS = {
    "voice": ("Voice", "Voz"),
    "audio": ("Audio", "Audio"),
    "image": ("Image", "Imagen"),
    "video": ("Video", "Video"),
    "cad": ("CAD", "CAD"),
    "text": ("Text", "Texto"),
    "presentation": ("Presentation", "Presentación"),
}


def _package_files() -> list[Path]:
    return sorted((ROOT / "packages").glob("*/package.toml"))


@pytest.mark.parametrize("manifest", _package_files(), ids=lambda p: p.parent.name)
def test_every_capability_has_an_es_summary(manifest: Path) -> None:
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    assert data["capabilities"], f"{manifest.parent.name} declares no capabilities"
    for capability, item in data["capabilities"].items():
        summary = item.get("i18n", {}).get("es", {}).get("summary")
        assert isinstance(summary, str) and summary, (
            f"{manifest.parent.name} [{capability}] has no i18n.es summary"
        )
        assert len(summary) <= SUMMARY_LIMIT, (
            f"{manifest.parent.name} [{capability}] es summary is {len(summary)} chars"
        )


def test_index_declares_every_facet_label() -> None:
    data = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
    assert set(data["facets"]) == set(FACET_LABELS)
    for facet, (english, spanish) in FACET_LABELS.items():
        entry = data["facets"][facet]
        assert entry["label"] == english
        assert entry["i18n"]["es"]["label"] == spanish
