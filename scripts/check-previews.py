# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "jsonschema==4.26.0",
# ]
# ///

"""Validate preview examples against their JSON Schemas.

Every ``<kind>.schema.json`` must be a valid draft 2020-12 schema, its
``examples/<kind>.json`` must pass and its ``examples/<kind>.invalid.json``
must fail. Every example file must have a schema of its own. Exits non-zero
when any check fails. Package specs reuse it on the preview files their
runners write.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

SDIR = Path(__file__).resolve().parents[1] / "schemas" / "preview"


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def check_schema_file(schema_path: Path) -> bool:
    try:
        schema = read_json(schema_path)
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as exc:
        print(f"FAIL {schema_path.name}: bad schema ({exc})")
        return False
    print(f"OK {schema_path.name}: schema valid")
    return True


def check_example(kind: str, schema: dict[str, Any]) -> bool:
    path = SDIR / "examples" / f"{kind}.json"
    if not path.exists():
        print(f"FAIL {path.name}: missing example")
        return False
    try:
        Draft202012Validator(schema).validate(read_json(path))
    except (OSError, ValueError, ValidationError) as exc:
        print(f"FAIL {path.name}: should pass ({exc})")
        return False
    print(f"OK {path.name}: valid")
    return True


def check_invalid(kind: str, schema: dict[str, Any]) -> bool:
    path = SDIR / "examples" / f"{kind}.invalid.json"
    if not path.exists():
        print(f"FAIL {path.name}: missing invalid example")
        return False
    try:
        instance = read_json(path)
    except (OSError, ValueError) as exc:
        print(f"FAIL {path.name}: unreadable ({exc})")
        return False
    try:
        Draft202012Validator(schema).validate(instance)
    except ValidationError:
        print(f"OK {path.name}: correctly rejected")
        return True
    print(f"FAIL {path.name}: should fail validation")
    return False


def check_orphans(schema_paths: list[Path]) -> bool:
    """Every example file must have a schema of its own to validate against."""
    ok = True
    for path in sorted((SDIR / "examples").glob("*.json")):
        name = path.name
        kind = name.removesuffix(".invalid.json").removesuffix(".json")
        if SDIR / f"{kind}.schema.json" not in schema_paths:
            print(f"FAIL {name}: no {kind}.schema.json to validate it against")
            ok = False
    return ok


def check_pair(schema_path: Path) -> bool:
    if not check_schema_file(schema_path):
        return False
    kind = schema_path.name.removesuffix(".schema.json")
    try:
        schema = read_json(schema_path)
    except (OSError, ValueError):
        return False
    if not isinstance(schema, dict):
        return False
    ok = check_example(kind, schema)
    return check_invalid(kind, schema) and ok


def check_file(path: Path) -> bool:
    """Validate one preview file against the schema of its declared ``kind``.

    Package specs use this on the preview files their runners write:
    ``uv run scripts/check-previews.py build/clip.wav.preview.json``.
    """
    try:
        data = read_json(path)
    except (OSError, ValueError) as exc:
        print(f"FAIL {path}: unreadable ({exc})")
        return False
    if not isinstance(data, dict):
        print(f"FAIL {path}: the preview is not a JSON object")
        return False
    kind = data.get("kind")
    if not isinstance(kind, str) or not kind:
        print(f"FAIL {path}: the preview names no kind")
        return False
    schema_path = SDIR / f"{kind}.schema.json"
    if not schema_path.is_file():
        print(f"FAIL {path}: no {schema_path.name} for kind {kind!r}")
        return False
    try:
        schema = read_json(schema_path)
        Draft202012Validator(schema).validate(data)
    except (OSError, ValueError, SchemaError, ValidationError) as exc:
        print(f"FAIL {path.name}: should pass ({exc})")
        return False
    print(f"OK {path.name}: valid against {schema_path.name}")
    return True


def main() -> int:
    files = [Path(argument) for argument in sys.argv[1:]]
    if files:
        ok = True
        for path in files:
            ok = check_file(path) and ok
        return 0 if ok else 1
    schemas = sorted(SDIR.glob("*.schema.json"))
    if not schemas:
        print("FAIL: no schemas found")
        return 1
    ok = check_orphans(schemas)
    for schema_path in schemas:
        ok = check_pair(schema_path) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
