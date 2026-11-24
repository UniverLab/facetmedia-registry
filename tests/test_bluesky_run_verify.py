"""The bluesky send, read-back, preview and credential check, all offline.

The network is replaced, never touched: these tests run the runner
in-process against a stub ``facet_runner_sdk`` and a fake ``xrpc_client``
whose calls are recorded, so the reply chain, the uploaded blobs, the
facets and the read-back comparisons are the runner's own answers. A
test that still passed with the send removed would be sent back.
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
DID = "did:plc:lab123"
PDS = "https://pds.univerlab.org"


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


class FakeNet:
    """The whole network: sessions, blobs, records and profiles on demand."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.uploads: list[dict[str, Any]] = []
        self.counter = 0
        self.session_calls = 0

    def create_session(self, handle: str, password: str) -> dict[str, Any]:
        self.session_calls += 1
        assert handle == HANDLE
        assert password == "hunter2"
        return {"did": DID, "handle": handle, "accessJwt": "jwt", "refreshJwt": "refresh"}

    def pds_for(self, did: str) -> str:
        assert did == DID
        return PDS

    def resolve_handle(self, handle: str) -> str:
        if handle == "lab.univerlab.org":
            return DID
        raise RUNNER.xrpc_client.XrpcError("resolve", 400, "InvalidHandle")

    def upload_blob(
        self, host: str, token: str, path: str, data: bytes, mime: str
    ) -> dict[str, Any]:
        assert host == PDS and token == "jwt"
        self.uploads.append({"path": path, "bytes": len(data), "mime": mime})
        return {"ref": {"$link": f"blob{len(self.uploads)}"}, "mimeType": mime, "size": len(data)}

    def create_record(
        self, host: str, token: str, did: str, record: dict[str, Any]
    ) -> dict[str, str]:
        assert host == PDS and token == "jwt" and did == DID
        self.counter += 1
        rkey = f"3khilo{self.counter:02d}"
        self.records[rkey] = record
        return {"uri": f"at://{did}/app.bsky.feed.post/{rkey}", "cid": f"cid{self.counter}"}

    def get_record(self, host: str, did: str, collection: str, rkey: str) -> dict[str, Any]:
        assert host == PDS and did == DID
        if rkey not in self.records:
            raise RUNNER.xrpc_client.XrpcError("getRecord", 400, "RecordNotFound")
        return {"uri": f"at://{did}/{collection}/{rkey}", "cid": "cid", "value": self.records[rkey]}

    def get_profile(self, host: str, actor: str, *, token: str | None = None) -> dict[str, Any]:
        assert actor == DID
        return {"handle": HANDLE, "displayName": "Laboratorio"}


@pytest.fixture()
def net(monkeypatch: pytest.MonkeyPatch) -> FakeNet:
    fake = FakeNet()
    monkeypatch.setenv("FACET_SECRET_HANDLE", HANDLE)
    monkeypatch.setenv("FACET_SECRET_APP_PASSWORD", "hunter2")
    monkeypatch.setattr(RUNNER.xrpc_client, "create_session", fake.create_session)
    monkeypatch.setattr(RUNNER.xrpc_client, "pds_for", fake.pds_for)
    monkeypatch.setattr(RUNNER.xrpc_client, "resolve_handle", fake.resolve_handle)
    monkeypatch.setattr(RUNNER.xrpc_client, "upload_blob", fake.upload_blob)
    monkeypatch.setattr(RUNNER.xrpc_client, "create_record", fake.create_record)
    monkeypatch.setattr(RUNNER.xrpc_client, "get_record", fake.get_record)
    monkeypatch.setattr(RUNNER.xrpc_client, "get_profile", fake.get_profile)
    return fake


@pytest.fixture()
def png(tmp_path: Path) -> Path:
    path = tmp_path / "banco.png"
    path.write_bytes(
        struct.pack(">8sI4sII", b"\x89PNG\r\n\x1a\n", 13, b"IHDR", 64, 48) + b"\x00" * 8
    )
    return path


def _inputs(png: Path) -> dict[str, Any]:
    return {
        "posts": [
            {
                "text": "Mira la escuadra @lab.univerlab.org https://univerlab.org #taller",
                "lang": "es",
            },
            {"text": "El plano queda en el catálogo.", "lang": "es"},
        ],
        "images": [{"post": 1, "path": str(png), "alt": "La escuadra sobre la mesa."}],
    }


def _request(verb: str, tmp_path: Path, data: dict[str, Any]) -> Any:
    return STUB.Request({"verb": verb, "capability": "bluesky.post", **data})


def test_run_sends_a_thread_of_replies_with_one_record_each(
    tmp_path: Path, png: Path, net: FakeNet
) -> None:
    req = _request("run", tmp_path, {"inputs": _inputs(png), "out_dir": str(tmp_path)})
    result = RUNNER.runner._verbs["run"](req)
    post = result["post"]
    assert result["tool"] == {"name": "Bluesky", "version": "0.1.1"}
    assert post["network"] == "bluesky"
    assert post["account"] == HANDLE
    assert post["state"] == "published"
    assert post["cost"] is None
    assert [entry["url"] for entry in post["posts"]] == [
        f"https://bsky.app/profile/{HANDLE}/post/3khilo01",
        f"https://bsky.app/profile/{HANDLE}/post/3khilo02",
    ]
    first, second = net.records["3khilo01"], net.records["3khilo02"]
    assert "reply" not in first
    assert second["reply"]["parent"]["uri"].endswith("/3khilo01")
    assert second["reply"]["root"]["uri"].endswith("/3khilo01")


def test_run_uploads_the_image_with_alt_and_aspect(tmp_path: Path, png: Path, net: FakeNet) -> None:
    req = _request("run", tmp_path, {"inputs": _inputs(png), "out_dir": str(tmp_path)})
    RUNNER.runner._verbs["run"](req)
    assert net.uploads == [{"path": "banco.png", "bytes": png.stat().st_size, "mime": "image/png"}]
    embed = net.records["3khilo01"]["embed"]
    assert embed["$type"] == "app.bsky.embed.images"
    assert embed["images"][0]["alt"] == "La escuadra sobre la mesa."
    assert embed["images"][0]["aspectRatio"] == {"width": 64, "height": 48}
    assert "embed" not in net.records["3khilo02"]


def test_run_facets_the_link_mention_and_tag(tmp_path: Path, png: Path, net: FakeNet) -> None:
    req = _request("run", tmp_path, {"inputs": _inputs(png), "out_dir": str(tmp_path)})
    RUNNER.runner._verbs["run"](req)
    kinds = [
        feature["$type"]
        for facet in net.records["3khilo01"]["facets"]
        for feature in facet["features"]
    ]
    assert kinds == [
        "app.bsky.richtext.facet#mention",
        "app.bsky.richtext.facet#link",
        "app.bsky.richtext.facet#tag",
    ]
    assert net.records["3khilo01"]["langs"] == ["es"]


def test_run_refuses_over_long_text_before_anything_leaves(
    tmp_path: Path, png: Path, net: FakeNet
) -> None:
    inputs = {"posts": [{"text": "y" * 301}], "images": []}
    req = _request("run", tmp_path, {"inputs": inputs, "out_dir": str(tmp_path)})
    with pytest.raises(ValueError, match="300"):
        RUNNER.runner._verbs["run"](req)
    assert net.counter == 0


def test_verify_reads_back_text_and_media_count(tmp_path: Path, png: Path, net: FakeNet) -> None:
    run_req = _request("run", tmp_path, {"inputs": _inputs(png), "out_dir": str(tmp_path)})
    sent = RUNNER.runner._verbs["run"](run_req)["post"]
    verify_req = _request(
        "verify",
        tmp_path,
        {
            "inputs": _inputs(png),
            "post": {
                "network": "bluesky",
                "account": HANDLE,
                "posts": sent["posts"],
                "state": "published",
            },
            "sources": [{"path": str(png)}],
        },
    )
    measured = RUNNER.runner._verbs["verify"](verify_req)
    assert measured["state"] == "published"
    assert len(measured["media"]) == 1
    assert measured["media"][0]["alt"] == "La escuadra sobre la mesa."


def test_verify_raises_when_the_network_holds_other_text(
    tmp_path: Path, png: Path, net: FakeNet
) -> None:
    run_req = _request("run", tmp_path, {"inputs": _inputs(png), "out_dir": str(tmp_path)})
    sent = RUNNER.runner._verbs["run"](run_req)["post"]
    net.records["3khilo01"]["text"] = "Otro texto."
    verify_req = _request(
        "verify",
        tmp_path,
        {"inputs": _inputs(png), "post": {"posts": sent["posts"]}, "sources": [{"path": str(png)}]},
    )
    with pytest.raises(ValueError, match="post 1.*different text"):
        RUNNER.runner._verbs["verify"](verify_req)


def test_verify_raises_when_a_post_is_gone(tmp_path: Path, png: Path, net: FakeNet) -> None:
    verify_req = _request(
        "verify",
        tmp_path,
        {
            "inputs": _inputs(png),
            "post": {
                "posts": [{"id": f"at://{DID}/app.bsky.feed.post/3kgone", "url": "https://x"}]
            },
            "sources": [],
        },
    )
    with pytest.raises(ValueError, match="post 1"):
        RUNNER.runner._verbs["verify"](verify_req)


def test_preview_writes_the_post_schema_beside_the_receipt(
    tmp_path: Path, png: Path, net: FakeNet
) -> None:
    run_req = _request("run", tmp_path, {"inputs": _inputs(png), "out_dir": str(tmp_path)})
    sent = RUNNER.runner._verbs["run"](run_req)["post"]
    receipt = tmp_path / "hilo.post.json"
    receipt.write_text(
        json.dumps(
            {
                "network": "bluesky",
                "account": HANDLE,
                "state": "published",
                "posts": sent["posts"],
            }
        )
    )
    preview_req = _request(
        "preview",
        tmp_path,
        {"inputs": _inputs(png), "out_dir": str(tmp_path), "assets": [str(receipt)]},
    )
    result = RUNNER.runner._verbs["preview"](preview_req)
    preview = json.loads((tmp_path / "hilo.post.json.preview.json").read_text())
    assert result == {"assets": [{"file": "hilo.post.json.preview.json"}]}
    assert preview["preview"] == 1
    assert preview["kind"] == "post"
    assert preview["network"] == "bluesky"
    assert preview["account"] == HANDLE
    assert preview["state"] == "published"
    assert preview["images"] == ["banco.png"]
    assert [post["text"] for post in preview["posts"]] == [
        "Mira la escuadra @lab.univerlab.org https://univerlab.org #taller",
        "El plano queda en el catálogo.",
    ]
    assert [post["url"] for post in preview["posts"]] == [entry["url"] for entry in sent["posts"]]
    assert preview["posts"][0]["media"] == [
        {"file": "banco.png", "alt": "La escuadra sobre la mesa."}
    ]
    assert preview["posts"][1]["media"] == []


def test_preview_of_a_text_only_thread_lists_no_images(tmp_path: Path) -> None:
    inputs = {"posts": [{"text": "Solo texto."}], "images": []}
    receipt = tmp_path / "solo.post.json"
    receipt.write_text(
        json.dumps(
            {
                "network": "bluesky",
                "account": HANDLE,
                "state": "published",
                "posts": [{"id": "at://x/y/z", "url": "https://bsky.app/profile/lab/post/z"}],
            }
        )
    )
    preview_req = _request(
        "preview", tmp_path, {"inputs": inputs, "out_dir": str(tmp_path), "assets": [str(receipt)]}
    )
    RUNNER.runner._verbs["preview"](preview_req)
    preview = json.loads((tmp_path / "solo.post.json.preview.json").read_text())
    assert preview["images"] == []
    assert preview["posts"] == [
        {"text": "Solo texto.", "url": "https://bsky.app/profile/lab/post/z", "media": []}
    ]


def test_doctor_quick_checks_client_and_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACET_SECRET_HANDLE", HANDLE)
    monkeypatch.setenv("FACET_SECRET_APP_PASSWORD", "hunter2")
    req = _request("doctor", tmp_path, {"depth": "quick"})
    checks = {check["name"]: check for check in RUNNER.runner._verbs["doctor"](req)["checks"]}
    assert set(checks) == {"imports", "handle", "app-password"}
    assert all(check["ok"] for check in checks.values())
    assert all("hunter2" not in check["detail"] for check in checks.values())


def test_doctor_quick_names_a_missing_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACET_SECRET_APP_PASSWORD", raising=False)
    monkeypatch.setenv("FACET_SECRET_HANDLE", HANDLE)
    req = _request("doctor", tmp_path, {"depth": "quick"})
    checks = {check["name"]: check for check in RUNNER.runner._verbs["doctor"](req)["checks"]}
    assert checks["app-password"]["ok"] is False
    assert "facet secret set" in checks["app-password"]["fix"]


def test_doctor_full_signs_in_and_names_the_account(tmp_path: Path, net: FakeNet) -> None:
    req = _request("doctor", tmp_path, {"depth": "full"})
    checks = {check["name"]: check for check in RUNNER.runner._verbs["doctor"](req)["checks"]}
    assert checks["session"]["ok"] is True
    assert HANDLE in checks["session"]["detail"]
    assert "Laboratorio" in checks["session"]["detail"]
    assert net.session_calls == 1


def test_doctor_full_reports_a_failed_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACET_SECRET_HANDLE", HANDLE)
    monkeypatch.setenv("FACET_SECRET_APP_PASSWORD", "mala")

    def _refused(handle: str, password: str) -> dict[str, Any]:
        raise RUNNER.xrpc_client.XrpcError("createSession", 400, "AuthenticationRequired")

    monkeypatch.setattr(RUNNER.xrpc_client, "create_session", _refused)
    req = _request("doctor", tmp_path, {"depth": "full"})
    checks = {check["name"]: check for check in RUNNER.runner._verbs["doctor"](req)["checks"]}
    assert checks["session"]["ok"] is False
    assert "mala" not in checks["session"]["detail"]
