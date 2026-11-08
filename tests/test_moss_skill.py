"""The moss skill teaches the memory rule, the levels and the event-count trap.

The skill is the only place an agent learns the package, so these tests pin
what a person reads: the front matter and the four headings the core requires
in order, the capability id ``moss.efecto`` with every input named, the seven
approved examples with their WAVs, and the descriptions reference the skill
cites.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "moss"
EXAMPLES = PACKAGE / "examples"
REFERENCES = PACKAGE / "skill" / "references"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
#: The approved pieces that ship, each as a ``.toml`` and a ``.wav``.
APPROVED = (
    "cafe-ambiente",
    "campana-notificacion",
    "clic-interfaz",
    "lluvia-ventana",
    "pagina-libro",
    "pasos-madera",
    "whoosh-transicion",
)
#: The lab's ``seconds`` per piece; pagina-libro omits it and took the default 3.
SEGUNDOS = {
    "cafe-ambiente": 12,
    "campana-notificacion": 2,
    "clic-interfaz": 1,
    "lluvia-ventana": 12,
    "pagina-libro": 3,
    "pasos-madera": 6,
    "whoosh-transicion": 2,
}
#: A reference the skill cites, as ``references/<name>.md``.
REFERENCE_RE = re.compile(r"references/([a-z0-9][a-z0-9-]*)\.md")


def _front_matter() -> tuple[dict[str, str], str]:
    """The skill's front matter and body, split the way the core parses it."""
    first, second, *rest = SKILL.split("---", 2)
    assert first == "" and second.strip().startswith("name:")
    meta: dict[str, str] = {}
    for line in second.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, rest[0]


def _piece(piece: str) -> dict[str, object]:
    """One example as its ``[inputs]`` table."""
    return tomllib.loads((EXAMPLES / f"{piece}.toml").read_text(encoding="utf-8"))["inputs"]


def test_skill_front_matter_and_headings_order() -> None:
    """The core's contract: name=moss, a 20-200 description, four headings."""
    meta, body = _front_matter()
    assert meta["name"] == "moss"
    assert DESCRIPTION_MIN <= len(meta["description"]) <= DESCRIPTION_MAX
    assert "\n" not in meta["description"]
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_skill_names_the_capability_and_the_inputs() -> None:
    _, body = _front_matter()
    assert "moss.efecto" in body
    for name in MANIFEST["capabilities"]["efecto"]["inputs"]:
        assert name in body, name


def test_the_skill_cites_the_approved_examples() -> None:
    """All seven approved pieces are named in the skill, not only on disk."""
    _, body = _front_matter()
    for piece in APPROVED:
        assert f"examples/{piece}.toml" in body, piece


def test_the_examples_are_runnable_effect_pieces() -> None:
    """Each example parses, stays inside ``moss.efecto`` and ships its WAV."""
    efecto_inputs = MANIFEST["capabilities"]["efecto"]["inputs"]
    name_pattern = efecto_inputs["nombre"]["pattern"]
    max_segundos = efecto_inputs["segundos"]["max"]
    for piece in APPROVED:
        inputs = _piece(piece)
        assert set(inputs) <= set(efecto_inputs), piece
        assert "seed" not in inputs, piece
        assert inputs["nombre"] == piece, piece
        assert re.fullmatch(name_pattern, inputs["nombre"]), piece
        assert inputs["segundos"] == SEGUNDOS[piece], piece
        assert inputs["segundos"] <= max_segundos, piece
        assert str(inputs["descripcion"]).strip(), piece
        wav = EXAMPLES / f"{piece}.wav"
        assert wav.is_file(), piece
        assert wav.stat().st_size > 0, piece


def test_every_reference_the_skill_cites_exists() -> None:
    """A cited reference that is not on disk sends the reader nowhere."""
    _, body = _front_matter()
    cited = set(REFERENCE_RE.findall(body))
    assert cited, "the skill cites at least one reference"
    for name in cited:
        path = REFERENCES / f"{name}.md"
        assert path.is_file(), name
        assert path.stat().st_size > 0, name


def test_the_descriptions_reference_ports_every_prompt() -> None:
    """The reference keeps each lab prompt verbatim, exactly once."""
    text = (REFERENCES / "descriptions.md").read_text(encoding="utf-8")
    for piece in APPROVED:
        assert text.count(str(_piece(piece)["descripcion"])) == 1, piece
