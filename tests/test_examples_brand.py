"""The UniverLab brand gate for curated example pieces.

Every file and folder under ``packages/*/examples/`` carries an English
name, and every colour in a scanned example source belongs to one of the
two UniverLab palettes (plus black). Third-party code under ``vendor/``
is excluded from the colour gate.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"

#: Spanish stems that must not survive in any example file or folder name.
DENYLIST = frozenset(
    {
        "laboratorio",
        "zorro",
        "voz",
        "musica",
        "modelos",
        "estudio",
        "escuadra",
        "plano",
        "cierre",
        "clasica",
        "alegre",
        "melancolica",
        "cafe",
        "ambiente",
        "hola",
        "mundo",
        "arquitectura",
        "ciclo",
        "acuarela",
        "fondo",
        "taza",
        "vapor",
        "lluvia",
        "ventana",
        "campana",
        "notificacion",
        "pasos",
        "madera",
        "pagina",
        "libro",
        "clic",
        "interfaz",
        "bosque",
        "niebla",
        "rapido",
        "calle",
        "foto",
        "producto",
        "lamina",
        "ilustracion",
        "iteracion",
        "grabado",
        "comparacion",
        "subtitulos",
        "medicion",
        "remover",
        "vista",
        "imagenes",
        "mano",
        "transicion",
        "leeme",
    }
)

#: Day palette, night palette, and black: the only hex colours allowed.
ALLOWED_HEX = frozenset(
    {
        "f4f0ea",
        "eee7dc",
        "1d1510",
        "6b5a43",
        "8a6a2c",
        "87222c",
        "222928",
        "1a201f",
        "ecebe4",
        "b9bdb5",
        "5b6560",
        "d9b878",
        "e6c84a",
        "000",
        "000000",
    }
)

SCANNED_SUFFIXES = {".html", ".css", ".svg", ".toml", ".js", ".mmd", ".py"}
HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
TOKEN_RE = re.compile(r"[a-z0-9]+")


def _example_paths() -> list[Path]:
    """Every file and folder under every package's ``examples/``."""
    found: list[Path] = []
    for package in sorted(PACKAGES.iterdir()):
        examples = package / "examples"
        if not examples.is_dir():
            continue
        for path in sorted(examples.rglob("*")):
            if ".venv" in path.parts:
                continue
            found.append(path)
    return found


def test_example_names_are_english() -> None:
    """No example file or folder name carries a denylisted Spanish word."""
    offenders: list[str] = []
    for path in _example_paths():
        tokens = TOKEN_RE.findall(path.name.lower())
        hit = DENYLIST.intersection(tokens)
        if hit:
            offenders.append(f"{path}: {sorted(hit)}")
    assert not offenders, "\n".join(offenders)


def test_example_colours_are_univerlab() -> None:
    """No scanned example source uses a hex outside the two palettes."""
    offenders: list[str] = []
    for path in _example_paths():
        if "vendor" in path.parts:
            continue
        if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in HEX_RE.findall(text):
            if match.lower() not in ALLOWED_HEX:
                offenders.append(f"{path}: #{match}")
    assert not offenders, "\n".join(offenders)
