"""LinkedIn run, verify and preview with the network replaced by a fake."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import socket
import struct
import sys
import threading
import time
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
PACKAGE = ROOT / "packages" / "linkedin"
AUTHOR = "urn:li:organization:1234567"
SECRETS = (
    "CLIENT_ID",
    "CLIENT_SECRET",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "ORG_ID",
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
    for name in ("linkedin_runner", "linkedin_client"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("linkedin_runner", PACKAGE / "runner.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["linkedin_runner"] = module
    with contextlib.suppress(SystemExit):
        spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()
LinkedInError = RUNNER.linkedin_client.LinkedInError


class FakeLinkedIn:
    def __init__(self) -> None:
        self.token_ok = "good-token"
        self.counter = 0
        self.inits: list[str] = []
        self.uploads: list[tuple[str, bytes]] = []
        self.bodies: list[dict[str, Any]] = []
        self.posts: dict[str, dict[str, Any]] = {}
        self.refreshed: list[tuple[str, str, str]] = []
        self.info_error: Exception | None = None
        self.acl_entries = [
            {
                "organization": AUTHOR,
                "role": "ADMINISTRATOR",
                "roleAssignee": "urn:li:person:abc",
            }
        ]

    def _check(self, token: str) -> None:
        if token != self.token_ok:
            raise LinkedInError("rest/posts", 401, "the token expired")

    def userinfo(self, token: str) -> dict[str, Any]:
        self._check(token)
        if self.info_error is not None:
            raise self.info_error
        return {"sub": "abc", "name": "Laboratorio"}

    def organization_acls(self, token: str) -> list[dict[str, Any]]:
        self._check(token)
        return list(self.acl_entries)

    def organization(self, token: str, org_id: str) -> dict[str, Any]:
        self._check(token)
        return {"localizedName": "Laboratorio", "vanityName": "univerlab", "id": org_id}

    def init_image_upload(self, token: str, owner: str) -> tuple[str, str]:
        self._check(token)
        self.counter += 1
        urn = f"urn:li:image:img{self.counter}"
        self.inits.append(owner)
        return f"https://upload.test/{self.counter}", urn

    def upload_image(self, url: str, mime: str, data: bytes) -> None:
        self.uploads.append((mime, data))

    def create_post(self, token: str, body: dict[str, Any]) -> str:
        self._check(token)
        post_id = f"urn:li:share:{7000 + len(self.bodies)}"
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
        tokens_cls = RUNNER.linkedin_client.Tokens
        return tokens_cls(
            access_token="fresh-token",
            refresh_token="fresh-refresh",
            scopes=("w_organization_social", "r_organization_social"),
        )


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeLinkedIn:
    net = FakeLinkedIn()
    for name in SECRETS:
        monkeypatch.setenv(f"FACET_SECRET_{name}", "s3cr3t")
    monkeypatch.setenv("FACET_SECRET_ACCESS_TOKEN", net.token_ok)
    monkeypatch.setenv("FACET_SECRET_ORG_ID", "1234567")
    STUB.renewals.clear()
    client = RUNNER.linkedin_client
    monkeypatch.setattr(client, "userinfo", net.userinfo)
    monkeypatch.setattr(client, "organization_acls", net.organization_acls)
    monkeypatch.setattr(client, "organization", net.organization)
    monkeypatch.setattr(client, "init_image_upload", net.init_image_upload)
    monkeypatch.setattr(client, "upload_image", net.upload_image)
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
        "author": AUTHOR,
        "text": "La escuadra del laboratorio. #taller",
        "images": [{"path": str(files["still"]), "alt": "La escuadra sobre el banco."}],
    }
    data.update(over)
    return data


def _req(verb: str, files: dict[str, Path], data: dict[str, Any] | None = None) -> Any:
    payload: dict[str, Any] = {
        "verb": verb,
        "capability": "linkedin.post",
        "inputs": _inputs(files),
        "out_dir": str(files["dir"]),
        "piece_dir": str(files["dir"]),
    }
    if data:
        payload.update(data)
    return STUB.Request(payload)


def test_run_single_image_uploads_then_answers_a_published_receipt(
    files: dict[str, Path], fake: FakeLinkedIn
) -> None:
    result = RUNNER.runner._verbs["run"](_req("run", files))
    assert result["tool"] == {"name": "LinkedIn", "version": "0.1.5"}
    post = result["post"]
    assert post["network"] == "linkedin"
    assert post["account"] == "Laboratorio"
    assert post["state"] == "published"
    assert post["posts"] == [
        {
            "id": "urn:li:share:7000",
            "url": "https://www.linkedin.com/feed/update/urn:li:share:7000",
        }
    ]
    assert post["cost"] is None
    assert fake.inits == [AUTHOR]
    assert len(fake.uploads) == 1
    assert fake.uploads[0][0] == "image/png"
    (body,) = fake.bodies
    assert body["content"] == {
        "media": {"id": "urn:li:image:img1", "title": "La escuadra sobre el banco."}
    }


def test_run_text_only_sends_no_media(files: dict[str, Path], fake: FakeLinkedIn) -> None:
    req = _req("run", files, {"inputs": _inputs(files, images=[])})
    result = RUNNER.runner._verbs["run"](req)
    assert result["post"]["posts"][0]["id"] == "urn:li:share:7000"
    (body,) = fake.bodies
    assert "content" not in body
    assert fake.inits == [] and fake.uploads == []


def test_run_two_images_ride_one_multiimage_post(
    files: dict[str, Path], fake: FakeLinkedIn
) -> None:
    second = files["dir"] / "otra.png"
    second.write_bytes(_png(8, 8))
    inputs = _inputs(
        files,
        images=[
            {"path": str(files["still"]), "alt": "Una."},
            {"path": str(second), "alt": "Otra."},
        ],
    )
    result = RUNNER.runner._verbs["run"](_req("run", files, {"inputs": inputs}))
    assert result["post"]["posts"][0]["id"] == "urn:li:share:7000"
    (body,) = fake.bodies
    assert body["content"] == {
        "multiImage": {
            "images": [
                {"id": "urn:li:image:img1", "altText": "Una."},
                {"id": "urn:li:image:img2", "altText": "Otra."},
            ]
        }
    }


def test_run_refuses_over_count_images_before_anything_leaves(
    files: dict[str, Path], fake: FakeLinkedIn
) -> None:
    inputs = _inputs(
        files, images=[{"path": str(files["still"]), "alt": f"Vista {n}."} for n in range(21)]
    )
    with pytest.raises(ValueError, match="over the 20 limit"):
        RUNNER.runner._verbs["run"](_req("run", files, {"inputs": inputs}))
    assert fake.inits == [] and fake.uploads == [] and fake.bodies == []


def test_run_refuses_an_oversize_image_without_uploading(
    files: dict[str, Path], fake: FakeLinkedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER, "PIXEL_LIMIT", 8)
    with pytest.raises(ValueError, match="pixels, over"):
        RUNNER.runner._verbs["run"](_req("run", files))
    assert fake.inits == [] and fake.uploads == [] and fake.bodies == []


def test_run_refuses_an_overlong_text_before_anything_leaves(
    files: dict[str, Path], fake: FakeLinkedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER, "TEXT_LIMIT", 8)
    with pytest.raises(ValueError, match="over the 8 limit"):
        RUNNER.runner._verbs["run"](_req("run", files))
    assert fake.bodies == []


def test_run_refreshes_an_expired_token_through_store_back(
    files: dict[str, Path], fake: FakeLinkedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACET_SECRET_ACCESS_TOKEN", "expired-token")
    fake.token_ok = "fresh-token"
    result = RUNNER.runner._verbs["run"](_req("run", files))
    assert result["post"]["account"] == "Laboratorio"
    assert len(fake.refreshed) == 1
    assert ("access-token", "fresh-token") in STUB.renewals
    assert ("refresh-token", "fresh-refresh") in STUB.renewals


def test_verify_passes_when_text_and_media_count_match(
    files: dict[str, Path], fake: FakeLinkedIn
) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    req = _req("run", files, {"post": run_res["post"]})
    result = RUNNER.runner._verbs["verify"](req)
    assert result["state"] == "published"
    assert result["media"] == [{"file": "banco.png", "alt": "La escuadra sobre el banco."}]


def test_verify_fails_on_another_text(files: dict[str, Path], fake: FakeLinkedIn) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    fake.posts["urn:li:share:7000"]["commentary"] = "Otro texto."
    with pytest.raises(ValueError, match="another text"):
        RUNNER.runner._verbs["verify"](_req("run", files, {"post": run_res["post"]}))


def test_verify_fails_on_another_media_count(files: dict[str, Path], fake: FakeLinkedIn) -> None:
    run_res = RUNNER.runner._verbs["run"](_req("run", files))
    fake.posts["urn:li:share:7000"]["images"] = []
    with pytest.raises(ValueError, match="another media count"):
        RUNNER.runner._verbs["verify"](_req("run", files, {"post": run_res["post"]}))


def test_verify_refuses_an_unknown_post_id(files: dict[str, Path], fake: FakeLinkedIn) -> None:
    post = {
        "network": "linkedin",
        "account": "Laboratorio",
        "state": "published",
        "posts": [{"id": "urn:li:share:9", "url": "https://www.linkedin.com/feed/update/x"}],
        "cost": None,
    }
    with pytest.raises(ValueError, match="does not exist"):
        RUNNER.runner._verbs["verify"](_req("run", files, {"post": post}))


def _write_receipt(files: dict[str, Path], run_res: dict[str, Any]) -> Path:
    receipt = files["dir"] / "post.post.json"
    receipt.write_text(json.dumps(run_res["post"]))
    return receipt


def test_preview_writes_the_post_schema_beside_the_receipt(
    files: dict[str, Path], fake: FakeLinkedIn
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
    assert data["network"] == "linkedin"
    assert data["account"] == "Laboratorio"
    assert data["state"] == "published"
    assert len(data["summary"]) <= SUMMARY_LIMIT
    assert "public" in data["summary"] and "organization" in data["summary"]
    assert data["images"] == ["banco.png"]
    assert data["posts"] == [
        {
            "text": "La escuadra del laboratorio. #taller",
            "url": "https://www.linkedin.com/feed/update/urn:li:share:7000",
            "media": [{"file": "banco.png", "alt": "La escuadra sobre el banco."}],
        }
    ]


def test_doctor_full_names_the_member_role_and_scopes(
    files: dict[str, Path], fake: FakeLinkedIn
) -> None:
    req = _req("doctor", files)
    req.depth = "full"
    result = RUNNER.runner._verbs["doctor"](req)
    session = [check for check in result["checks"] if check["name"] == "session"][0]
    assert session["ok"] is True
    assert "ADMINISTRATOR" in session["detail"]
    assert "w_organization_social" in session["detail"]


def test_doctor_full_fails_without_a_company_page_role(
    files: dict[str, Path], fake: FakeLinkedIn
) -> None:
    fake.acl_entries = []
    req = _req("doctor", files)
    req.depth = "full"
    result = RUNNER.runner._verbs["doctor"](req)
    session = [check for check in result["checks"] if check["name"] == "session"][0]
    assert session["ok"] is False
    assert "Company Page role" in session["detail"]


def test_authorize_url_names_the_scopes_and_the_redirect() -> None:
    url = RUNNER.linkedin_client.authorize_url("cid-1", "http://localhost:8080/callback", "s")
    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
    assert "scope=w_organization_social" in url and "redirect_uri=" in url


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_authorize_announces_the_whole_address_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RUNNER.linkedin_client
    redirect_uri = f"http://localhost:{_free_port()}/callback"
    announced: list[str] = []

    real_urlopen = urllib.request.urlopen

    def fake_urlopen(req: Any, timeout: float = 30.0) -> _FakeResponse:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "accessToken" in url:
            return _FakeResponse(
                json.dumps({"access_token": "tok-1", "refresh_token": "ref-1"}).encode()
            )
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(client.secrets, "token_urlsafe", lambda _n: "fixed-state")

    def send_callbacks() -> None:
        for _ in range(40):
            try:
                real_urlopen(f"{redirect_uri}?state=fixed-state&code=code-1")
                return
            except OSError:
                threading.Event().wait(0.05)
        raise AssertionError("callback server did not accept connection")

    worker = threading.Thread(target=send_callbacks, daemon=True)
    worker.start()
    result = client.authorize("cid-1", "csec", redirect_uri, announce=announced.append)
    worker.join(timeout=5.0)
    assert result == {"access-token": "tok-1", "refresh-token": "ref-1"}
    assert len(announced) == 1
    assert announced[0].startswith("https://www.linkedin.com/oauth/v2/authorization?")
    assert "client_id=cid-1" in announced[0]


def test_authorize_default_announce_prints_the_whole_address(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = RUNNER.linkedin_client
    assert client.authorize.__defaults__ == (client._print_address,)
    client._print_address("https://www.linkedin.com/oauth/v2/authorization?client_id=cid-1")
    assert capsys.readouterr().out == (
        "open this address and sign in:\n"
        "https://www.linkedin.com/oauth/v2/authorization?client_id=cid-1\n"
    )


def test_auth_announces_through_the_core(
    files: dict[str, Path], fake: FakeLinkedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def capture(
        client_id: str, client_secret: str, redirect_uri: str, **kwargs: Any
    ) -> dict[str, str]:
        seen.update(kwargs)
        return {"access-token": "a", "refresh-token": "r"}

    monkeypatch.setattr(RUNNER.linkedin_client, "authorize", capture)
    result = RUNNER.runner._verbs["auth"](_req("auth", files))
    assert result == {"secrets": {"access-token": "a", "refresh-token": "r"}}
    assert seen["announce"] is STUB.announce_url


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


def _http_error(url: str, code: int, payload: dict[str, Any]) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url, code, "refused", {}, io.BytesIO(json.dumps(payload).encode("utf-8"))
    )


def _ok(
    monkeypatch: pytest.MonkeyPatch, payload: bytes, status: int, headers: dict[str, str]
) -> None:
    def fake_urlopen(*args: Any, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse(payload, status, headers)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_client_create_post_reads_the_post_id_from_the_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ok(monkeypatch, b"", HTTPStatus.CREATED, {"X-Restli-Id": "urn:li:share:7000"})
    assert RUNNER.linkedin_client.create_post("t", {"author": AUTHOR}) == "urn:li:share:7000"


def test_client_create_post_without_a_post_id_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    _ok(monkeypatch, b"", HTTPStatus.CREATED, {})
    with pytest.raises(LinkedInError, match="no Post ID"):
        RUNNER.linkedin_client.create_post("t", {"author": AUTHOR})


def test_organization_error_names_the_organizations_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ok(monkeypatch, b"[]", HTTPStatus.OK, {})
    with pytest.raises(LinkedInError, match="rest/organizations"):
        RUNNER.linkedin_client.organization("t", "1234567")


def test_client_init_upload_reads_url_and_urn(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {"value": {"uploadUrl": "https://up/x", "image": "urn:li:image:abc"}}
    ).encode()
    _ok(monkeypatch, payload, HTTPStatus.OK, {})
    client = RUNNER.linkedin_client
    assert client.init_image_upload("t", AUTHOR) == ("https://up/x", "urn:li:image:abc")


def test_client_maps_http_failures_to_linkedins_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"message": "Not enough permissions", "status": 403}
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(_http_error("https://x", 403, payload)),
    )
    with pytest.raises(LinkedInError, match="Not enough permissions"):
        RUNNER.linkedin_client.get_post("stale", "urn:li:share:1")


def test_authorize_aborts_immediately_on_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RUNNER.linkedin_client
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    redirect_uri = f"http://localhost:{port}/callback"
    seen_url: list[str] = []
    ready = threading.Event()
    orig_authorize_url = client.authorize_url

    def spy_url(cid: str, r_uri: str, state: str) -> str:
        url = orig_authorize_url(cid, r_uri, state)
        seen_url.append(url)
        ready.set()
        return url

    monkeypatch.setattr(client, "authorize_url", spy_url)
    callback_status: list[tuple[int, str, str]] = []

    def send_error() -> None:
        assert ready.wait(timeout=5.0)
        state = urllib.parse.parse_qs(urllib.parse.urlparse(seen_url[0]).query)["state"][0]
        target = (
            f"http://127.0.0.1:{port}/callback"
            f"?error=unauthorized_scope_error&error_description=The+scope+is+not+authorized&state={state}"
        )
        for _ in range(50):
            try:
                with pytest.raises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(target, timeout=2.0)
                ctype = caught.value.headers.get("Content-Type", "")
                body = caught.value.read().decode("utf-8")
                callback_status.append((caught.value.code, ctype, body))
                return
            except urllib.error.URLError:
                time.sleep(0.05)

    thread = threading.Thread(target=send_error, daemon=True)
    thread.start()
    started = time.monotonic()
    with pytest.raises(LinkedInError, match="The scope is not authorized"):
        client.authorize("cid", "csec", redirect_uri, announce=lambda _: None)
    elapsed = time.monotonic() - started
    thread.join(timeout=5.0)
    max_abort_s = 5.0
    assert elapsed < max_abort_s
    assert callback_status
    code, ctype, body = callback_status[0]
    assert code == HTTPStatus.BAD_REQUEST
    assert "text/html" in ctype
    assert "The scope is not authorized" in body
