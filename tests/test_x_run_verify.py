"""The x send, read-back, preview and credential check, all offline.

The network is replaced, never touched: these tests run the runner
in-process against a stub ``facet_runner_sdk`` and a fake ``x_client``
whose calls are recorded, so the reply chain, the uploaded media, the
rates on the receipt and the read-back comparisons are the runner's own
answers. A test that still passed with the send removed would be sent
back.
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
HANDLE = "lab"
USER_ID = "123456"
SECRETS = ("CONSUMER_KEY", "CONSUMER_SECRET", "ACCESS_TOKEN", "ACCESS_TOKEN_SECRET")


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


class FakeNet:
    """The whole network: the account, uploads, posts and reads on demand."""

    def __init__(self) -> None:
        self.posts: dict[str, dict[str, Any]] = {}
        self.uploads: list[dict[str, Any]] = []
        self.alts: list[dict[str, str]] = []
        self.counter = 0
        self.reads = 0

    def whoami(self) -> dict[str, Any]:
        return {"id": USER_ID, "name": "Laboratorio", "username": HANDLE}

    def probe_write(self) -> bool:
        return True

    def upload_media(self, data: bytes, mime: str, category: str) -> str:
        self.uploads.append({"bytes": len(data), "mime": mime, "category": category})
        return f"media{len(self.uploads)}"

    def set_alt_text(self, media_id: str, alt: str) -> None:
        self.alts.append({"media_id": media_id, "alt": alt})

    def create_post(
        self, text: str, *, media_ids: list[str] | None = None, reply_to: str | None = None
    ) -> dict[str, str]:
        self.counter += 1
        post_id = f"19000000000000000{self.counter:02d}"
        self.posts[post_id] = {
            "id": post_id,
            "text": text,
            "attachments": {"media_keys": list(media_ids or [])},
            "reply_to": reply_to,
        }
        return {"id": post_id, "text": text}

    def get_posts(self, ids: list[str]) -> list[dict[str, Any]]:
        self.reads += 1
        found = []
        for post_id in ids:
            if post_id not in self.posts:
                raise RUNNER.x_client.XError("GET /2/tweets", 404, "not found")
            found.append(self.posts[post_id])
        return found


@pytest.fixture()
def net(monkeypatch: pytest.MonkeyPatch) -> FakeNet:
    fake = FakeNet()
    for name in SECRETS:
        monkeypatch.setenv(f"FACET_SECRET_{name}", "s3cr3t")
    monkeypatch.setattr(RUNNER.x_client, "whoami", lambda keys: fake.whoami())
    monkeypatch.setattr(RUNNER.x_client, "probe_write", lambda keys: fake.probe_write())
    monkeypatch.setattr(
        RUNNER.x_client,
        "upload_media",
        lambda keys, data, mime, cat: fake.upload_media(data, mime, cat),
    )
    monkeypatch.setattr(
        RUNNER.x_client,
        "set_alt_text",
        lambda keys, media_id, alt: fake.set_alt_text(media_id, alt),
    )
    monkeypatch.setattr(
        RUNNER.x_client,
        "create_post",
        lambda keys, text, **kwargs: fake.create_post(
            text, media_ids=kwargs.get("media_ids"), reply_to=kwargs.get("reply_to")
        ),
    )
    monkeypatch.setattr(RUNNER.x_client, "get_posts", lambda keys, ids: fake.get_posts(ids))
    return fake


@pytest.fixture()
def png(tmp_path: Path) -> Path:
    path = tmp_path / "banco.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    return path


def _inputs(png: Path) -> dict[str, Any]:
    return {
        "posts": [
            {"text": "La escuadra, recién salida del banco. #taller"},
            {"text": "Lee el plano https://univerlab.org/catalogo/escuadra ya."},
        ],
        "images": [{"post": 1, "path": str(png), "alt": "La escuadra sobre la mesa."}],
    }


def _request(verb: str, tmp_path: Path, data: dict[str, Any]) -> Any:
    return STUB.Request({"verb": verb, "capability": "x.post", **data})


def test_run_sends_a_thread_of_replies_with_one_record_each(
    tmp_path: Path, png: Path, net: FakeNet
) -> None:
    req = _request("run", tmp_path, {"inputs": _inputs(png), "out_dir": str(tmp_path)})
    result = RUNNER.runner._verbs["run"](req)
    post = result["post"]
    assert result["tool"] == {"name": "X", "version": "0.1.1"}
    assert post["network"] == "x"
    assert post["account"] == "@lab"
    assert post["state"] == "published"
    assert post["cost"] == {"amount": 0.235, "currency": "USD"}
    assert [entry["url"] for entry in post["posts"]] == [
        "https://x.com/i/status/1900000000000000001",
        "https://x.com/i/status/1900000000000000002",
    ]
    first = net.posts["1900000000000000001"]
    second = net.posts["1900000000000000002"]
    assert first["reply_to"] is None
    assert second["reply_to"] == "1900000000000000001"


def test_run_uploads_the_image_with_alt_text(tmp_path: Path, png: Path, net: FakeNet) -> None:
    req = _request("run", tmp_path, {"inputs": _inputs(png), "out_dir": str(tmp_path)})
    RUNNER.runner._verbs["run"](req)
    assert net.uploads == [
        {"bytes": png.stat().st_size, "mime": "image/png", "category": "tweet_image"}
    ]
    assert net.alts == [{"media_id": "media1", "alt": "La escuadra sobre la mesa."}]
    assert net.posts["1900000000000000001"]["attachments"] == {"media_keys": ["media1"]}
    assert net.posts["1900000000000000002"]["attachments"] == {"media_keys": []}


def test_run_refuses_over_long_text_before_anything_leaves(
    tmp_path: Path, png: Path, net: FakeNet
) -> None:
    inputs = {"posts": [{"text": "y" * 281}], "images": []}
    req = _request("run", tmp_path, {"inputs": inputs, "out_dir": str(tmp_path)})
    with pytest.raises(ValueError, match="280"):
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
                "network": "x",
                "account": "@lab",
                "posts": sent["posts"],
                "state": "published",
            },
            "sources": [{"path": str(png)}],
        },
    )
    measured = RUNNER.runner._verbs["verify"](verify_req)
    assert measured["state"] == "published"
    assert len(measured["media"]) == 1


def test_verify_raises_when_the_network_holds_other_text(
    tmp_path: Path, png: Path, net: FakeNet
) -> None:
    run_req = _request("run", tmp_path, {"inputs": _inputs(png), "out_dir": str(tmp_path)})
    sent = RUNNER.runner._verbs["run"](run_req)["post"]
    net.posts["1900000000000000001"]["text"] = "Otro texto."
    verify_req = _request(
        "verify",
        tmp_path,
        {"inputs": _inputs(png), "post": {"posts": sent["posts"]}, "sources": [{"path": str(png)}]},
    )
    with pytest.raises(ValueError, match="post 1.*different text"):
        RUNNER.runner._verbs["verify"](verify_req)


def test_verify_accepts_the_shortened_url_the_network_returns(
    tmp_path: Path, png: Path, net: FakeNet
) -> None:
    run_req = _request("run", tmp_path, {"inputs": _inputs(png), "out_dir": str(tmp_path)})
    sent = RUNNER.runner._verbs["run"](run_req)["post"]
    net.posts["1900000000000000001"]["text"] += " https://t.co/media1"
    net.posts["1900000000000000002"]["text"] = "Lee el plano https://t.co/abc123 ya."
    verify_req = _request(
        "verify",
        tmp_path,
        {"inputs": _inputs(png), "post": {"posts": sent["posts"]}, "sources": [{"path": str(png)}]},
    )
    measured = RUNNER.runner._verbs["verify"](verify_req)
    assert measured["state"] == "published"
    assert len(measured["media"]) == 1


def test_verify_raises_when_the_network_holds_a_different_media_count(
    tmp_path: Path, png: Path, net: FakeNet
) -> None:
    run_req = _request("run", tmp_path, {"inputs": _inputs(png), "out_dir": str(tmp_path)})
    sent = RUNNER.runner._verbs["run"](run_req)["post"]
    net.posts["1900000000000000001"]["attachments"] = {"media_keys": []}
    verify_req = _request(
        "verify",
        tmp_path,
        {"inputs": _inputs(png), "post": {"posts": sent["posts"]}, "sources": [{"path": str(png)}]},
    )
    with pytest.raises(ValueError, match="post 1.*different media count"):
        RUNNER.runner._verbs["verify"](verify_req)


def test_verify_raises_when_a_post_is_gone(tmp_path: Path, png: Path, net: FakeNet) -> None:
    verify_req = _request(
        "verify",
        tmp_path,
        {
            "inputs": _inputs(png),
            "post": {"posts": [{"id": "1999999999999999999", "url": "https://x.com/i/status/1"}]},
            "sources": [],
        },
    )
    with pytest.raises(ValueError, match="read-back failed"):
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
                "network": "x",
                "account": "@lab",
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
    assert preview["network"] == "x"
    assert preview["account"] == "@lab"
    assert preview["state"] == "published"
    assert preview["images"] == ["banco.png"]
    assert [post["text"] for post in preview["posts"]] == [
        "La escuadra, recién salida del banco. #taller",
        "Lee el plano https://univerlab.org/catalogo/escuadra ya.",
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
                "network": "x",
                "account": "@lab",
                "state": "published",
                "posts": [{"id": "1900000000000000001", "url": "https://x.com/i/status/1"}],
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
        {"text": "Solo texto.", "url": "https://x.com/i/status/1", "media": []}
    ]


def test_doctor_quick_checks_client_rates_and_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in SECRETS:
        monkeypatch.setenv(f"FACET_SECRET_{name}", "s3cr3t")
    req = _request("doctor", tmp_path, {"depth": "quick"})
    checks = {check["name"]: check for check in RUNNER.runner._verbs["doctor"](req)["checks"]}
    assert set(checks) == {
        "imports",
        "consumer-key",
        "consumer-secret",
        "access-token",
        "access-token-secret",
    }
    assert all(check["ok"] for check in checks.values())
    assert all("s3cr3t" not in check["detail"] for check in checks.values())


def test_doctor_quick_names_a_missing_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in SECRETS:
        monkeypatch.setenv(f"FACET_SECRET_{name}", "s3cr3t")
    monkeypatch.delenv("FACET_SECRET_ACCESS_TOKEN", raising=False)
    req = _request("doctor", tmp_path, {"depth": "quick"})
    checks = {check["name"]: check for check in RUNNER.runner._verbs["doctor"](req)["checks"]}
    assert checks["access-token"]["ok"] is False
    assert "facet secret set" in checks["access-token"]["fix"]


def test_doctor_full_names_the_account_and_states_the_check_cost(
    tmp_path: Path, net: FakeNet
) -> None:
    req = _request("doctor", tmp_path, {"depth": "full"})
    checks = {check["name"]: check for check in RUNNER.runner._verbs["doctor"](req)["checks"]}
    assert checks["session"]["ok"] is True
    assert "@lab" in checks["session"]["detail"]
    assert "Laboratorio" in checks["session"]["detail"]
    assert "$0.010" in checks["session"]["detail"]
    assert checks["write"]["ok"] is True
    assert "before creating a post" in checks["write"]["detail"]


def test_doctor_full_names_a_read_only_token(
    tmp_path: Path, net: FakeNet, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER.x_client, "probe_write", lambda keys: False)
    req = _request("doctor", tmp_path, {"depth": "full"})
    checks = {check["name"]: check for check in RUNNER.runner._verbs["doctor"](req)["checks"]}
    assert checks["write"]["ok"] is False
    assert "cannot write" in checks["write"]["detail"]
    assert "Read and write" in checks["write"]["fix"]
    assert "facet secret set x access-token" in checks["write"]["fix"]


def test_doctor_full_reports_a_failed_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in SECRETS:
        monkeypatch.setenv(f"FACET_SECRET_{name}", "mala")

    def _refused(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RUNNER.x_client.XError("GET /2/users/me", 403, "Forbidden")

    monkeypatch.setattr(RUNNER.x_client, "whoami", _refused)
    req = _request("doctor", tmp_path, {"depth": "full"})
    checks = {check["name"]: check for check in RUNNER.runner._verbs["doctor"](req)["checks"]}
    assert checks["session"]["ok"] is False
    assert "mala" not in checks["session"]["detail"]
