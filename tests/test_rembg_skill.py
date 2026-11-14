"""The rembg skill teaches the cutout, clean paper and the lab's measurements.

The skill is the only place an agent learns the package, so these tests pin
what a person reads: the front matter and the four headings the core requires
in order, the capability ids ``rembg.cutout`` and ``rembg.paper`` with the
checkerboard and ``facet pull rembg``, the lamina_web exclusion, the lab's measured
run, the licence attributions, and the approved examples the skill cites.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "rembg"
EXAMPLES = PACKAGE / "examples"
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
HEADINGS = ("## When to use", "## Pieces", "## Judging the result", "## Pitfalls")
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
#: The lab pieces that ship, each cited in the skill body.
EXAMPLE_FILES = ("remove.py", "measurement.json", "plate-checkerboard.png", "README.md")
#: The lab run recorded in ``medicion.json``; the skill states the same numbers.
LAB_SIZE = [1344, 768]
LAB_SECONDS = 1.48
LAB_TRANSPARENT = 66.59


def _body() -> str:
    _first, _second, body = SKILL.split("---", 2)
    return body


def test_the_front_matter_parses_in_the_core_format() -> None:
    first, second, _rest = SKILL.split("---", 2)
    assert first == ""
    frontmatter = second.strip().splitlines()
    assert "name: rembg" in frontmatter
    description = next(
        line.removeprefix("description:").strip()
        for line in frontmatter
        if line.startswith("description:")
    )
    assert DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX


def test_the_four_headings_appear_in_order() -> None:
    body = _body()
    positions = [body.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)


def test_the_body_names_the_capability_and_the_checkerboard() -> None:
    body = _body()
    assert "rembg.cutout" in body
    assert "rembg.paper" in body
    assert "checkerboard" in body
    assert "facet pull rembg" in body


def test_the_skill_ports_the_lamina_web_exclusion() -> None:
    """The clean-paper rule keeps lamina_web out, as the README does."""
    assert "lamina_web" in _body()
    assert "paper-cleaning" in _body()
    assert "tools/papel_limpio.py" not in _body()


def test_the_skill_ports_the_lab_measurements_and_the_licences() -> None:
    """The measured run and both licence attributions survive as numbers."""
    body = _body()
    for token in ("1344×768", "1.48", "66.59", "MIT", "Apache-2.0", "U-2-Net"):
        assert token in body, token


def test_the_skill_cites_the_approved_examples() -> None:
    """Each approved example is named in the skill, not only left on disk."""
    body = _body()
    for name in EXAMPLE_FILES:
        assert f"examples/{name}" in body, name


def test_the_approved_examples_ship_and_are_non_empty() -> None:
    """Deleting a lab piece fails here, not in a person's first run."""
    for name in EXAMPLE_FILES:
        example = EXAMPLES / name
        assert example.is_file(), example
        assert example.stat().st_size > 0, example


def test_the_example_record_carries_the_ported_measurements() -> None:
    """The skill's numbers match the record byte-for-byte, not a summary."""
    record = json.loads((EXAMPLES / "measurement.json").read_text(encoding="utf-8"))
    assert record["size"] == LAB_SIZE
    assert record["elapsed_seconds"] == LAB_SECONDS
    assert record["transparent_pixels_percent"] == LAB_TRANSPARENT
    assert record["preview"] == "plate-checkerboard.png"
