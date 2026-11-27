"""LinkedIn Member run, verify, preview, doctor and auth with HTTP faked."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import socket
import struct
import sys
import threading
import types
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "linkedin-member"
MEMBER_ID = "sub-member-42"
AUTHOR = f"urn:li:person:{MEMBER_ID}"
SECRETS = (
    "CLIENT_ID",
    "CLIENT_SECRET",
    "ACCESS_TOKEN",
    "MEMBER_ID",
    "REFRESH_TOKEN",
)
SUMMARY_LIMIT = 160


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

    def announce_url(url: str) -> None:
        stub.announced.append(url)  # type: ignore[attr-defined]

    stub.Request = Request  # type: ignore[attr-defined]
    stub.Runner = Runner  # type: ignore[attr-defined]
    stub.secret = secret  # type: ignore[attr-defined]
    stub.renew_secret = renew_secret  # type: ignore[attr-defined]
    stub.renewals = []  # type: ignore[attr-defined]
    stub.announce_url = announce_url  # type: ignore[attr-defined]
    stub.announced = []  # type: ignore[attr-defined]
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
LinkedInError = RUNNER.linkedin_member_client.LinkedInError


class FakeLinkedInMember:
    def __init__(self) -> None:
        self.token_ok = "good-token"
        self.counter = 0
        self.inits: list[str] = []
        self.uploads: list[tuple[str, bytes]] = []
        self.video_inits: list[tuple[str, int]] = []
        self.video_chunks: list[tuple[str, bytes]] = []
        self.video_finalizes: list[tuple[str, str, list[str]]] = []
        self.video_statuses: list[str] = ["PROCESSING", "AVAILABLE"]
        self.video_read_forbidden = False
        self.bodies: list[dict[str, Any]] = []
        self.posts: dict[str, dict[str, Any]] = {}
        self.refreshed: list[tuple[str, str, str]] = []
        self.read_forbidden = False

    def _check(self, token: str) -> None:
        if token != self.token_ok:
            raise LinkedInError("rest/posts", 401, "the token expired")

    def userinfo(self, token: str) -> dict[str, Any]:
        self._check(token)
        return {"sub": MEMBER_ID, "name": "Ada Lovelace"}

    def init_image_upload(self, token: str, owner: str) -> tuple[str, str]:
        self._check(token)
        self.counter += 1
        urn = f"urn:li:image:img{self.counter}"
        self.inits.append(owner)
        return f"https://upload.test/{self.counter}", urn

    def upload_image(self, url: str, mime: str, data: bytes) -> None:
        self.uploads.append((mime, data))

    def init_video_upload(
        self, token: str, owner: str, file_size_bytes: int
    ) -> tuple[str, str, list[dict[str, Any]]]:
        self._check(token)
        self.counter += 1
        self.video_inits.append((owner, file_size_bytes))
        mid = file_size_bytes // 2
        instructions = [
            {
                "uploadUrl": f"https://upload.test/video/{self.counter}/part1",
                "firstByte": 0,
                "lastByte": mid - 1,
            },
            {
                "uploadUrl": f"https://upload.test/video/{self.counter}/part2",
                "firstByte": mid,
                "lastByte": file_size_bytes - 1,
            },
        ]
        return f"urn:li:video:vid{self.counter}", f"tok-{self.counter}", instructions

    def upload_video_chunk(self, upload_url: str, chunk: bytes) -> str:
        self.video_chunks.append((upload_url, chunk))
        return f'"etag-{len(self.video_chunks)}"'

    def finalize_video_upload(
        self, token: str, video_urn: str, upload_token: str, uploaded_part_ids: list[str]
    ) -> None:
        self._check(token)
        self.video_finalizes.append((video_urn, upload_token, list(uploaded_part_ids)))

    def get_video(self, token: str, video_urn: str) -> dict[str, Any]:
        self._check(token)
        if self.video_read_forbidden:
            raise LinkedInError("rest/videos", 403, "Not enough permissions")
        status = self.video_statuses.pop(0) if self.video_statuses else "AVAILABLE"
        return {"id": video_urn, "status": status}

    def create_post(self, token: str, body: dict[str, Any]) -> str:
        self._check(token)
        post_id = f"urn:li:share:{8000 + len(self.bodies)}"
        self.bodies.append(dict(body))
        images: list[str] = []
        content = body.get("content", {})
        if "multiImage" in content:
            images = [entry["id"] for entry in content["multiImage"]["images"]]
        elif "media" in content:
            images = [content["media"]["id"]]
        self.posts[post_id] = {"commentary": body["commentary"], "images": images}
        return post_id

    def get_post(self, token: str, post_id: str) -> dict[str, Any]:
        self._check(token)
        if self.read_forbidden:
            raise LinkedInError("rest/posts", 403, "Not enough permissions")
        if post_id not in self.posts:
            raise LinkedInError("rest/posts", 404, "the post does not exist")
        stored = self.posts[post_id]
        post: dict[str, Any] = {
            "author": AUTHOR,
            "commentary": stored["commentary"],
            "visibility": "PUBLIC",
            "lifecycleState": "PUBLISHED",
            "id": post_id,
        }
        if len(stored["images"]) == 1:
            post["content"] = {"media": {"id": stored["images"][0], "title": "alt"}}
        elif stored["images"]:
            post["content"] = {"multiImage": {"images": [{"id": urn} for urn in stored["images"]]}}
        return post

    def refresh_tokens(self, client_id: str, client_secret: str, refresh_token: str) -> Any:
        self.refreshed.append((client_id, client_secret, refresh_token))
        tokens_cls = RUNNER.linkedin_member_client.Tokens
        return tokens_cls(
            access_token="fresh-token",
            refresh_token="fresh-refresh",
            scopes=("openid", "profile", "w_member_social"),
        )


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeLinkedInMember:
    net = FakeLinkedInMember()
    for name in SECRETS:
        monkeypatch.setenv(f"FACET_SECRET_{name}", "s3cr3t")
    monkeypatch.setenv("FACET_SECRET_ACCESS_TOKEN", net.token_ok)
    monkeypatch.setenv("FACET_SECRET_MEMBER_ID", MEMBER_ID)
    STUB.renewals.clear()
    client = RUNNER.linkedin_member_client
    monkeypatch.setattr(client, "userinfo", net.userinfo)
    monkeypatch.setattr(client, "init_image_upload", net.init_image_upload)
    monkeypatch.setattr(client, "upload_image", net.upload_image)
    monkeypatch.setattr(client, "init_video_upload", net.init_video_upload)
    monkeypatch.setattr(client, "upload_video_chunk", net.upload_video_chunk)
    monkeypatch.setattr(client, "finalize_video_upload", net.finalize_video_upload)
    monkeypatch.setattr(client, "get_video", net.get_video)
    monkeypatch.setattr(client, "VIDEO_POLL_INTERVAL_S", 0.0)
    monkeypatch.setattr(client, "create_post", net.create_post)
    monkeypatch.setattr(client, "get_post", net.get_post)
    monkeypatch.setattr(client, "refresh_tokens", net.refresh_tokens)
    return net


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


def _inputs(files: dict[str, Path], **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "text": "La escuadra del laboratorio. #taller",
        "images": [{"path": str(files["still"]), "alt": "La escuadra sobre el banco."}],
    }
    data.update(over)
    return data


def _req(verb: str, files: dict[str, Path], data: dict[str, Any] | None = None) -> Any:
    payload: dict[str, Any] = {
        "verb": verb,
        "capability": "linkedin-member.post",
        "inputs": _inputs(files),
        "out_dir": str(files["dir"]),
        "piece_dir": str(files["dir"]),
    }
    if data:
        payload.update(data)
    return STUB.Request(payload)


def test_run_single_image_uses_person_urn_and_answers_published_receipt(
    files: dict[str, Path], fake: FakeLinkedInMember
) -> None:
    result = RUNNER.runner._verbs["run"](_req("run", files))
    assert result["tool"] == {"name": "LinkedIn Member", "version": "0.2.1"}
    post = result["post"]
    assert post["network"] == "linkedin-member"
    assert post["account"] == "Ada Lovelace"
    assert post["state"] == "published"
    assert post["posts"] == [
        {
            "id": "urn:li:share:8000",
            "url": "https://www.linkedin.com/feed/update/urn:li:share:8000",
        }
    ]
    assert post["cost"] is None
    assert "warnings" not in post
    assert fake.inits == [AUTHOR]
    (body,) = fake.bodies
    assert body["author"] == AUTHOR
    assert body["content"] == {
        "media": {"id": "urn:li:image:img1", "title": "La escuadra sobre el banco."}
    }


def test_run_text_only_sends_no_media(files: dict[str, Path], fake: FakeLinkedInMember) -> None:
    req = _req("run", files, {"inputs": _inputs(files, images=[])})
    result = RUNNER.runner._verbs["run"](req)
    assert result["post"]["posts"][0]["id"] == "urn:li:share:8000"
    (body,) = fake.bodies
    assert body["author"] == AUTHOR
    assert "content" not in body
    assert fake.inits == [] and fake.uploads == []


def test_run_read_back_forbidden_keeps_urn_url_with_unknown_and_warning(
    files: dict[str, Path], fake: FakeLinkedInMember
) -> None:
    fake.read_forbidden = True
    result = RUNNER.runner._verbs["run"](_req("run", files))
    post = result["post"]
    assert post["state"] == "unknown"
    assert post["posts"] == [
        {
            "id": "urn:li:share:8000",
            "url": "https://www.linkedin.com/feed/update/urn:li:share:8000",
        }
    ]
    assert post["warnings"]
    assert "forbidden" in post["warnings"][0].lower()


def test_run_401_with_refresh_token_refreshes_once_and_stores(
    files: dict[str, Path], fake: FakeLinkedInMember, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACET_SECRET_ACCESS_TOKEN", "expired-token")
    fake.token_ok = "fresh-token"
    result = RUNNER.runner._verbs["run"](_req("run", files))
    assert result["post"]["account"] == "Ada Lovelace"
    assert len(fake.refreshed) == 1
    assert ("access-token", "fresh-token") in STUB.renewals
    assert ("refresh-token", "fresh-refresh") in STUB.renewals


def test_run_401_without_refresh_token_instructs_relogin(
    files: dict[str, Path], fake: FakeLinkedInMember, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACET_SECRET_ACCESS_TOKEN", "expired-token")
    monkeypatch.delenv("FACET_SECRET_REFRESH_TOKEN", raising=False)
    with pytest.raises(ValueError, match="facet auth logout linkedin-member") as exc_info:
        RUNNER.runner._verbs["run"](_req("run", files))
    assert "facet auth login linkedin-member" in str(exc_info.value)


def test_verify_passes_when_matching_and_returns_unknown_when_forbidden(
    files: dict[str, Path], fake: FakeLinkedInMember
) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    req = _req("verify", files, {"post": run_res["post"]})
    result = RUNNER.runner._verbs["verify"](req)
    assert result["state"] == "published"
    assert result["media"] == [{"file": "banco.png", "alt": "La escuadra sobre el banco."}]

    fake.read_forbidden = True
    forbidden_res = RUNNER.runner._verbs["verify"](req)
    assert forbidden_res["state"] == "unknown"
    assert forbidden_res["warnings"]


def test_preview_writes_the_post_schema_beside_the_receipt(
    files: dict[str, Path], fake: FakeLinkedInMember
) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    receipt = files["dir"] / "post.post.json"
    receipt.write_text(json.dumps(run_res["post"]))
    req = _req("preview", files, {"assets": [str(receipt)]})
    result = RUNNER.runner._verbs["preview"](req)
    preview_file = files["dir"] / f"{receipt.name}.preview.json"
    assert result == {"assets": [{"file": preview_file.name}]}
    data = json.loads(preview_file.read_text(encoding="utf-8"))
    assert data["preview"] == 1
    assert data["kind"] == "post"
    assert data["network"] == "linkedin-member"
    assert data["account"] == "Ada Lovelace"
    assert data["state"] == "published"
    assert len(data["summary"]) <= SUMMARY_LIMIT


def test_doctor_quick_allows_missing_refresh_and_full_reports_member_name(
    files: dict[str, Path], fake: FakeLinkedInMember, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACET_SECRET_REFRESH_TOKEN", raising=False)
    req = _req("doctor", files)
    req.depth = "full"
    result = RUNNER.runner._verbs["doctor"](req)
    by_name = {check["name"]: check for check in result["checks"]}
    assert by_name["refresh-token"]["ok"] is True
    assert by_name["session"]["ok"] is True
    assert "Ada Lovelace" in by_name["session"]["detail"]


def test_authorize_url_carries_openid_profile_and_member_social_scopes() -> None:
    url = RUNNER.linkedin_member_client.authorize_url(
        "cid-1", "http://localhost:8080/callback", "state-xyz"
    )
    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["cid-1"]
    assert params["state"] == ["state-xyz"]
    assert params["scope"] == ["openid profile w_member_social"]


class _FakeResponse:
    def __init__(
        self, payload: bytes, status: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        self._payload = payload
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def _ok(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> None:
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *args, **kwargs: _FakeResponse(payload, status, headers)
    )


def test_exchange_code_accepts_answer_with_and_without_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RUNNER.linkedin_member_client
    _ok(monkeypatch, json.dumps({"access_token": "tok-1"}).encode())
    without = client.exchange_code("cid", "csec", "code-1", "http://localhost:8080/callback")
    assert without.access_token == "tok-1"
    assert without.refresh_token is None

    _ok(monkeypatch, json.dumps({"access_token": "tok-2", "refresh_token": "ref-2"}).encode())
    with_ref = client.exchange_code("cid", "csec", "code-2", "http://localhost:8080/callback")
    assert with_ref.access_token == "tok-2"
    assert with_ref.refresh_token == "ref-2"


def test_authorize_checks_state_and_stores_sub_as_member_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RUNNER.linkedin_member_client
    captured_urls: list[str] = []

    real_urlopen = urllib.request.urlopen

    def fake_urlopen(req: Any, timeout: float = 30.0) -> _FakeResponse:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "accessToken" in url:
            return _FakeResponse(json.dumps({"access_token": "tok-abc"}).encode())
        if "userinfo" in url:
            return _FakeResponse(json.dumps({"sub": "member-99", "name": "Grace"}).encode())
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(client.secrets, "token_urlsafe", lambda _n: "fixed-state")
    orig_print = print

    def capture_print(*args: Any, **kwargs: Any) -> None:
        captured_urls.append(" ".join(str(a) for a in args))
        orig_print(*args, **kwargs)

    monkeypatch.setattr("builtins.print", capture_print)

    def send_callbacks() -> None:
        for _ in range(40):
            try:
                real_urlopen("http://localhost:18089/callback?state=wrong-state&code=bad")
            except urllib.error.HTTPError as exc:
                assert exc.code == HTTPStatus.BAD_REQUEST
                break
            except OSError:
                threading.Event().wait(0.05)
        real_urlopen("http://localhost:18089/callback?state=fixed-state&code=good-code")

    worker = threading.Thread(target=send_callbacks, daemon=True)
    worker.start()
    result = client.authorize("cid", "csec", "http://localhost:18089/callback")
    worker.join(timeout=5.0)
    assert result == {"access-token": "tok-abc", "member-id": "member-99"}
    assert any("openid+profile+w_member_social" in msg for msg in captured_urls)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_authorize_announces_the_whole_address_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RUNNER.linkedin_member_client
    redirect_uri = f"http://localhost:{_free_port()}/callback"
    announced: list[str] = []

    real_urlopen = urllib.request.urlopen

    def fake_token_urlopen(req: Any, timeout: float = 30.0) -> _FakeResponse:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "accessToken" in url:
            return _FakeResponse(json.dumps({"access_token": "tok-abc"}).encode())
        if "userinfo" in url:
            return _FakeResponse(json.dumps({"sub": "member-99", "name": "Grace"}).encode())
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_token_urlopen)
    monkeypatch.setattr(client.secrets, "token_urlsafe", lambda _n: "fixed-state")

    def send_callbacks() -> None:
        for _ in range(40):
            try:
                real_urlopen(f"{redirect_uri}?state=fixed-state&code=good-code")
                return
            except OSError:
                threading.Event().wait(0.05)
        raise AssertionError("callback server did not accept connection")

    worker = threading.Thread(target=send_callbacks, daemon=True)
    worker.start()
    result = client.authorize("cid-1", "csec", redirect_uri, announce=announced.append)
    worker.join(timeout=5.0)
    assert result == {"access-token": "tok-abc", "member-id": "member-99"}
    assert len(announced) == 1
    assert announced[0].startswith("https://www.linkedin.com/oauth/v2/authorization?")
    assert "client_id=cid-1" in announced[0]


def test_authorize_default_announce_prints_the_whole_address(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = RUNNER.linkedin_member_client
    assert client.authorize.__defaults__ == (client._print_address,)
    client._print_address("https://www.linkedin.com/oauth/v2/authorization?client_id=cid-1")
    assert capsys.readouterr().out == (
        "open this address and sign in:\n"
        "https://www.linkedin.com/oauth/v2/authorization?client_id=cid-1\n"
    )


def test_auth_announces_through_the_core(
    files: dict[str, Path], fake: FakeLinkedInMember, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def capture(
        client_id: str, client_secret: str, redirect_uri: str, **kwargs: Any
    ) -> dict[str, str]:
        seen.update(kwargs)
        return {"access-token": "a", "member-id": "m-1"}

    monkeypatch.setattr(RUNNER.linkedin_member_client, "authorize", capture)
    result = RUNNER.runner._verbs["auth"](_req("auth", files))
    assert result == {"secrets": {"access-token": "a", "member-id": "m-1"}}
    assert seen["announce"] is STUB.announce_url


def test_run_video_uploads_chunks_polls_and_creates_post(
    files: dict[str, Path], fake: FakeLinkedInMember
) -> None:
    clip = files["dir"] / "demo-clip.mp4"
    payload = b"0123456789ABCDEF"
    clip.write_bytes(payload)
    req = _req("run", files, {"inputs": {"text": "Video update", "video": "demo-clip.mp4"}})
    result = RUNNER.runner._verbs["run"](req)
    assert result["tool"] == {"name": "LinkedIn Member", "version": "0.2.1"}
    assert result["post"]["state"] == "published"
    assert fake.video_inits == [(AUTHOR, len(payload))]
    assert [chunk for _, chunk in fake.video_chunks] == [b"01234567", b"89ABCDEF"]
    assert fake.video_finalizes == [("urn:li:video:vid1", "tok-1", ['"etag-1"', '"etag-2"'])]
    assert fake.video_statuses == []
    (body,) = fake.bodies
    assert body["content"] == {"media": {"id": "urn:li:video:vid1", "title": "demo-clip"}}


def test_run_video_403_on_get_video_warns_and_creates_post(
    files: dict[str, Path], fake: FakeLinkedInMember
) -> None:
    clip = files["dir"] / "clip.mp4"
    clip.write_bytes(b"AABBCCDD")
    fake.video_read_forbidden = True
    req = _req(
        "run",
        files,
        {"inputs": {"text": "Video update", "video": str(clip), "video-title": "Custom Title"}},
    )
    result = RUNNER.runner._verbs["run"](req)
    post = result["post"]
    assert post["state"] == "published"
    assert any("video status read-back forbidden" in w for w in post["warnings"])
    assert fake.bodies[0]["content"] == {
        "media": {"id": "urn:li:video:vid1", "title": "Custom Title"}
    }


def test_verify_and_preview_video_post(files: dict[str, Path], fake: FakeLinkedInMember) -> None:
    clip = files["dir"] / "clip.mp4"
    clip.write_bytes(b"AABBCCDD")
    video_inputs = {"text": "Video update", "video": "clip.mp4", "video-title": "My Clip"}
    run_res = RUNNER.runner._verbs["run"](_req("run", files, {"inputs": video_inputs}))

    verify_req = _req("verify", files, {"inputs": video_inputs, "post": run_res["post"]})
    verify_res = RUNNER.runner._verbs["verify"](verify_req)
    assert verify_res == {
        "state": "published",
        "media": [{"file": "clip.mp4", "title": "My Clip"}],
    }

    receipt = files["dir"] / "video.post.json"
    receipt.write_text(json.dumps(run_res["post"]))
    preview_req = _req("preview", files, {"inputs": video_inputs, "assets": [str(receipt)]})
    preview_res = RUNNER.runner._verbs["preview"](preview_req)
    preview_file = files["dir"] / preview_res["assets"][0]["file"]
    data = json.loads(preview_file.read_text(encoding="utf-8"))
    assert data["images"] == []
    assert data["posts"][0]["media"] == [{"file": "clip.mp4", "title": "My Clip"}]


def test_upload_video_chunk_missing_etag_and_wait_for_video_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RUNNER.linkedin_member_client
    _ok(monkeypatch, b"", status=200, headers={})
    with pytest.raises(LinkedInError, match="no ETag"):
        client.upload_video_chunk("https://upload.test/part1", b"abc")

    _ok(monkeypatch, b"", status=201, headers={"etag": '  "abc-1"  '})
    assert client.upload_video_chunk("https://upload.test/part1", b"abc") == '"abc-1"'

    monkeypatch.setattr(
        client,
        "get_video",
        lambda _tok, _urn: {"id": "urn:li:video:1", "status": "PROCESSING_FAILED"},
    )
    with pytest.raises(LinkedInError, match="PROCESSING_FAILED"):
        client.wait_for_video("tok", "urn:li:video:1", timeout_s=1.0, poll_interval_s=0.0)

    monkeypatch.setattr(
        client, "get_video", lambda _tok, _urn: {"id": "urn:li:video:1", "status": "PROCESSING"}
    )
    with pytest.raises(LinkedInError, match="timed out"):
        client.wait_for_video(
            "tok", "urn:li:video:1", timeout_s=0.0, poll_interval_s=0.0, sleep=lambda _s: None
        )


def test_client_video_init_finalize_and_get_video(monkeypatch: pytest.MonkeyPatch) -> None:
    client = RUNNER.linkedin_member_client
    seen: list[tuple[str, str, dict[str, Any] | None]] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float = 30.0) -> _FakeResponse:
        body = json.loads(req.data.decode("utf-8")) if req.data else None
        seen.append((req.get_method(), req.full_url, body))
        if "initializeUpload" in req.full_url:
            return _FakeResponse(
                json.dumps(
                    {
                        "value": {
                            "video": "urn:li:video:abc",
                            "uploadToken": "utok-1",
                            "uploadInstructions": [
                                {"uploadUrl": "https://up/1", "firstByte": 0, "lastByte": 9}
                            ],
                        }
                    }
                ).encode()
            )
        if "finalizeUpload" in req.full_url:
            return _FakeResponse(b"{}", status=200)
        return _FakeResponse(json.dumps({"id": "urn:li:video:abc", "status": "AVAILABLE"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    urn, tok, instructions = client.init_video_upload("acc", AUTHOR, 10)
    assert (urn, tok) == ("urn:li:video:abc", "utok-1")
    assert instructions == [{"uploadUrl": "https://up/1", "firstByte": 0, "lastByte": 9}]

    client.finalize_video_upload("acc", urn, tok, ['"e1"'])
    got = client.get_video("acc", urn)
    assert got["status"] == "AVAILABLE"
    assert seen == [
        (
            "POST",
            f"{client.API_HOST}{client.VIDEOS_INIT}",
            {
                "initializeUploadRequest": {
                    "owner": AUTHOR,
                    "fileSizeBytes": 10,
                    "uploadCaptions": False,
                    "uploadThumbnail": False,
                }
            },
        ),
        (
            "POST",
            f"{client.API_HOST}{client.VIDEOS_FINALIZE}",
            {
                "finalizeUploadRequest": {
                    "video": "urn:li:video:abc",
                    "uploadToken": "utok-1",
                    "uploadedPartIds": ['"e1"'],
                }
            },
        ),
        ("GET", f"{client.API_HOST}{client.VIDEOS}/urn%3Ali%3Avideo%3Aabc", None),
    ]

    _ok(
        monkeypatch,
        json.dumps(
            {
                "value": {
                    "video": "urn:li:video:abc",
                    "uploadToken": "t",
                    "uploadInstructions": [
                        {"uploadUrl": "https://up/1", "firstByte": True, "lastByte": 1}
                    ],
                }
            }
        ).encode(),
    )
    with pytest.raises(LinkedInError, match="byte bounds"):
        client.init_video_upload("acc", AUTHOR, 2)
