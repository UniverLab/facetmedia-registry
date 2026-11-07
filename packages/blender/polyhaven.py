"""Fetch CC0 skies, textures and models from Poly Haven into the models dir.

Ported from the Grafics lab's ``tools/polyhaven.py``: the API records, the
fixed file names and the per-file size skip plus md5 check move verbatim, so
scene scripts find ``<id>/sky.hdr``, ``<id>/diff.jpg`` or ``<id>/<id>.gltf``
without guessing. Stdlib only. All Poly Haven assets are CC0: no attribution
needed, commercial use allowed.

Two adaptations for facet: the API base comes from ``POLYHAVEN_API`` (the
real one by default, a local stub in tests), and ``pick`` raises
``RuntimeError`` instead of ``SystemExit`` so a missing resolution fails the
run like every other fetch error. Models reporting more than
``MAX_POLYGONS`` polygons are refused before anything downloads — the lab's
rule, read from ``info/<id>`` first.
"""

import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_API = "https://api.polyhaven.com"
USER_AGENT = "grafics-lab/1.0"  # Poly Haven asks API clients to identify themselves
TEXTURE_MAPS = {"Diffuse": "diff.jpg", "nor_gl": "nor_gl.jpg", "Rough": "rough.jpg"}
TYPES = {0: "sky", 1: "texture", 2: "model"}
#: The lab's observed extreme; island_tree_01 sits just under at 3,729,692.
MAX_POLYGONS = 4_000_000


def _api() -> str:
    """The API base: the real Poly Haven unless a stub is configured."""
    return os.environ.get("POLYHAVEN_API") or DEFAULT_API


def get_json(path: str) -> Any:
    request = urllib.request.Request(f"{_api()}/{path}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def download(entry: dict[str, Any], target: Path) -> str:
    """entry is a Poly Haven file record: {url, size, md5}. Returns its md5."""
    if target.exists() and target.stat().st_size == entry["size"]:
        return str(entry["md5"])
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(entry["url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        data = response.read()
    if hashlib.md5(data).hexdigest() != entry["md5"]:
        raise RuntimeError(f"md5 mismatch for {entry['url']}")
    target.write_bytes(data)
    return str(entry["md5"])


def pick(levels: dict[str, Any], resolution: str, asset_id: str) -> dict[str, Any]:
    if resolution in levels:
        return levels[resolution]
    raise RuntimeError(f"{asset_id}: no {resolution} version (available: {', '.join(levels)})")


def fetch(asset_id: str, resolution: str | None, root: Path) -> dict[str, Any]:
    """Fetch one asset into ``root/<id>/`` and return its receipt entry.

    The receipt records every file with the path relative to ``root/<id>/``,
    its byte size and the md5 Poly Haven published, so ``verify`` can re-check
    the set without the network.
    """
    info = get_json(f"info/{asset_id}")
    kind = TYPES[info["type"]]
    if kind == "model":
        polycount = int(info.get("polycount") or 0)
        if polycount > MAX_POLYGONS:
            raise RuntimeError(f"{asset_id}: {polycount} polygons, over the {MAX_POLYGONS} limit")
    resolution = resolution or ("1k" if kind == "model" else "2k")
    files, folder = get_json(f"files/{asset_id}"), root / asset_id
    got: list[tuple[Path, str]] = []

    def grab(entry: dict[str, Any], target: Path) -> None:
        got.append((target, download(entry, target)))

    if kind == "sky":
        grab(pick(files["hdri"], resolution, asset_id)["hdr"], folder / "sky.hdr")
    elif kind == "texture":
        for key, name in TEXTURE_MAPS.items():
            lookup = key
            if key == "Diffuse" and key not in files:  # sold in several colours: col_1, col_2, ...
                lookup = min(k for k in files if k.startswith("col"))
            grab(pick(files[lookup], resolution, asset_id)["jpg"], folder / name)
    else:
        gltf = pick(files["gltf"], resolution, asset_id)["gltf"]
        grab(gltf, folder / f"{asset_id}.gltf")
        for relative, entry in gltf["include"].items():
            grab(entry, folder / relative)
    return {
        "id": asset_id,
        "type": kind,
        "res": resolution,
        "files": [
            {
                "path": str(target.relative_to(folder)),
                "bytes": target.stat().st_size,
                "md5": md5,
            }
            for target, md5 in got
        ],
    }
