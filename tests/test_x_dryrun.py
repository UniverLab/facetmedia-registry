"""The x dry run: rendering, URL counting, costs and refusals, nothing sent.

The dry run sends nothing and writes nothing, so these tests run the
runner in-process against a stub ``facet_runner_sdk`` and fail any test
that touches the network: ``x_client`` answers only when a test
replaces it. The refusals below are the runner's own checks for what the
manifest schema cannot express — a piece that still passed with one of
them removed would be sent back.
"""

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
PACKAGE = ROOT / "packages" / "x"
#: The bundled price table, read 2026-11-17, which the costs assert against.
POST_NO_URL = 0.015
POST_WITH_URL = 0.2
READ_POST = 0.005
READ_USER = 0.01
URL_LENGTH = 23
#: What one emoji, one CJK character or one other-Unicode code point weighs.
DOUBLE_WEIGHT = 2


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
        del name, value

    def announce_url(url: str) -> None:
        del url

    stub.Request = Request  # type: ignore[attr-defined]
    stub.Runner = Runner  # type: ignore[attr-defined]
    stub.secret = secret  # type: ignore[attr-defined]
    stub.renew_secret = renew_secret  # type: ignore[attr-defined]
    stub.announce_url = announce_url  # type: ignore[attr-defined]
    return stub


STUB = _stub_sdk()


def _load_runner() -> Any:
    sys.modules["facet_runner_sdk"] = STUB
    if "x_runner" in sys.modules:
        return sys.modules["x_runner"]
    spec = importlib.util.spec_from_file_location("x_runner", PACKAGE / "runner.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["x_runner"] = module
    with contextlib.suppress(SystemExit):
        spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the dry run must not touch the network")

    for name in (
        "whoami",
        "upload_media",
        "set_alt_text",
        "create_post",
        "get_posts",
        "probe_write",
    ):
        monkeypatch.setattr(RUNNER.x_client, name, _boom)


@pytest.fixture()
def piece(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    for name in ("CONSUMER_KEY", "CONSUMER_SECRET", "ACCESS_TOKEN", "ACCESS_TOKEN_SECRET"):
        monkeypatch.setenv(f"FACET_SECRET_{name}", "s3cr3t")
    png = tmp_path / "banco.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    return {"dir": tmp_path, "png": png}


def _request(tmp_path: Path, inputs: dict[str, Any]) -> Any:
    return STUB.Request(
        {
            "verb": "dry-run",
            "capability": "x.post",
            "inputs": inputs,
            "out_dir": str(tmp_path),
            "piece_dir": str(tmp_path),
        }
    )


def _inputs(png: Path, **over: Any) -> dict[str, Any]:
    posts: Any = over.get(
        "posts",
        [
            {"text": "La escuadra, recién salida del banco. #taller"},
            {"text": "El plano queda en el catálogo."},
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
    assert all(post["account"] == "@not-read" for post in result["posts"])
    assert result["posts"][0]["media"] == [str(piece["png"])]
    assert result["posts"][1]["media"] == []
    assert result["posts"][0]["cost"] == {"amount": POST_NO_URL, "currency": "USD"}
    assert result["posts"][1]["cost"] == {"amount": POST_NO_URL, "currency": "USD"}
    assert result["warnings"]


def test_dry_run_counts_a_url_at_its_fixed_length() -> None:
    rates = RUNNER._rates()
    assert rates.url_length == URL_LENGTH
    text = "Mira https://univerlab.org/una/ruta/muy/larga/que/sigue/y/sigue"
    assert RUNNER._char_count(text, rates) == len("Mira ") + URL_LENGTH


def test_dry_run_counts_emoji_cjk_and_nfc_the_way_x_does() -> None:
    rates = RUNNER._rates()
    assert RUNNER._char_count("hola", rates) == len("hola")
    assert RUNNER._char_count("\U0001f47e", rates) == DOUBLE_WEIGHT
    assert RUNNER._char_count("\U0001f64b\U0001f3fd", rates) == DOUBLE_WEIGHT
    assert RUNNER._char_count("\U0001f468\u200d\U0001f3a4", rates) == DOUBLE_WEIGHT
    assert RUNNER._char_count("\U0001f468\u200d\U0001f469\u200d\U0001f467", rates) == DOUBLE_WEIGHT
    assert RUNNER._char_count("\U0001f1ea\U0001f1f8", rates) == DOUBLE_WEIGHT
    assert RUNNER._char_count("\u6f22", rates) == DOUBLE_WEIGHT
    assert RUNNER._char_count("caf\u00e9", rates) == len("caf\u00e9")
    assert RUNNER._char_count("cafe\u0301", rates) == len("caf\u00e9")


def test_dry_run_prices_a_post_with_a_url_above_text_only(
    tmp_path: Path, piece: dict[str, Any]
) -> None:
    posts = [
        {"text": "Solo texto."},
        {"text": "Lee https://univerlab.org/catalogo/escuadra ya."},
    ]
    result = RUNNER.runner._verbs["dry-run"](
        _request(tmp_path, _inputs(piece["png"], posts=posts, images=[]))
    )
    assert result["posts"][0]["cost"] == {"amount": POST_NO_URL, "currency": "USD"}
    assert result["posts"][1]["cost"] == {"amount": POST_WITH_URL, "currency": "USD"}
    assert any("URL" in warning for warning in result["posts"][1]["warnings"])
    flat = " ".join(result["warnings"])
    assert "2026-11-17" in flat


def test_dry_run_itemizes_every_post_and_the_read_back(
    tmp_path: Path, piece: dict[str, Any]
) -> None:
    posts = [{"text": "Solo texto."}, {"text": "Lee https://univerlab.org/x ya."}]
    result = RUNNER.runner._verbs["dry-run"](
        _request(tmp_path, _inputs(piece["png"], posts=posts, images=[]))
    )
    flat = " ".join(result["warnings"])
    assert "post 1: $0.015" in flat
    assert "post 2: $0.200" in flat
    assert f"read-back: ${READ_POST * 2:.3f}" in flat
    assert f"account read: ${READ_USER:.3f}" in flat
    assert "total: $0.235" in flat
    assert "2026-11-17" in flat


def test_dry_run_warns_about_over_long_text(tmp_path: Path, piece: dict[str, Any]) -> None:
    long_text = "x" * 281
    inputs = _inputs(piece["png"], posts=[{"text": long_text}], images=[])
    result = RUNNER.runner._verbs["dry-run"](_request(tmp_path, inputs))
    assert len(result["posts"]) == 1
    assert any("281" in warning and "280" in warning for warning in result["posts"][0]["warnings"])


def test_dry_run_warns_about_an_image_over_the_limit(tmp_path: Path, piece: dict[str, Any]) -> None:
    big = tmp_path / "grande.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024 + 1))
    inputs = _inputs(piece["png"], images=[{"post": 1, "path": str(big), "alt": "Grande."}])
    result = RUNNER.runner._verbs["dry-run"](_request(tmp_path, inputs))
    assert any("5242880" in warning for warning in result["posts"][0]["warnings"])


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


def test_dry_run_refuses_video_with_gif(tmp_path: Path, piece: dict[str, Any]) -> None:
    clip = tmp_path / "corte.mp4"
    clip.write_bytes(b"\x00" * 64)
    loop = tmp_path / "giro.gif"
    loop.write_bytes(b"GIF89a" + b"\x00" * 64)
    posts = [{"text": "El corte.", "video": str(clip), "gif": str(loop)}]
    with pytest.raises(ValueError, match="one video or GIF"):
        RUNNER.runner._verbs["dry-run"](
            _request(tmp_path, _inputs(piece["png"], posts=posts, images=[]))
        )


def test_dry_run_lists_a_video_and_a_gif_post_media(tmp_path: Path, piece: dict[str, Any]) -> None:
    clip = tmp_path / "corte.mp4"
    clip.write_bytes(b"\x00" * 64)
    loop = tmp_path / "giro.gif"
    loop.write_bytes(b"GIF89a" + b"\x00" * 64)
    video = _inputs(piece["png"], posts=[{"text": "El corte.", "video": str(clip)}], images=[])
    gif = _inputs(piece["png"], posts=[{"text": "El giro.", "gif": str(loop)}], images=[])
    assert RUNNER.runner._verbs["dry-run"](_request(tmp_path, video))["posts"][0]["media"] == [
        str(clip)
    ]
    assert RUNNER.runner._verbs["dry-run"](_request(tmp_path, gif))["posts"][0]["media"] == [
        str(loop)
    ]


def test_dry_run_refuses_an_image_on_no_post(tmp_path: Path, piece: dict[str, Any]) -> None:
    images = [{"post": 3, "path": str(piece["png"]), "alt": "La escuadra."}]
    with pytest.raises(ValueError, match="no post"):
        RUNNER.runner._verbs["dry-run"](_request(tmp_path, _inputs(piece["png"], images=images)))
