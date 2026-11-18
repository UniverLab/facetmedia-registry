"""The post preview schema and the receipt fixture every post viewer reads.

The registry suite runs without the core and without ``jsonschema``, so this
file re-applies the draft-2020-12 keywords the preview schemas use, and the
served-name rule facet's preview server applies: only names that resolve to a
file inside the receipt's own directory reach the viewer, never an absolute
path and never one that climbs out with ``..``.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "schemas" / "preview"
EXAMPLES = PREVIEW / "examples"
FIXTURE = ROOT / "viewers" / "_examples" / "post"
RECEIPT = "hilo.post.json"
GALLERY = ROOT / "viewers" / "_examples" / "gallery.json"
VIEWERS = ROOT / "viewers"
STATES = ("published", "draft", "private", "scheduled", "unknown")
#: The preview, its posts and their media: every object schema is closed.
OBJECT_SCHEMAS = 3
#: The JSON types ``isinstance`` answers directly.
PRIMITIVES = {"object": dict, "array": list, "string": str, "boolean": bool}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _matches(kind: str, value: Any) -> bool:
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if kind == "null":
        return value is None
    expected = PRIMITIVES.get(kind)
    return True if expected is None else isinstance(value, expected)


def _type_problems(schema: dict[str, Any], value: Any, path: str) -> list[str]:
    declared = schema.get("type")
    if declared is None:
        return []
    kinds = [declared] if isinstance(declared, str) else list(declared)
    if any(_matches(kind, value) for kind in kinds):
        return []
    return [f"{path}: type {kinds}, not {type(value).__name__}"]


def _string_problems(schema: dict[str, Any], value: str, path: str) -> list[str]:
    problems: list[str] = []
    if len(value) < schema.get("minLength", 0):
        problems.append(f"{path}: shorter than {schema['minLength']}")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        problems.append(f"{path}: longer than {schema['maxLength']}")
    pattern = schema.get("pattern")
    if pattern is not None and re.search(pattern, value) is None:
        problems.append(f"{path}: {value!r} matches no {pattern}")
    if schema.get("format") == "uri" and not urlparse(value).scheme:
        problems.append(f"{path}: {value!r} is not a uri")
    return problems


def _array_problems(schema: dict[str, Any], value: list[Any], path: str) -> list[str]:
    problems: list[str] = []
    if len(value) < schema.get("minItems", 0):
        problems.append(f"{path}: fewer than {schema['minItems']}")
    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for index, item in enumerate(value):
            problems.extend(_problems(item_schema, item, f"{path}[{index}]"))
    return problems


def _object_problems(schema: dict[str, Any], value: dict[str, Any], path: str) -> list[str]:
    problems: list[str] = []
    properties = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in value:
            problems.append(f"{path}.{key}: required")
    if schema.get("additionalProperties") is False:
        problems.extend(f"{path}.{key}: not allowed" for key in value if key not in properties)
    for key, value_schema in properties.items():
        if key in value:
            problems.extend(_problems(value_schema, value[key], f"{path}.{key}"))
    return problems


def _problems(schema: dict[str, Any], value: Any, path: str = "$") -> list[str]:
    """The problems this value has against the schema's own keywords."""
    problems = _type_problems(schema, value, path)
    if "const" in schema and value != schema["const"]:
        problems.append(f"{path}: not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: not one of {schema['enum']}")
    if isinstance(value, str):
        problems.extend(_string_problems(schema, value, path))
    elif isinstance(value, list):
        problems.extend(_array_problems(schema, value, path))
    elif isinstance(value, dict):
        problems.extend(_object_problems(schema, value, path))
    return problems


def _object_nodes(node: Any, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    """Every object subschema, so each one can be asked for its closed shape."""
    found: list[tuple[str, dict[str, Any]]] = []
    if not isinstance(node, dict):
        return found
    if node.get("type") == "object":
        found.append((path, node))
    properties = node.get("properties")
    if isinstance(properties, dict):
        for name, child in properties.items():
            found.extend(_object_nodes(child, f"{path}.{name}"))
    items = node.get("items")
    if isinstance(items, dict):
        found.extend(_object_nodes(items, f"{path}[]"))
    return found


def _refs(node: Any) -> list[str]:
    """Every ``$ref`` the schema names; the preview schemas may name none."""
    if isinstance(node, dict):
        own = [node["$ref"]] if "$ref" in node else []
        return own + [ref for value in node.values() for ref in _refs(value)]
    if isinstance(node, list):
        return [ref for value in node for ref in _refs(value)]
    return []


def served_names(preview: dict[str, Any], asset_dir: Path) -> list[str]:
    """The preview's images as paths relative to ``asset_dir``.

    facet serves ``images``, every ``views[].file`` and the document ``pages``,
    each resolved inside the asset's directory; anything absolute, climbing
    out with ``..`` or missing is silently dropped.
    """
    names: list[str] = []
    images = preview.get("images")
    if isinstance(images, list):
        names.extend(item for item in images if isinstance(item, str))
    views = preview.get("views")
    if isinstance(views, list):
        names.extend(
            view["file"]
            for view in views
            if isinstance(view, dict) and isinstance(view.get("file"), str)
        )
    pages = preview.get("pages")
    if isinstance(pages, list):
        names.extend(item for item in pages if isinstance(item, str))
    base = asset_dir.resolve()
    found: list[str] = []
    for name in names:
        if not name or name.startswith("/") or ".." in Path(name).parts:
            continue
        resolved = (asset_dir / name).resolve()
        if not resolved.is_relative_to(base) or not resolved.is_file():
            continue
        relative = resolved.relative_to(base).as_posix()
        if relative not in found:
            found.append(relative)
    return found


def test_the_example_pair_passes_and_fails() -> None:
    schema = _read_json(PREVIEW / "post.schema.json")
    assert not _problems(schema, _read_json(EXAMPLES / "post.json"))
    invalid = _read_json(EXAMPLES / "post.invalid.json")
    assert invalid["state"] == "live"
    assert _problems(schema, invalid)


def test_the_schema_is_closed_2020_12_without_refs() -> None:
    schema = _read_json(PREVIEW / "post.schema.json")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["kind"]["const"] == "post"
    assert schema["properties"]["preview"]["const"] == 1
    assert schema["properties"]["state"]["enum"] == list(STATES)
    assert _refs(schema) == []
    objects = _object_nodes(schema)
    assert len(objects) == OBJECT_SCHEMAS, "the post, its media and the preview are objects"
    for path, node in objects:
        assert node.get("additionalProperties") is False, f"{path} is not closed"


def test_the_receipt_keeps_only_ids_and_urls() -> None:
    receipt = _read_json(FIXTURE / RECEIPT)
    preview = _read_json(FIXTURE / f"{RECEIPT}.preview.json")
    assert receipt["receipt"] == 1
    assert set(receipt) == {
        "receipt",
        "network",
        "account",
        "state",
        "posts",
        "sources",
        "cost",
        "sent_at",
        "verified_at",
    }
    assert receipt["posts"]
    for post in receipt["posts"]:
        assert set(post) == {"id", "url"}
    sent = json.dumps(receipt, ensure_ascii=False)
    for post in preview["posts"]:
        assert post["text"] not in sent, "the post's text lives only in the preview"


def test_the_fixture_record_describes_its_receipt() -> None:
    data = (FIXTURE / RECEIPT).read_bytes()
    record = _read_json(FIXTURE / f"{RECEIPT}.facet.json")
    assert record["kind"] == "post"
    assert record["mime"] == "application/json"
    assert record["path"] == RECEIPT
    assert record["id"] == f"sha256:{hashlib.sha256(data).hexdigest()}"
    assert record["bytes"] == len(data)
    assert record["provenance"]["capability"] == "publish.post"
    assert record["provenance"]["facet"] == "publish"


def test_the_fixture_is_a_verified_draft_so_the_viewer_marks_nothing() -> None:
    record = _read_json(FIXTURE / f"{RECEIPT}.facet.json")
    preview = _read_json(FIXTURE / f"{RECEIPT}.preview.json")
    assert record["verification"]["status"] == "passed"
    assert preview["state"] == "draft"
    assert record["properties"]["state"] == preview["state"]
    assert record["properties"]["network"] == preview["network"]
    assert record["properties"]["url"] == preview["posts"][0]["url"]
    assert preview["kind"] == record["kind"]


def test_the_fixture_preview_names_files_beside_the_receipt() -> None:
    preview = _read_json(FIXTURE / f"{RECEIPT}.preview.json")
    assert preview["images"]
    for name in preview["images"]:
        assert not name.startswith("/"), f"{name} is absolute"
        assert ".." not in Path(name).parts, f"{name} climbs out of the receipt"
        assert (FIXTURE / name).is_file(), f"{name} is not beside the receipt"
    media = [item["file"] for post in preview["posts"] for item in post["media"]]
    assert media
    assert set(media) <= set(preview["images"])


def test_the_fixture_rides_the_paths_facet_preview_serves() -> None:
    preview = _read_json(FIXTURE / f"{RECEIPT}.preview.json")
    served = served_names(preview, FIXTURE)
    assert "hilo-media.png" in served
    for post in preview["posts"]:
        for item in post["media"]:
            assert item["file"] in served, f"facet never serves {item['file']}"
    for name in (RECEIPT, f"{RECEIPT}.facet.json", f"{RECEIPT}.preview.json"):
        assert (FIXTURE / name).is_file(), f"the server cannot serve {name}"


def test_a_name_facet_would_drop_is_not_served() -> None:
    preview = {
        "images": ["../outside.png", "/etc/passwd", "hilo-media.png"],
        "views": [{"file": "."}],
        "pages": ["hilo-media.png"],
    }
    assert served_names(preview, FIXTURE) == ["hilo-media.png"]


def test_the_gallery_lists_the_post_receipt_under_publish() -> None:
    cards = _read_json(GALLERY)["assets"]
    posts = [card for card in cards if card["kind"] == "post"]
    assert posts, "the gallery example carries no post receipt"
    assert posts[0]["facet"] == "publish"
    assert posts[0]["capability"] == "publish.post"
    assert posts[0]["open"] is not None
    gallery = (VIEWERS / "gallery" / "main.js").read_text(encoding="utf-8")
    assert '"publish"]' in gallery, "publish is the last facet in the gallery's order"
    assert 'publish: "✦",' in gallery


def test_the_index_labels_the_publish_facet() -> None:
    index = tomllib.loads((ROOT / "index.toml").read_text(encoding="utf-8"))
    assert index["facets"]["publish"]["label"] == "Publish"
    assert index["facets"]["publish"]["i18n"]["es"]["label"] == "Publicación"
