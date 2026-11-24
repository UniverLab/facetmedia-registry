"""LinkedIn Member dry run: what lands on the personal profile, with no network touched."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import struct
import sys
import types
import zlib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "linkedin-member"


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
    for name in ("linkedin_member_runner", "linkedin_member_client"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("linkedin_member_runner", PACKAGE / "runner.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["linkedin_member_runner"] = module
    with contextlib.suppress(SystemExit):
        spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


def _png(width: int, height: int) -> bytes:
    row = b"\x00" + bytes([34, 41, 40]) * width
    raw = row * height

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = struct.pack(">I", len(data)) + kind + data
        return body + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    head = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", head)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture()
def files(tmp_path: Path) -> dict[str, Path]:
    still = tmp_path / "banco.png"
    still.write_bytes(_png(64, 48))
    return {"still": still, "dir": tmp_path}


@pytest.fixture()
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def bomb(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the dry run touched the network")

    for name in (
        "userinfo",
        "init_image_upload",
        "upload_image",
        "create_post",
        "get_post",
        "refresh_tokens",
        "exchange_code",
    ):
        monkeypatch.setattr(RUNNER.linkedin_member_client, name, bomb)
    monkeypatch.setattr(RUNNER.linkedin_member_client, "_exchange", bomb)


def _req(files: dict[str, Path], inputs: dict[str, Any]) -> Any:
    return STUB.Request(
        {
            "verb": "dry-run",
            "capability": "linkedin-member.post",
            "inputs": inputs,
            "out_dir": str(files["dir"]),
            "piece_dir": str(files["dir"]),
        }
    )


def _inputs(files: dict[str, Path], **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "text": "La escuadra del laboratorio. #taller",
        "images": [{"path": str(files["still"]), "alt": "La escuadra sobre el banco."}],
    }
    data.update(over)
    return data


def test_dry_run_names_text_unread_account_media_and_null_cost(
    files: dict[str, Path], offline: None
) -> None:
    result = RUNNER.runner._verbs["dry-run"](_req(files, _inputs(files)))
    assert len(result["posts"]) == 1
    post = result["posts"][0]
    assert post["text"] == "La escuadra del laboratorio. #taller"
    assert post["account"] == "@not-read"
    assert post["media"] == [str(files["still"])]
    assert post["warnings"] == []
    assert post["cost"] is None
    group = " ".join(result["warnings"]).lower()
    assert "public" in group and "personal" in group


def test_dry_run_text_only_carries_no_media(files: dict[str, Path], offline: None) -> None:
    result = RUNNER.runner._verbs["dry-run"](_req(files, _inputs(files, images=[])))
    assert result["posts"][0]["media"] == []


def test_dry_run_multiimage_warns_the_ride(files: dict[str, Path], offline: None) -> None:
    second = files["dir"] / "otra.png"
    second.write_bytes(_png(8, 8))
    inputs = _inputs(
        files,
        images=[
            {"path": str(files["still"]), "alt": "Una."},
            {"path": str(second), "alt": "Otra."},
        ],
    )
    result = RUNNER.runner._verbs["dry-run"](_req(files, inputs))
    assert any("multiimage" in warning.lower() for warning in result["posts"][0]["warnings"])


def test_dry_run_refuses_a_missing_text(files: dict[str, Path], offline: None) -> None:
    with pytest.raises(ValueError, match="no text"):
        RUNNER.runner._verbs["dry-run"](_req(files, _inputs(files, text="")))


def test_dry_run_refuses_more_than_twenty_images(files: dict[str, Path], offline: None) -> None:
    images = [{"path": str(files["still"]), "alt": f"Vista {n}."} for n in range(21)]
    with pytest.raises(ValueError, match="over the 20 limit"):
        RUNNER.runner._verbs["dry-run"](_req(files, _inputs(files, images=images)))


def test_dry_run_refuses_an_image_without_alt_text(files: dict[str, Path], offline: None) -> None:
    images = [{"path": str(files["still"]), "alt": ""}]
    with pytest.raises(ValueError, match="alt text"):
        RUNNER.runner._verbs["dry-run"](_req(files, _inputs(files, images=images)))


def test_dry_run_refuses_a_foreign_container(files: dict[str, Path], offline: None) -> None:
    other = files["dir"] / "nota.txt"
    other.write_text("not an image")
    images = [{"path": str(other), "alt": "Una nota."}]
    with pytest.raises(ValueError, match="JPG, GIF or PNG"):
        RUNNER.runner._verbs["dry-run"](_req(files, _inputs(files, images=images)))


def test_dry_run_warns_over_the_character_limit(
    files: dict[str, Path], offline: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER, "TEXT_LIMIT", 8)
    result = RUNNER.runner._verbs["dry-run"](_req(files, _inputs(files)))
    assert any("over the 8 limit" in warning for warning in result["posts"][0]["warnings"])
