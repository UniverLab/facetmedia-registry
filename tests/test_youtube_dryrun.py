"""The youtube dry run: metadata, warnings and refusals, nothing sent."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sys
import tomllib
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "youtube"


def _stub_sdk() -> types.ModuleType:
    stub = types.ModuleType("facet_runner_sdk")

    class Request:
        def __init__(self, data: dict[str, Any]) -> None:
            self.verb = str(data.get("verb", ""))
            self.capability = str(data.get("capability", ""))
            self.depth = str(data.get("depth", "quick"))
            self.inputs = dict(data.get("inputs") or {})
            self.out_dir = Path(str(data.get("out_dir", "")))
            self.piece_dir = Path(str(data.get("piece_dir", "")))
            self.assets = [Path(str(item)) for item in data.get("assets") or []]
            self.sources = [item for item in data.get("sources") or []]
            self.post = dict(data.get("post") or {})

        @classmethod
        def from_file(cls, path: Path) -> Request:
            return cls(json.loads(path.read_text()))

    class Runner:
        def __init__(self) -> None:
            self._verbs: dict[str, Any] = {}

        def verb(self, name: str):  # type: ignore[no-untyped-def]
            def register(function):  # type: ignore[no-untyped-def]
                self._verbs[name] = function
                return function

            return register

        def main(self) -> None:
            raise SystemExit(0)

    def secret(name: str) -> str:
        variable = f"FACET_SECRET_{name.upper().replace('-', '_')}"
        try:
            return os.environ[variable]
        except KeyError:
            raise KeyError(f"secret {name} is not set; run facet secret set") from None

    stub.Request = Request  # type: ignore[attr-defined]
    stub.Runner = Runner  # type: ignore[attr-defined]
    stub.secret = secret  # type: ignore[attr-defined]
    return stub


STUB = _stub_sdk()


def _load_runner() -> Any:
    sys.modules["facet_runner_sdk"] = STUB
    for name in ("youtube_runner", "video_meta", "youtube_client"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("youtube_runner", PACKAGE / "runner.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["youtube_runner"] = module
    with contextlib.suppress(SystemExit):
        spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the dry run must not touch the network")

    for name in ("authorize", "channel", "upload_video", "set_thumbnail", "video_state"):
        monkeypatch.setattr(RUNNER.youtube_client, name, _boom, raising=False)


@pytest.fixture()
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00" * 64)
    return path


def _inputs(video: Path, **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "video": str(video),
        "title": "La escuadra",
        "description": "Recién salida del banco.",
        "tags": ["taller", "escuadra"],
        "category": "28",
        "privacy": "private",
        "made-for-kids": False,
        "notify-subscribers": True,
    }
    data.update(over)
    return data


def _request(tmp_path: Path, inputs: dict[str, Any], sources: list[Any] | None = None) -> Any:
    return STUB.Request(
        {
            "verb": "dry-run",
            "capability": "youtube.upload",
            "inputs": inputs,
            "out_dir": str(tmp_path),
            "piece_dir": str(tmp_path),
            "sources": sources or [],
        }
    )


def test_dry_run_shows_metadata_privacy_and_synthetic(
    tmp_path: Path, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER.video_meta, "probe", lambda path: None)
    result = RUNNER.runner._verbs["dry-run"](_request(tmp_path, _inputs(video)))
    assert len(result["posts"]) == 1
    post = result["posts"][0]
    assert post["text"] == "La escuadra\n\nRecién salida del banco."
    assert post["account"] == "@not-read"
    assert str(video) in post["media"]
    assert post["cost"] is None
    group = "\n".join(result["warnings"])
    assert "privacy: private" in group
    assert "synthetic: no" in group
    assert "made for kids: no" in group
    assert "category: 28" in group
    assert "tags: taller, escuadra" in group
    assert "notify subscribers: yes" in group


def test_dry_run_warns_for_title_and_description_limits(
    tmp_path: Path, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER.video_meta, "probe", lambda path: None)
    inputs = _inputs(video, title="x" * 101, description="y" * 5001)
    result = RUNNER.runner._verbs["dry-run"](_request(tmp_path, inputs))
    warnings = " ".join(result["posts"][0]["warnings"])
    assert "101" in warnings and "100" in warnings
    assert "5001" in warnings and "5000" in warnings


def test_dry_run_warns_when_vertical_video_under_shorts_length(
    tmp_path: Path, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = RUNNER.video_meta.VideoInfo(width=1080, height=1920, duration_s=59.0)
    monkeypatch.setattr(RUNNER.video_meta, "probe", lambda path: info)
    result = RUNNER.runner._verbs["dry-run"](_request(tmp_path, _inputs(video)))
    assert any("Short" in w for w in result["posts"][0]["warnings"])


def test_dry_run_refuses_missing_file(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path / "missing.mp4")
    with pytest.raises(ValueError):
        RUNNER.runner._verbs["dry-run"](_request(tmp_path, inputs))


def test_dry_run_forces_synthetic_for_generated_source(
    tmp_path: Path, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER.video_meta, "probe", lambda path: None)
    req = _request(tmp_path, _inputs(video, synthetic=False), sources=[{"generated": True}])
    result = RUNNER.runner._verbs["dry-run"](req)
    assert "synthetic: yes" in "\n".join(result["warnings"])


def test_dry_run_refuses_missing_made_for_kids(tmp_path: Path, video: Path) -> None:
    inputs = _inputs(video)
    inputs.pop("made-for-kids")
    with pytest.raises(ValueError, match="made-for-kids"):
        RUNNER.runner._verbs["dry-run"](_request(tmp_path, inputs))

    inputs_none = _inputs(video, **{"made-for-kids": None})
    with pytest.raises(ValueError, match="made-for-kids"):
        RUNNER.runner._verbs["dry-run"](_request(tmp_path, inputs_none))


def test_dry_run_bundled_example(tmp_path: Path) -> None:
    example = PACKAGE / "examples" / "upload.toml"
    data = tomllib.loads(example.read_text(encoding="utf-8"))
    req = STUB.Request(
        {
            "verb": "dry-run",
            "capability": data["capability"],
            "inputs": data["inputs"],
            "out_dir": str(tmp_path),
            "piece_dir": str(example.parent),
        }
    )
    result = RUNNER.runner._verbs["dry-run"](req)
    assert len(result["posts"]) == 1
    assert result["posts"][0]["account"] == "@not-read"
    assert "privacy: private" in "\n".join(result["warnings"])
