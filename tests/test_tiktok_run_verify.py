"""TikTok run, verify and preview with the network replaced by a fake."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "tiktok"
SECRETS = (
    "CLIENT_KEY",
    "CLIENT_SECRET",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "OPEN_ID",
)


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
TikTokError = RUNNER.tiktok_client.TikTokError
INBOX = RUNNER.tiktok_client.INBOX_STATUS
SUMMARY_LIMIT = 160


class FakeTikTok:
    def __init__(self) -> None:
        self.handle = "lab"
        self.token_ok = "good-token"
        self.inits: list[dict[str, Any]] = []
        self.chunks: list[dict[str, Any]] = []
        self.photo_inits: list[list[str]] = []
        self.statuses: dict[str, tuple[str, str]] = {}
        self.refreshed: list[tuple[str, str, str]] = []
        self.counter = 0
        self.init_error: Exception | None = None
        self.photo_error: Exception | None = None
        self.info_error: Exception | None = None

    def _check(self, token: str) -> None:
        if token != self.token_ok:
            raise TikTokError("creator_info", 401, "access_token_invalid: expired")

    def creator_info(self, token: str) -> dict[str, Any]:
        self._check(token)
        if self.info_error is not None:
            raise self.info_error
        return {"creator_username": self.handle, "creator_nickname": "Laboratorio"}

    def user_info(self, token: str) -> dict[str, Any]:
        self._check(token)
        return {"display_name": "Laboratorio", "open_id": "open-1"}

    def init_video_upload(
        self, token: str, size: int, chunk_size: int, chunk_count: int
    ) -> tuple[str, str]:
        self._check(token)
        if self.init_error is not None:
            raise self.init_error
        self.counter += 1
        publish_id = f"v_inbox_file~v2.{self.counter}"
        self.inits.append({"size": size, "chunk_size": chunk_size, "chunks": chunk_count})
        return publish_id, "https://upload.test/video"

    def upload_chunk(
        self, url: str, mime: str, data: bytes, first: int, last: int, total: int
    ) -> bool:
        self.chunks.append(
            {"mime": mime, "bytes": len(data), "first": first, "last": last, "total": total}
        )
        return last + 1 >= total

    def init_photo_upload(self, token: str, urls: list[str]) -> str:
        self._check(token)
        if self.photo_error is not None:
            raise self.photo_error
        self.counter += 1
        publish_id = f"p_inbox_url~v2.{self.counter}"
        self.photo_inits.append(list(urls))
        return publish_id

    def publish_status(self, token: str, publish_id: str) -> tuple[str, str]:
        self._check(token)
        if publish_id not in self.statuses:
            raise TikTokError("status/fetch", 400, "invalid_publish_id: unknown")
        return self.statuses[publish_id]

    def refresh_tokens(self, key: str, client_secret: str, refresh_token: str) -> Any:
        self.refreshed.append((key, client_secret, refresh_token))
        tokens_cls = RUNNER.tiktok_client.Tokens
        return tokens_cls(
            access_token="fresh-token",
            refresh_token="fresh-refresh",
            open_id="open-1",
            scopes=("user.info.basic", "video.upload"),
        )


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeTikTok:
    net = FakeTikTok()
    for name in SECRETS:
        monkeypatch.setenv(f"FACET_SECRET_{name}", "s3cr3t")
    monkeypatch.setenv("FACET_SECRET_ACCESS_TOKEN", net.token_ok)
    STUB.renewals.clear()
    client = RUNNER.tiktok_client
    monkeypatch.setattr(client, "creator_info", net.creator_info)
    monkeypatch.setattr(client, "user_info", net.user_info)
    monkeypatch.setattr(client, "init_video_upload", net.init_video_upload)
    monkeypatch.setattr(client, "upload_chunk", net.upload_chunk)
    monkeypatch.setattr(client, "init_photo_upload", net.init_photo_upload)
    monkeypatch.setattr(client, "publish_status", net.publish_status)
    monkeypatch.setattr(client, "refresh_tokens", net.refresh_tokens)
    return net


@pytest.fixture()
def files(tmp_path: Path) -> dict[str, Path]:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00" * 64)
    return {"video": video, "dir": tmp_path}


def _req(verb: str, files: dict[str, Path], data: dict[str, Any] | None = None) -> Any:
    payload: dict[str, Any] = {
        "verb": verb,
        "capability": "tiktok.post",
        "inputs": {
            "caption": "La escuadra del laboratorio. #taller",
            "video": str(files["video"]),
        },
        "out_dir": str(files["dir"]),
        "piece_dir": str(files["dir"]),
    }
    if data:
        payload.update(data)
    return STUB.Request(payload)


def test_run_video_uploads_chunks_and_answers_a_draft(
    files: dict[str, Path], fake: FakeTikTok
) -> None:
    result = RUNNER.runner._verbs["run"](_req("run", files))
    assert result["tool"] == {"name": "TikTok", "version": "0.1.2"}
    post = result["post"]
    assert post["network"] == "tiktok"
    assert post["account"] == "@lab"
    assert post["state"] == "draft"
    assert post["posts"] == [{"id": "v_inbox_file~v2.1", "url": "https://www.tiktok.com/@lab"}]
    assert post["cost"] is None
    assert len(fake.inits) == 1
    assert fake.inits[0] == {"size": 64, "chunk_size": 64, "chunks": 1}
    assert len(fake.chunks) == 1
    assert fake.chunks[0]["mime"] == "video/mp4"
    assert (fake.chunks[0]["first"], fake.chunks[0]["last"]) == (0, 63)


STREAMED = 25


def test_run_video_streams_chunks_sequentially(
    files: dict[str, Path], fake: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER, "CHUNK_SIZE", 10)
    monkeypatch.setattr(RUNNER, "MIN_CHUNK", 5)
    files["video"].write_bytes(b"\x01" * STREAMED)
    result = RUNNER.runner._verbs["run"](_req("run", files))
    assert result["post"]["state"] == "draft"
    assert fake.inits[0] == {"size": STREAMED, "chunk_size": 10, "chunks": 3}
    ranges = [(entry["first"], entry["last"]) for entry in fake.chunks]
    assert ranges == [(0, 9), (10, 19), (20, 24)]
    assert sum(entry["bytes"] for entry in fake.chunks) == STREAMED


def test_run_photo_inits_by_url_and_skips_chunks(files: dict[str, Path], fake: FakeTikTok) -> None:
    urls = ["https://fotos.univerlab.org/taller/e-1.jpg"]
    req = _req(
        "run",
        files,
        {"inputs": {"caption": "La escuadra.", "photos": [{"url": urls[0]}]}},
    )
    result = RUNNER.runner._verbs["run"](req)
    post = result["post"]
    assert post["state"] == "draft"
    assert post["posts"][0]["id"] == "p_inbox_url~v2.1"
    assert post["posts"][0]["url"] == "https://www.tiktok.com/@lab"
    assert fake.photo_inits == [urls]
    assert fake.inits == [] and fake.chunks == []


def test_run_photo_refused_before_anything_lands(files: dict[str, Path], fake: FakeTikTok) -> None:
    fake.photo_error = TikTokError(
        "content/init", 403, "url_ownership_unverified: verify the domain"
    )
    req = _req(
        "run",
        files,
        {
            "inputs": {
                "caption": "La escuadra.",
                "photos": [{"url": "https://fotos.univerlab.org/taller/e-1.jpg"}],
            }
        },
    )
    with pytest.raises(ValueError, match="url_ownership_unverified"):
        RUNNER.runner._verbs["run"](req)
    assert fake.photo_inits == []
    assert fake.inits == [] and fake.chunks == []


def test_run_refreshes_an_expired_token_through_store_back(
    files: dict[str, Path], fake: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACET_SECRET_ACCESS_TOKEN", "expired-token")
    fake.token_ok = "fresh-token"
    result = RUNNER.runner._verbs["run"](_req("run", files))
    assert result["post"]["account"] == "@lab"
    assert len(fake.refreshed) == 1
    assert ("access-token", "fresh-token") in STUB.renewals
    assert ("refresh-token", "fresh-refresh") in STUB.renewals


def test_run_refuses_an_oversize_video_without_uploading(
    files: dict[str, Path], fake: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER, "VIDEO_LIMIT", 8)
    with pytest.raises(ValueError, match="over"):
        RUNNER.runner._verbs["run"](_req("run", files))
    assert fake.inits == [] and fake.chunks == []


def test_verify_passes_when_the_draft_reached_the_inbox(
    files: dict[str, Path], fake: FakeTikTok
) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    fake.statuses["v_inbox_file~v2.1"] = (INBOX, "")
    req = _req("run", files, {"post": run_res["post"]})
    result = RUNNER.runner._verbs["verify"](req)
    assert result["state"] == "draft"
    assert result["media"] == [{"file": "v_inbox_file~v2.1.video", "alt": None}]


def test_verify_photo_set_reads_back_no_media(files: dict[str, Path], fake: FakeTikTok) -> None:
    req = _req(
        "run",
        files,
        {"inputs": {"caption": "La escuadra.", "photos": [{"url": "https://a.b/c.jpg"}]}},
    )
    run_res = RUNNER.runner._verbs["run"](req)
    fake.statuses["p_inbox_url~v2.1"] = (INBOX, "")
    check = _req(
        "verify",
        files,
        {
            "inputs": req.inputs,
            "post": run_res["post"],
        },
    )
    result = RUNNER.runner._verbs["verify"](check)
    assert result["state"] == "draft"
    assert result["media"] == []


def test_verify_fails_with_tiktoks_reason(files: dict[str, Path], fake: FakeTikTok) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    fake.statuses["v_inbox_file~v2.1"] = ("FAILED", "picture_size_check_failed")
    with pytest.raises(ValueError, match="picture_size_check_failed"):
        RUNNER.runner._verbs["verify"](_req("run", files, {"post": run_res["post"]}))


def test_verify_waits_while_tiktok_still_processes(
    files: dict[str, Path], fake: FakeTikTok
) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    fake.statuses["v_inbox_file~v2.1"] = ("PROCESSING_UPLOAD", "")
    with pytest.raises(ValueError, match="not in the inbox yet"):
        RUNNER.runner._verbs["verify"](_req("run", files, {"post": run_res["post"]}))


def test_verify_refuses_an_unknown_publish_id(files: dict[str, Path], fake: FakeTikTok) -> None:
    post = {
        "network": "tiktok",
        "account": "@lab",
        "state": "draft",
        "posts": [{"id": "v_inbox_file~v2.9", "url": "https://www.tiktok.com/@lab"}],
        "cost": None,
    }
    with pytest.raises(ValueError, match="invalid_publish_id"):
        RUNNER.runner._verbs["verify"](_req("run", files, {"post": post}))


def _write_receipt(files: dict[str, Path], run_res: dict[str, Any]) -> Path:
    receipt = files["dir"] / "inbox.post.json"
    receipt.write_text(json.dumps(run_res["post"]))
    return receipt


def test_preview_writes_the_post_schema_beside_the_receipt(
    files: dict[str, Path], fake: FakeTikTok
) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    receipt = _write_receipt(files, run_res)
    req = _req("preview", files, {"assets": [str(receipt)]})
    result = RUNNER.runner._verbs["preview"](req)
    preview_file = files["dir"] / f"{receipt.name}.preview.json"
    assert result == {"assets": [{"file": preview_file.name}]}
    data = json.loads(preview_file.read_text(encoding="utf-8"))
    assert data["preview"] == 1
    assert data["kind"] == "post"
    assert data["network"] == "tiktok"
    assert data["account"] == "@lab"
    assert data["state"] == "draft"
    assert len(data["summary"]) <= SUMMARY_LIMIT
    assert "inbox" in data["summary"] and "paste" in data["summary"]
    assert data["images"] == ["clip.mp4"]
    assert data["posts"] == [
        {
            "text": "La escuadra del laboratorio. #taller",
            "url": "https://www.tiktok.com/@lab",
            "media": [{"file": "clip.mp4", "alt": None}],
        }
    ]


def test_preview_photo_set_carries_no_files(files: dict[str, Path], fake: FakeTikTok) -> None:
    inputs = {
        "caption": "La escuadra.",
        "photos": [{"url": "https://fotos.univerlab.org/taller/e-1.jpg"}],
    }
    run_res = RUNNER.runner._verbs["run"](_req("run", files, {"inputs": inputs}))
    receipt = _write_receipt(files, run_res)
    req = _req("preview", files, {"inputs": inputs, "assets": [str(receipt)]})
    RUNNER.runner._verbs["preview"](req)
    data = json.loads((files["dir"] / f"{receipt.name}.preview.json").read_text())
    assert data["images"] == []
    assert data["posts"][0]["media"] == []
    assert data["posts"][0]["text"] == "La escuadra."


TOTAL_SMALL = 4 * 1024 * 1024
TOTAL_MERGED = 24 * 1024 * 1024
TOTAL_EVEN = 25 * 1024 * 1024
FINAL_MERGED = 14 * 1024 * 1024


def test_chunk_plan_keeps_every_chunk_inside_tiktoks_rule() -> None:
    plan = RUNNER._chunk_plan
    assert plan(TOTAL_SMALL) == (TOTAL_SMALL, 1)
    assert plan(TOTAL_EVEN) == (10 * 1024 * 1024, 3)
    size, count = plan(TOTAL_MERGED)
    assert (size, count) == (10 * 1024 * 1024, 2)
    assert size * (count - 1) < TOTAL_MERGED
    assert TOTAL_MERGED - size * (count - 1) == FINAL_MERGED


def test_authorize_url_names_the_scopes_and_the_redirect() -> None:
    verifier = RUNNER.tiktok_client.make_verifier()
    challenge = RUNNER.tiktok_client.challenge_of(verifier)
    url = RUNNER.tiktok_client.authorize_url("key-1", "http://127.0.0.1:8080/x", "s", challenge)
    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/?")
    assert "scope=user.info.basic" in url and "redirect_uri=" in url
    assert f"code_challenge={challenge}" in url
    assert "code_challenge_method=S256" in url


MIN_VERIFIER_LEN = 64
MAX_VERIFIER_LEN = 128
SHA256_HEX_LEN = 64


def test_pkce_verifier_charset_length_and_hex_sha256_challenge() -> None:
    client = RUNNER.tiktok_client
    verifier = client.make_verifier()
    assert MIN_VERIFIER_LEN <= len(verifier) <= MAX_VERIFIER_LEN
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    assert set(verifier) <= allowed
    expected = __import__("hashlib").sha256(verifier.encode("ascii")).hexdigest()
    assert client.challenge_of(verifier) == expected
    assert expected == expected.lower() and len(expected) == SHA256_HEX_LEN


def test_exchange_code_sends_code_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float = 30.0) -> _FakeResponse:
        assert request.data is not None
        captured.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse(
            {
                "data": {
                    "access_token": "a1",
                    "refresh_token": "r1",
                    "open_id": "o1",
                    "scope": "user.info.basic,video.upload",
                },
                "error": {"code": "ok"},
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    tokens = RUNNER.tiktok_client.exchange_code(
        "k1", "s1", "c1", "http://127.0.0.1:8080/callback/", "v1"
    )
    assert tokens.access_token == "a1"
    assert captured == [
        {
            "client_key": "k1",
            "client_secret": "s1",
            "code": "c1",
            "grant_type": "authorization_code",
            "redirect_uri": "http://127.0.0.1:8080/callback/",
            "code_verifier": "v1",
        }
    ]


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def _http_error(url: str, code: int, payload: dict[str, Any]) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url, code, "refused", {}, io.BytesIO(json.dumps(payload).encode("utf-8"))
    )


def _ok(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: _FakeResponse(payload))


def test_client_init_video_upload_reads_publish_id_and_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ok(
        monkeypatch,
        {"data": {"publish_id": "v1", "upload_url": "https://up/x"}, "error": {"code": "ok"}},
    )
    client = RUNNER.tiktok_client
    assert client.init_video_upload("t", 64, 64, 1) == ("v1", "https://up/x")


def test_client_refuses_tiktoks_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ok(
        monkeypatch,
        {"error": {"code": "url_ownership_unverified", "message": "verify it"}},
    )
    with pytest.raises(TikTokError, match="url_ownership_unverified"):
        RUNNER.tiktok_client.init_photo_upload("t", ["https://a.b/c.jpg"])


def test_client_maps_http_failures_to_tiktoks_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"error": {"code": "access_token_invalid", "message": "expired"}}
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(_http_error("https://x", 401, payload)),
    )
    with pytest.raises(TikTokError, match="access_token_invalid"):
        RUNNER.tiktok_client.creator_info("stale")


def test_client_upload_chunk_reports_done_only_on_201(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RUNNER.tiktok_client
    _ok(monkeypatch, {})
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *args, **kwargs: _FakeResponse({}, status=206)
    )
    assert client.upload_chunk("https://up/x", "video/mp4", b"1", 0, 0, 2) is False
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *args, **kwargs: _FakeResponse({}, status=201)
    )
    assert client.upload_chunk("https://up/x", "video/mp4", b"1", 1, 1, 2) is True
