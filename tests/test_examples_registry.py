"""Every capability ships a self-contained example piece under ``examples/``.

``facet example <capability>`` copies the first piece tagged with a top-level
``capability`` key, so a missing tag or a missing file leaves a person with
nothing to run. These tests read the manifests as data — the registry suite
runs without the core installed — and re-apply the core's input validation to
every tagged piece: unknown keys, required keys, types, enums, ranges, patterns
and the paths resolved from the piece's own directory.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
INTEGER = "integer"
NUMBER = "number"
ENUM = "enum"
ARRAY = "array"
PATH = "path"
STRING = "string"
BOOLEAN = "boolean"
NUMERIC = {INTEGER, NUMBER}


def _manifests() -> list[tuple[str, dict[str, Any]]]:
    """Every package manifest, by package name."""
    found: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(PACKAGES.glob("*/package.toml")):
        found.append((path.parent.name, tomllib.loads(path.read_text(encoding="utf-8"))))
    return found


def _tagged_examples(package_dir: Path) -> list[tuple[str, Path]]:
    """Every example piece of a package: (capability id, piece path)."""
    found: list[tuple[str, Path]] = []
    for path in sorted((package_dir / "examples").rglob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        named = data.get("capability")
        if isinstance(named, str):
            found.append((named, path))
    return found


def _examples_by_capability() -> dict[str, list[Path]]:
    """The tagged pieces of every package, keyed by capability id."""
    grouped: dict[str, list[Path]] = {}
    for name, _manifest in _manifests():
        for capability, path in _tagged_examples(PACKAGES / name):
            grouped.setdefault(capability, []).append(path)
    return grouped


def _type_matches(kind: str, value: Any) -> bool:
    if kind in {STRING, ENUM, PATH}:
        return isinstance(value, str)
    if kind == INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == NUMBER:
        return isinstance(value, int | float) and not isinstance(value, bool)
    if kind == BOOLEAN:
        return isinstance(value, bool)
    return False


def _check_scalar(
    name: str, field: dict[str, Any], value: Any, base: Path, errors: list[str]
) -> None:
    kind = field["type"]
    if not _type_matches(kind, value):
        errors.append(f"{name}: type")
        return
    if kind == PATH:
        if not (base / value).resolve().exists():
            errors.append(f"{name}: not_found ({value})")
        return
    if kind == ENUM and value not in field["values"]:
        errors.append(f"{name}: enum {value!r}")
    pattern = field.get("pattern")
    if pattern is not None and re.fullmatch(pattern, value) is None:
        errors.append(f"{name}: pattern")
    if kind in NUMERIC and "min" in field and value < field["min"]:
        errors.append(f"{name}: min")
    if kind in NUMERIC and "max" in field and value > field["max"]:
        errors.append(f"{name}: max")


def _check_array(
    name: str, field: dict[str, Any], value: Any, base: Path, errors: list[str]
) -> None:
    if not isinstance(value, list):
        errors.append(f"{name}: type")
        return
    if len(value) < field.get("min_items", 0):
        errors.append(f"{name}: min_items")
    for position, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"{name}[{position}]: type")
            continue
        _check_fields(field.get("items", {}), item, f"{name}[{position}]", base, errors)


def _check_fields(
    declared: dict[str, Any], values: dict[str, Any], prefix: str, base: Path, errors: list[str]
) -> None:
    for key in values:
        if key not in declared:
            errors.append(f"{prefix}.{key}: unknown")
    for key, field in declared.items():
        name = f"{prefix}.{key}"
        if key not in values:
            if field.get("required"):
                errors.append(f"{name}: required")
            continue
        if field["type"] == ARRAY:
            _check_array(name, field, values[key], base, errors)
        else:
            _check_scalar(name, field, values[key], base, errors)


def _problems(piece: Path) -> list[str]:
    """Everything the core's input validation would refuse in this piece."""
    data = tomllib.loads(piece.read_text(encoding="utf-8"))
    package = PACKAGES / piece.relative_to(ROOT).parts[1]
    manifest = tomllib.loads((package / "package.toml").read_text(encoding="utf-8"))
    capability = manifest["capabilities"][data["capability"].split(".")[-1]]
    errors: list[str] = []
    _check_fields(capability["inputs"], data.get("inputs", {}), "", piece.parent, errors)
    return errors


def _missing_examples() -> list[str]:
    grouped = _examples_by_capability()
    missing: list[str] = []
    for name, manifest in _manifests():
        for capability in manifest["capabilities"]:
            full = f"{name}.{capability}"
            if not grouped.get(full):
                missing.append(full)
    return missing


def test_every_capability_ships_an_example_piece() -> None:
    """Ten packages used to ship none; one missing id still breaks the verb."""
    missing = _missing_examples()
    assert not missing, f"capabilities with no tagged example: {missing}"


def test_every_example_names_a_real_capability() -> None:
    """A wrong id makes the piece a non-example: rule 1 short-circuits on it."""
    known = {
        f"{name}.{capability}"
        for name, manifest in _manifests()
        for capability in manifest["capabilities"]
    }
    unknown: list[str] = []
    for name, _manifest in _manifests():
        for capability, path in _tagged_examples(PACKAGES / name):
            if capability not in known:
                unknown.append(f"{path.relative_to(ROOT)}: {capability}")
    assert not unknown, f"capability keys that name no capability: {unknown}"


def test_every_example_validates_against_its_capability_inputs() -> None:
    """Keys, required keys, types, ranges, enums and patterns are the manifest's."""
    failures: list[str] = []
    grouped = _examples_by_capability()
    for capability, pieces in grouped.items():
        for piece in pieces:
            errors = _problems(piece)
            if errors:
                failures.append(f"{capability} ({piece.relative_to(ROOT)}): {errors}")
    assert not failures, failures


def test_no_untagged_toml_shadows_a_capability() -> None:
    """Rule 2 assigns by file stem: a fixture named like a capability would win.

    ``facet example`` copies the first example in path order, so an untagged
    score named ``demo.toml`` would be copied as the piece and fail.
    """
    failures: list[str] = []
    for name, manifest in _manifests():
        for piece in sorted((PACKAGES / name / "examples").rglob("*.toml")):
            data = tomllib.loads(piece.read_text(encoding="utf-8"))
            if isinstance(data.get("capability"), str):
                continue
            if piece.stem in manifest["capabilities"]:
                failures.append(f"{piece.relative_to(ROOT)}: stem matches a capability")
    assert not failures, failures


def test_every_path_an_example_names_exists_beside_it() -> None:
    """A path input resolves from the piece's directory; a missing one is dead."""
    failures: list[str] = []
    grouped = _examples_by_capability()
    for capability, pieces in grouped.items():
        for piece in pieces:
            errors = [error for error in _problems(piece) if "not_found" in error]
            if errors:
                failures.append(f"{capability} ({piece.relative_to(ROOT)}): {errors}")
    assert not failures, failures
