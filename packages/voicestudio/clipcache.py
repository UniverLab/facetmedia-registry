"""Verified-clip cache for the voicestudio package.

Clips live under ``<FACET_HOME|~/.facet>/data/voicestudio/clip-cache``. Only
clips that passed verification when produced are stored. Lookup touches mtime;
store evicts oldest by mtime so the cache stays at or below 1 GiB.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

CAP_BYTES = 1024 * 1024 * 1024


def _home() -> Path:
    return Path(os.environ.get("FACET_HOME") or str(Path.home() / ".facet"))


def cache_dir() -> Path:
    return _home() / "data" / "voicestudio" / "clip-cache"


def enabled(params: dict[str, Any]) -> bool:
    return bool(params.get("cache", True))


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def key(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def attempt_key(
    clip: dict[str, Any],
    seed: int,
    tool_version: str,
) -> str:
    return key(
        {
            "tool_version": tool_version,
            "model": clip["model"],
            "voice": clip["voice"],
            "text": clip["text"],
            "language": clip["language"],
            "num_step": clip.get("num_step"),
            "guidance_scale": clip.get("guidance_scale"),
            "seed": int(seed),
        }
    )


def _path(digest: str) -> Path:
    return cache_dir() / f"{digest}.wav"


def lookup(digest: str, dest: Path) -> bool:
    """Copy a cached clip to ``dest`` if present, touching its mtime. Return hit."""
    src = _path(digest)
    if not src.is_file():
        return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        os.utime(src, None)
    except OSError:
        return False
    return True


def _evict(folder: Path) -> None:
    try:
        entries = [p for p in folder.iterdir() if p.is_file()]
    except OSError:
        return
    sized: list[tuple[float, int, Path]] = []
    total = 0
    for path in entries:
        try:
            st = path.stat()
        except OSError:
            continue
        sized.append((st.st_mtime, st.st_size, path))
        total += st.st_size
    if total <= CAP_BYTES:
        return
    sized.sort(key=lambda item: (item[0], item[2].name))
    for _mtime, size, path in sized:
        if total <= CAP_BYTES:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            continue


def store(digest: str, src: Path) -> None:
    """Store ``src`` in the cache and enforce the 1 GiB cap."""
    folder = cache_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, _path(digest))
    except OSError:
        return
    _evict(folder)
