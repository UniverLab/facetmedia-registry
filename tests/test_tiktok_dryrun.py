"""TikTok dry run: what lands in the inbox, with no network touched."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "tiktok"


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

    def renew_secret(name: str, value: str) -> None:
        stub.renewals.append((name, value))  # type: ignore[attr-defined]

    stub.Request = Request  # type: ignore[attr-defined]
    stub.Runner = Runner  # type: ignore[attr-defined]
    stub.secret = secret  # type: ignore[attr-defined]
    stub.renew_secret = renew_secret  # type: ignore[attr-defined]
    stub.renewals = []  # type: ignore[attr-defined]
    return stub


STUB = _stub_sdk()


def _load_runner() -> Any:
    sys.modules["facet_runner_sdk"] = STUB
    for name in ("tiktok_runner", "tiktok_client"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("tiktok_runner", PACKAGE / "runner.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["tiktok_runner"] = module
    with contextlib.suppress(SystemExit):
        spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


@pytest.fixture()
def files(tmp_path: Path) -> dict[str, Path]:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    return {"video": video, "dir": tmp_path}


@pytest.fixture()
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def bomb(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the dry run touched the network")

    for name in (
        "creator_info",
        "user_info",
        "init_video_upload",
        "init_photo_upload",
        "publish_status",
        "refresh_tokens",
        "upload_chunk",
    ):
        monkeypatch.setattr(RUNNER.tiktok_client, name, bomb)
    monkeypatch.setattr(RUNNER.tiktok_client, "_call", bomb)


def _req(files: dict[str, Path], inputs: dict[str, Any]) -> Any:
    return STUB.Request(
        {
            "verb": "dry-run",
            "capability": "tiktok.post",
            "inputs": inputs,
            "out_dir": str(files["dir"]),
            "piece_dir": str(files["dir"]),
        }
    )


def _video_inputs(files: dict[str, Path], **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "caption": "La escuadra del laboratorio. #taller",
        "video": str(files["video"]),
    }
    data.update(over)
    return data


def test_dry_run_video_names_caption_inbox_and_paste(files: dict[str, Path], offline: None) -> None:
    result = RUNNER.runner._verbs["dry-run"](_req(files, _video_inputs(files)))
    assert len(result["posts"]) == 1
    post = result["posts"][0]
    assert post["text"] == "La escuadra del laboratorio. #taller"
    assert post["account"] == "@not-read"
    assert post["media"] == [str(files["video"])]
    assert post["warnings"] == []
    assert post["cost"] is None
    group = " ".join(result["warnings"]).lower()
    assert "inbox" in group and "draft" in group
    assert "paste" in group and "caption" in group


def test_dry_run_video_refuses_a_foreign_container(files: dict[str, Path], offline: None) -> None:
    other = files["dir"] / "clip.txt"
    other.write_text("not a video")
    with pytest.raises(ValueError, match="MP4"):
        RUNNER.runner._verbs["dry-run"](_req(files, _video_inputs(files, video=str(other))))


def test_dry_run_video_refuses_a_missing_file(files: dict[str, Path], offline: None) -> None:
    missing = files["dir"] / "gone.mp4"
    with pytest.raises(ValueError, match="not a file"):
        RUNNER.runner._verbs["dry-run"](_req(files, _video_inputs(files, video=str(missing))))


def test_dry_run_video_warns_over_the_size_limit(
    files: dict[str, Path], offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER, "VIDEO_LIMIT", 8)
    result = RUNNER.runner._verbs["dry-run"](_req(files, _video_inputs(files)))
    assert any("over" in warning for warning in result["posts"][0]["warnings"])


def test_dry_run_photos_echo_urls_and_warn_verified_domain(
    files: dict[str, Path], offline: None
) -> None:
    urls = [
        "https://fotos.univerlab.org/taller/escuadra-1.jpg",
        "https://fotos.univerlab.org/taller/escuadra-2.jpg",
    ]
    inputs = {
        "caption": "La escuadra, paso a paso.",
        "photos": [{"url": url} for url in urls],
    }
    result = RUNNER.runner._verbs["dry-run"](_req(files, inputs))
    post = result["posts"][0]
    assert post["text"] == "La escuadra, paso a paso."
    assert post["media"] == urls
    assert any("verif" in warning for warning in post["warnings"])
    group = " ".join(result["warnings"]).lower()
    assert "inbox" in group and "paste" in group


def test_dry_run_photos_refuse_plain_http(files: dict[str, Path], offline: None) -> None:
    inputs = {
        "caption": "La escuadra.",
        "photos": [{"url": "http://fotos.univerlab.org/taller/e-1.jpg"}],
    }
    with pytest.raises(ValueError, match="https"):
        RUNNER.runner._verbs["dry-run"](_req(files, inputs))


def test_dry_run_refuses_video_and_photos_together(files: dict[str, Path], offline: None) -> None:
    inputs = _video_inputs(files)
    inputs["photos"] = [{"url": "https://fotos.univerlab.org/taller/e-1.jpg"}]
    with pytest.raises(ValueError, match="exactly one"):
        RUNNER.runner._verbs["dry-run"](_req(files, inputs))


def test_dry_run_refuses_no_media(files: dict[str, Path], offline: None) -> None:
    with pytest.raises(ValueError, match="no video and no photos"):
        RUNNER.runner._verbs["dry-run"](_req(files, {"caption": "La escuadra."}))


def test_dry_run_refuses_a_missing_caption(files: dict[str, Path], offline: None) -> None:
    with pytest.raises(ValueError, match="no caption"):
        RUNNER.runner._verbs["dry-run"](_req(files, {"video": str(files["video"]), "caption": ""}))
