"""The bluesky dry run: rendering, warnings and refusals, nothing sent.

The dry run sends nothing and writes nothing, so these tests run the
runner in-process against a stub ``facet_runner_sdk`` and fail any test
that touches the network: ``xrpc_client`` answers only when a test
replaces it. The refusals below are the runner's own checks for what the
manifest schema cannot express — a piece that still passed with one of
them removed would be sent back.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import struct
import sys
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "bluesky"
HANDLE = "lab.univerlab.org"


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
    if "bluesky_runner" in sys.modules:
        return sys.modules["bluesky_runner"]
    spec = importlib.util.spec_from_file_location("bluesky_runner", PACKAGE / "runner.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bluesky_runner"] = module
    with contextlib.suppress(SystemExit):
        spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the dry run must not touch the network")

    for name in (
        "create_session",
        "pds_for",
        "upload_blob",
        "create_record",
        "get_posts",
        "get_record",
        "resolve_handle",
        "get_profile",
    ):
        monkeypatch.setattr(RUNNER.xrpc_client, name, _boom)


@pytest.fixture()
def piece(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("FACET_SECRET_HANDLE", HANDLE)
    monkeypatch.setenv("FACET_SECRET_APP_PASSWORD", "hunter2")
    png = tmp_path / "banco.png"
    png.write_bytes(_png(64, 48))
    return {"dir": tmp_path, "png": png}


def _png(width: int, height: int) -> bytes:
    header = struct.pack(">8sI4sII", b"\x89PNG\r\n\x1a\n", 13, b"IHDR", width, height)
    return header + b"\x00" * 8


def _request(tmp_path: Path, inputs: dict[str, Any]) -> Any:
    return STUB.Request(
        {
            "verb": "dry-run",
            "capability": "bluesky.post",
            "inputs": inputs,
            "out_dir": str(tmp_path),
            "piece_dir": str(tmp_path),
        }
    )


def _inputs(png: Path, **over: Any) -> dict[str, Any]:
    posts: Any = over.get(
        "posts",
        [
            {"text": "La escuadra, recién salida del banco. #taller", "lang": "es"},
            {"text": "El plano queda en el catálogo.", "lang": "es"},
        ],
    )
    images: Any = over.get(
        "images", [{"post": 1, "path": str(png), "alt": "La escuadra sobre la mesa."}]
    )
    return {"posts": posts, "images": images}


def test_dry_run_renders_every_post_with_account_media_and_cost(
    tmp_path: Path, piece: dict[str, Any]
) -> None:
    result = RUNNER.runner._verbs["dry-run"](_request(tmp_path, _inputs(piece["png"])))
    assert [post["text"] for post in result["posts"]] == [
        "La escuadra, recién salida del banco. #taller",
        "El plano queda en el catálogo.",
    ]
    assert [post["account"] for post in result["posts"]] == [HANDLE, HANDLE]
    assert result["posts"][0]["media"] == [str(piece["png"])]
    assert result["posts"][1]["media"] == []
    assert all(post["cost"] is None for post in result["posts"])
    assert all(post["warnings"] == [] for post in result["posts"])
    assert result["warnings"] == []


def test_dry_run_names_the_handle_from_the_secrets_store(
    tmp_path: Path, piece: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACET_SECRET_HANDLE", "taller.example.org")
    result = RUNNER.runner._verbs["dry-run"](_request(tmp_path, _inputs(piece["png"])))
    assert result["posts"][0]["account"] == "taller.example.org"


def test_dry_run_warns_about_over_long_text(tmp_path: Path, piece: dict[str, Any]) -> None:
    long_text = "x" * 301
    inputs = _inputs(piece["png"], posts=[{"text": long_text}])
    result = RUNNER.runner._verbs["dry-run"](_request(tmp_path, inputs))
    assert len(result["posts"]) == 1
    assert any("301" in warning and "300" in warning for warning in result["posts"][0]["warnings"])


def test_dry_run_warns_about_an_image_over_the_limit(tmp_path: Path, piece: dict[str, Any]) -> None:
    big = tmp_path / "grande.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 1_000_001)
    inputs = _inputs(piece["png"], images=[{"post": 1, "path": str(big), "alt": "Grande."}])
    result = RUNNER.runner._verbs["dry-run"](_request(tmp_path, inputs))
    assert any(
        "1_000_000" in warning or "1000000" in warning for warning in result["posts"][0]["warnings"]
    )


def test_dry_run_warns_about_a_card_without_thumbnail(
    tmp_path: Path, piece: dict[str, Any]
) -> None:
    posts = [
        {
            "text": "El plano queda en el catálogo.",
            "card-url": "https://univerlab.org/catalogo/escuadra",
            "card-title": "Escuadra de banco",
            "card-description": "Plano y cotas.",
        }
    ]
    result = RUNNER.runner._verbs["dry-run"](
        _request(tmp_path, _inputs(piece["png"], posts=posts, images=[]))
    )
    assert any("thumbnail" in warning for warning in result["posts"][0]["warnings"])


def test_dry_run_refuses_an_image_without_alt_text(tmp_path: Path, piece: dict[str, Any]) -> None:
    images = [{"post": 1, "path": str(piece["png"]), "alt": ""}]
    with pytest.raises(ValueError, match="alt text"):
        RUNNER.runner._verbs["dry-run"](_request(tmp_path, _inputs(piece["png"], images=images)))


def test_dry_run_refuses_a_fifth_image_on_one_post(tmp_path: Path, piece: dict[str, Any]) -> None:
    images = [{"post": 1, "path": str(piece["png"]), "alt": f"Vista {n}."} for n in range(5)]
    with pytest.raises(ValueError, match="at most 4"):
        RUNNER.runner._verbs["dry-run"](_request(tmp_path, _inputs(piece["png"], images=images)))


def test_dry_run_refuses_video_with_images(tmp_path: Path, piece: dict[str, Any]) -> None:
    clip = tmp_path / "corte.mp4"
    clip.write_bytes(b"\x00" * 64)
    posts = [{"text": "El corte.", "video": str(clip)}]
    images = [{"post": 1, "path": str(piece["png"]), "alt": "La escuadra."}]
    with pytest.raises(ValueError, match="video"):
        RUNNER.runner._verbs["dry-run"](
            _request(tmp_path, _inputs(piece["png"], posts=posts, images=images))
        )


def test_dry_run_lists_a_video_post_media(tmp_path: Path, piece: dict[str, Any]) -> None:
    clip = tmp_path / "corte.mp4"
    clip.write_bytes(b"\x00" * 64)
    posts = [{"text": "El corte.", "video": str(clip)}]
    result = RUNNER.runner._verbs["dry-run"](
        _request(tmp_path, _inputs(piece["png"], posts=posts, images=[]))
    )
    assert result["posts"][0]["media"] == [str(clip)]
    assert result["posts"][0]["warnings"] == []


def test_dry_run_refuses_media_with_a_card(tmp_path: Path, piece: dict[str, Any]) -> None:
    posts = [
        {
            "text": "El plano.",
            "card-url": "https://univerlab.org/catalogo",
            "card-title": "Catálogo",
            "card-description": "El plano.",
        }
    ]
    images = [{"post": 1, "path": str(piece["png"]), "alt": "La escuadra."}]
    with pytest.raises(ValueError, match="one embed"):
        RUNNER.runner._verbs["dry-run"](
            _request(tmp_path, _inputs(piece["png"], posts=posts, images=images))
        )


def test_dry_run_refuses_a_card_without_its_title(tmp_path: Path, piece: dict[str, Any]) -> None:
    posts = [{"text": "El plano.", "card-url": "https://univerlab.org/catalogo"}]
    with pytest.raises(ValueError, match="card-title"):
        RUNNER.runner._verbs["dry-run"](
            _request(tmp_path, _inputs(piece["png"], posts=posts, images=[]))
        )


def test_dry_run_refuses_an_image_on_no_post(tmp_path: Path, piece: dict[str, Any]) -> None:
    images = [{"post": 3, "path": str(piece["png"]), "alt": "La escuadra."}]
    with pytest.raises(ValueError, match="no post"):
        RUNNER.runner._verbs["dry-run"](_request(tmp_path, _inputs(piece["png"], images=images)))
