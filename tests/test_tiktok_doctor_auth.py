"""TikTok auth, doctor and the store-back of a renewed token."""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import importlib.util
import json
import os
import socket
import sys
import threading
import time
import types
import urllib.parse
import urllib.request
from http import HTTPStatus
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


class FakeTikTok:
    def __init__(self) -> None:
        self.token_ok = "good-token"
        self.authorized: dict[str, str] = {
            "access-token": "fresh-access",
            "refresh-token": "fresh-refresh",
            "open-id": "open-1",
        }
        self.authorize_error: Exception | None = None
        self.missing_scope = False
        self.refreshes = 0
        self.redirect_uri: str | None = None

    def _check(self, token: str) -> None:
        if token != self.token_ok:
            raise TikTokError("endpoint", 401, "access_token_invalid: expired")

    def creator_info(self, token: str) -> dict[str, Any]:
        self._check(token)
        if self.missing_scope:
            raise TikTokError("creator_info", 401, "scope_not_authorized: no grant")
        return {"creator_username": "lab", "creator_nickname": "Laboratorio"}

    def user_info(self, token: str) -> dict[str, Any]:
        self._check(token)
        return {"display_name": "Laboratorio", "open_id": "open-1"}

    def refresh_tokens(self, key: str, client_secret: str, refresh_token: str) -> Any:
        self.refreshes += 1
        tokens_cls = RUNNER.tiktok_client.Tokens
        return tokens_cls(
            access_token="fresh-token",
            refresh_token="fresh-refresh",
            open_id="open-1",
            scopes=("user.info.basic", "video.upload"),
        )

    def authorize(self, key: str, client_secret: str, redirect_uri: str) -> dict[str, str]:
        if self.authorize_error is not None:
            raise self.authorize_error
        self.redirect_uri = redirect_uri
        assert key == "s3cr3t" and redirect_uri.startswith("http://127.0.0.1")
        return dict(self.authorized)


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
    monkeypatch.setattr(client, "refresh_tokens", net.refresh_tokens)
    monkeypatch.setattr(client, "authorize", net.authorize)
    return net


def _req(verb: str, tmp_path: Path, depth: str = "quick") -> Any:
    return STUB.Request(
        {
            "verb": verb,
            "capability": "tiktok.post",
            "depth": depth,
            "inputs": {},
            "out_dir": str(tmp_path),
            "piece_dir": str(tmp_path),
        }
    )


def test_auth_returns_the_secrets_map(tmp_path: Path, fake: FakeTikTok) -> None:
    result = RUNNER.runner._verbs["auth"](_req("auth", tmp_path))
    assert result == {"secrets": fake.authorized}
    assert set(result["secrets"]) == {"access-token", "refresh-token", "open-id"}
    assert fake.redirect_uri == "http://127.0.0.1:8080/callback/"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _FakeTokenResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> _FakeTokenResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


MIN_VERIFIER_LEN = 64
MAX_VERIFIER_LEN = 128


@pytest.mark.parametrize("callback_path", ["/callback/", "/callback"])
def test_authorize_pkce_and_callback_slash_handling(
    callback_path: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = RUNNER.tiktok_client
    port = _free_port()
    redirect_uri = f"http://127.0.0.1:{port}/callback/"
    seen_url: list[str] = []
    seen_token_body: list[dict[str, Any]] = []
    ready = threading.Event()
    orig_authorize_url = client.authorize_url

    def spy_authorize_url(client_key: str, r_uri: str, state: str, code_challenge: str) -> str:
        url = orig_authorize_url(client_key, r_uri, state, code_challenge)
        seen_url.append(url)
        ready.set()
        return url

    def fake_urlopen(request: urllib.request.Request, timeout: float = 30.0) -> _FakeTokenResponse:
        assert request.data is not None
        seen_token_body.append(json.loads(request.data.decode("utf-8")))
        return _FakeTokenResponse(
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

    monkeypatch.setattr(client, "authorize_url", spy_authorize_url)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    def send_callback() -> None:
        assert ready.wait(timeout=5.0)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(seen_url[0]).query)
        state = query["state"][0]
        for _ in range(50):
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
                conn.request("GET", f"{callback_path}?state={state}&code=code-1")
                resp = conn.getresponse()
                assert resp.status == HTTPStatus.OK
                conn.close()
                return
            except OSError:
                time.sleep(0.05)
        raise AssertionError("callback server did not accept connection")

    thread = threading.Thread(target=send_callback, daemon=True)
    thread.start()
    result = client.authorize("k1", "s1", redirect_uri)
    thread.join(timeout=5.0)

    assert result == {"access-token": "a1", "refresh-token": "r1", "open-id": "o1"}
    out = capsys.readouterr().out
    assert redirect_uri in out
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(seen_url[0]).query)
    assert qs["code_challenge_method"] == ["S256"]
    verifier = seen_token_body[0]["code_verifier"]
    assert MIN_VERIFIER_LEN <= len(verifier) <= MAX_VERIFIER_LEN
    assert qs["code_challenge"] == [hashlib.sha256(verifier.encode("ascii")).hexdigest()]


def test_auth_refuses_without_the_stored_app_pair(
    tmp_path: Path, fake: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACET_SECRET_CLIENT_KEY")
    with pytest.raises(ValueError, match="client-key"):
        RUNNER.runner._verbs["auth"](_req("auth", tmp_path))


def test_auth_reports_a_sign_in_failure(tmp_path: Path, fake: FakeTikTok) -> None:
    fake.authorize_error = TikTokError("authorize", None, "no sign-in code arrived")
    with pytest.raises(ValueError, match="no sign-in code"):
        RUNNER.runner._verbs["auth"](_req("auth", tmp_path))


def test_doctor_quick_checks_imports_and_secrets(tmp_path: Path, fake: FakeTikTok) -> None:
    result = RUNNER.runner._verbs["doctor"](_req("doctor", tmp_path))
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["imports"]["ok"] is True
    for name in ("client-key", "client-secret", "access-token", "refresh-token", "open-id"):
        assert checks[name]["ok"] is True
    assert "session" not in checks


def test_doctor_quick_names_a_missing_secret(
    tmp_path: Path, fake: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FACET_SECRET_OPEN_ID")
    result = RUNNER.runner._verbs["doctor"](_req("doctor", tmp_path))
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["open-id"]["ok"] is False
    assert checks["open-id"]["fix"]


def test_doctor_full_reports_account_and_grant(tmp_path: Path, fake: FakeTikTok) -> None:
    result = RUNNER.runner._verbs["doctor"](_req("doctor", tmp_path, depth="full"))
    checks = {check["name"]: check for check in result["checks"]}
    session = checks["session"]
    assert session["ok"] is True
    assert "@lab" in session["detail"]
    assert "video.upload" in session["detail"]


def test_doctor_full_names_a_missing_scope_grant(tmp_path: Path, fake: FakeTikTok) -> None:
    fake.missing_scope = True
    result = RUNNER.runner._verbs["doctor"](_req("doctor", tmp_path, depth="full"))
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["session"]["ok"] is False
    assert "video.upload" in checks["session"]["detail"]
    assert checks["session"]["fix"]
    assert fake.refreshes == 0


def test_doctor_full_refreshes_only_through_store_back(
    tmp_path: Path, fake: FakeTikTok, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FACET_SECRET_ACCESS_TOKEN", "expired-token")
    fake.token_ok = "fresh-token"
    result = RUNNER.runner._verbs["doctor"](_req("doctor", tmp_path, depth="full"))
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["session"]["ok"] is True
    assert fake.refreshes >= 1
    assert ("access-token", "fresh-token") in STUB.renewals
    assert ("refresh-token", "fresh-refresh") in STUB.renewals
