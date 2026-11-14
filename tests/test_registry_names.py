"""The registry's capability ids, inputs and enum values are English.

Before v1 the user decided every name the registry exposes is English. This
file pins the rename at the level a TOML round-trip hides: the bare
``[capabilities.*]`` headers and the input keys such as ``name``, ``photo``
and ``text`` that an acceptance grep over dotted ids would never see.

It fails on the old tree — every package here carried a Spanish capability,
input or enum value — and passes only when the English name is the only one.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: The capability ids each package must expose, English and old-free.
CAPABILITIES = {
    "acestep": ("bed",),
    "ascii": ("image", "banner", "fonts"),
    "deck": ("slides", "page", "presenter"),
    "demostage": ("demo",),
    "freecad": ("drawing",),
    "moss": ("sfx",),
    "pillow": ("base",),
    "rembg": ("cutout", "paper"),
    "svganim": ("bake",),
    "texforge": ("document",),
    "whisper-subs": ("subtitles",),
    "comfy": ("still", "edit", "clip"),
    "comfy-xl": ("still", "edit", "clip"),
    "recipes": ("plan",),
}

#: The Spanish names each manifest must no longer carry, anywhere.
OLD_IDENTIFIERS = {
    "acestep": ("duracion",),
    "ascii": ("densidad", "trazo", "forma"),
    "deck": ("pagina", "fuente", "notas", "texto"),
    "demostage": ("partitura",),
    "freecad": ("plano", "guion", "pieza"),
    "moss": ("efecto", "descripcion", "segundos", "nombre"),
    "pillow": (
        "imagen",
        "operaciones",
        "operacion",
        "formato",
        "modo",
        "ancho",
        "alto",
        "columnas",
        "filas",
        "convertir",
        "redimensionar",
        "hoja",
    ),
    "rembg": ("papel", "foto", "lamina", "damero"),
    "svganim": ("guion", "datos"),
    "texforge": ("documento", "principal", "nombre", "autor"),
    "whisper-subs": ("subtitulos", "origen", "formato"),
    "comfy": ("rapido",),
    "comfy-xl": ("rapido",),
    "recipes": (),
}

NEW_INPUTS = {
    "deck": ("source", "notes", "page", "text"),
    "freecad": ("script", "part"),
    "moss": ("description", "seconds", "name"),
    "pillow": ("image", "operations", "op", "format", "mode", "width", "height"),
    "rembg": ("photo", "plate"),
    "svganim": ("script", "data"),
    "texforge": ("main", "name", "author"),
    "whisper-subs": ("source", "format"),
}


def _manifest_text(package: str) -> str:
    return (ROOT / "packages" / package / "package.toml").read_text(encoding="utf-8")


@pytest.mark.parametrize("package", sorted(CAPABILITIES))
def test_the_capability_ids_are_the_english_ones(package: str) -> None:
    manifest = tomllib.loads(_manifest_text(package))
    assert tuple(manifest["capabilities"]) == CAPABILITIES[package]


def _declared_identifiers(package: str) -> set[str]:
    """Capability ids, input keys and enum values — not prose.

    Spanish summaries legitimately say ``texto`` or ``imagen``; only the
    identifiers the registry exposes must stay English.  Every parsed table
    key counts, whatever syntax declared it — header, dotted, quoted or an
    inline table — because prose never becomes a key.
    """
    text = _manifest_text(package)
    manifest = tomllib.loads(text)
    declared = set(manifest.get("capabilities", {}))
    declared.update(re.findall(r"(?:inputs|items)\.([a-z][a-z-]*)", text))
    stack: list[object] = [manifest.get("capabilities", {})]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                declared.add(key)
                if key == "values" and isinstance(value, list):
                    declared.update(v for v in value if isinstance(v, str))
                else:
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return declared


@pytest.mark.parametrize("package", sorted(OLD_IDENTIFIERS))
def test_the_manifest_carries_no_old_identifier(package: str) -> None:
    declared = _declared_identifiers(package)
    for old in OLD_IDENTIFIERS[package]:
        assert old not in declared, f"{package}/package.toml still names {old!r}"


@pytest.mark.parametrize("package", sorted(NEW_INPUTS))
def test_the_capability_declares_the_english_inputs(package: str) -> None:
    text = _manifest_text(package)
    declared = set(re.findall(r"(?:inputs|items)\.([a-z][a-z-]*)", text))
    for new in NEW_INPUTS[package]:
        assert new in declared, f"{package} declares no {new!r} input"


def test_comfy_and_comfy_xl_ship_the_fast_flow_files() -> None:
    for package, name in (
        ("comfy", "wan22-i2v-fast.json"),
        ("comfy-xl", "wan22-i2v-14b-fast.json"),
    ):
        flows = ROOT / "packages" / package / "flows"
        assert (flows / name).is_file()
        assert not (flows / name.replace("-fast", "-rapido")).exists()


def test_rembg_ships_the_checkerboard_example() -> None:
    examples = ROOT / "packages" / "rembg" / "examples"
    assert (examples / "plate-checkerboard.png").is_file()
    assert not (examples / "vista-damero.png").exists()
    reading = (examples / "measurement.json").read_text(encoding="utf-8")
    assert "plate-checkerboard.png" in reading
