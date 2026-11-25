"""The x client: every network call the runner makes, replaced at the edge.

These tests load ``x_client`` on its own and replace ``urlopen`` (or the
one helper above it), so no account, credit or socket is touched — except
the sign-in tests, which drive the loopback callback over a real
loopback socket and a stubbed code exchange. They pin the authorize URL
(including S256 and the scope list), the state check, the token exchange
with Basic auth, the bearer on every call, the v2 media upload shapes,
the video/GIF processing poll and the write probe the doctor relies on.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "x"
#: What the network answers when the token may not write.
FORBIDDEN = 403
#: What the network's next-check hint defaults to when it gives none.
DEFAULT_CHECK_AFTER = 5.0
#: The bearer every call below must carry.
TOKEN = "token-1"


def _load_client() -> Any:
    spec = importlib.util.spec_from_file_location("x_client", PACKAGE / "x_client.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["x_client"] = module
    spec.loader.exec_module(module)
    return module


CLIENT = _load_client()


class FakeResponse:
    """A response body, as ``urlopen`` returns it inside a context manager."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class Captured:
    """The request a fake ``urlopen`` saw."""

    def __init__(self) -> None:
        self.url = ""
        self.data: bytes | None = None
        self.auth = ""
        self.content_type = ""

    def json(self) -> Any:
        assert self.data is not None
        return json.loads(self.data)

    def form(self) -> dict[str, str]:
        assert self.data is not None
        return {key: values[0] for key, values in urllib.parse.parse_qs(self.data.decode()).items()}


def _answer(payload: Any, captured: Captured) -> Any:
    def fake_open(request: Any, timeout: float | None = None) -> FakeResponse:
        captured.url = request.full_url
        captured.data = request.data
        captured.auth = request.get_header("Authorization") or ""
        captured.content_type = request.get_header("Content-type") or ""
        return FakeResponse(json.dumps(payload).encode())

    return fake_open


def test_authorize_url_carries_pkce_and_the_scope_list() -> None:
    url = CLIENT.authorize_url("id-1", "http://127.0.0.1:8080/callback", "state-1", "challenge-1")
    assert url.startswith(CLIENT.AUTHORIZE_URL + "?")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query == {
        "response_type": ["code"],
        "client_id": ["id-1"],
        "redirect_uri": ["http://127.0.0.1:8080/callback"],
        "scope": ["tweet.read tweet.write users.read media.write offline.access"],
        "state": ["state-1"],
        "code_challenge": ["challenge-1"],
        "code_challenge_method": ["S256"],
    }


def test_challenge_is_the_unpadded_s256_of_the_verifier() -> None:
    expected = base64.urlsafe_b64encode(hashlib.sha256(b"v").digest()).decode().rstrip("=")
    assert CLIENT._challenge("v") == expected
    assert "=" not in CLIENT._challenge("a much longer verifier string")


def test_exchange_code_uses_basic_auth_and_the_pkce_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = Captured()
    monkeypatch.setattr(
        CLIENT.urllib.request,
        "urlopen",
        _answer({"access_token": "a", "refresh_token": "r"}, captured),
    )
    tokens = CLIENT.exchange_code(
        "id-1", "sec-1", "code-1", "http://127.0.0.1:8080/callback", "verifier-1"
    )
    assert tokens.access_token == "a"
    assert tokens.refresh_token == "r"
    assert captured.url == CLIENT.TOKEN_URL
    assert captured.auth == "Basic " + base64.b64encode(b"id-1:sec-1").decode()
    assert captured.form() == {
        "grant_type": "authorization_code",
        "code": "code-1",
        "redirect_uri": "http://127.0.0.1:8080/callback",
        "code_verifier": "verifier-1",
    }


def test_exchange_code_refuses_an_answer_without_an_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        CLIENT.urllib.request, "urlopen", _answer({"refresh_token": "r"}, Captured())
    )
    with pytest.raises(CLIENT.XError, match="no access token"):
        CLIENT.exchange_code("id-1", "sec-1", "code-1", "http://x/cb", "verifier-1")


def test_refresh_tokens_trades_the_refresh_token_with_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = Captured()
    monkeypatch.setattr(
        CLIENT.urllib.request,
        "urlopen",
        _answer({"access_token": "fresh", "refresh_token": "rotated"}, captured),
    )
    tokens = CLIENT.refresh_tokens("id-1", "sec-1", "old-refresh")
    assert tokens.access_token == "fresh"
    assert tokens.refresh_token == "rotated"
    assert captured.url == CLIENT.TOKEN_URL
    assert captured.auth == "Basic " + base64.b64encode(b"id-1:sec-1").decode()
    assert captured.form() == {"grant_type": "refresh_token", "refresh_token": "old-refresh"}


def test_refresh_tokens_keeps_an_answer_without_a_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        CLIENT.urllib.request, "urlopen", _answer({"access_token": "fresh"}, Captured())
    )
    tokens = CLIENT.refresh_tokens("id-1", "sec-1", "old-refresh")
    assert tokens.access_token == "fresh"
    assert tokens.refresh_token is None


def _free_redirect() -> str:
    """A loopback callback address on a port nothing holds right now."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/callback"


def _run_authorize(
    monkeypatch: pytest.MonkeyPatch,
    redirect: str,
    exchanged: dict[str, Any],
    announce: Any = None,
) -> dict[str, Any]:
    """Run the sign-in in a thread with fixed PKCE values and a stubbed exchange."""
    fixed = iter(["state-1", "verifier-1"])
    monkeypatch.setattr(CLIENT.secrets, "token_urlsafe", lambda n: next(fixed))

    def fake_exchange(
        client_id: str, client_secret: str, code: str, uri: str, verifier: str
    ) -> Any:
        exchanged.update(code=code, uri=uri, verifier=verifier)
        assert (client_id, client_secret) == ("id-1", "sec-1")
        return CLIENT.Tokens(access_token="a", refresh_token="r")

    monkeypatch.setattr(CLIENT, "exchange_code", fake_exchange)
    outcome: dict[str, Any] = {}
    thread = threading.Thread(
        target=lambda: outcome.setdefault("result", _authorize_catch(redirect, outcome, announce)),
        daemon=True,
    )
    thread.start()
    return {"thread": thread, "outcome": outcome, "redirect": redirect}


def _authorize_catch(redirect: str, outcome: dict[str, Any], announce: Any = None) -> Any:
    try:
        if announce is None:
            return CLIENT.authorize("id-1", "sec-1", redirect)
        return CLIENT.authorize("id-1", "sec-1", redirect, announce=announce)
    except Exception as exc:  # noqa: BLE001 - the thread must report, not raise
        outcome["error"] = exc
        return None


def _callback(redirect: str, query: str) -> bytes:
    with urllib.request.urlopen(f"{redirect}?{query}", timeout=5) as response:
        return response.read()


def test_authorize_exchanges_the_returned_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run_authorize(monkeypatch, _free_redirect(), exchanged := {})
    time.sleep(0.5)
    _callback(run["redirect"], "code=code-1&state=state-1")
    run["thread"].join(timeout=10)
    assert run["outcome"]["result"] == {"access-token": "a", "refresh-token": "r"}
    assert exchanged == {
        "code": "code-1",
        "uri": run["redirect"],
        "verifier": "verifier-1",
    }
    printed = capsys.readouterr().out
    assert printed.startswith("open this address and sign in:\nhttps://x.com/i/oauth2/authorize?")


def test_authorize_announces_the_whole_address_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    announced: list[str] = []
    run = _run_authorize(monkeypatch, _free_redirect(), {}, announce=announced.append)
    time.sleep(0.5)
    _callback(run["redirect"], "code=code-1&state=state-1")
    run["thread"].join(timeout=10)
    assert run["outcome"]["result"] == {"access-token": "a", "refresh-token": "r"}
    assert len(announced) == 1
    assert announced[0].startswith("https://x.com/i/oauth2/authorize?")
    assert "client_id=id-1" in announced[0]


def test_authorize_default_announce_prints_the_whole_address(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert CLIENT.authorize.__defaults__ == (CLIENT._print_address,)
    run = _run_authorize(monkeypatch, _free_redirect(), exchanged := {})
    time.sleep(0.5)
    _callback(run["redirect"], "code=code-1&state=state-1")
    run["thread"].join(timeout=10)
    assert run["outcome"]["result"] == {"access-token": "a", "refresh-token": "r"}
    assert exchanged["code"] == "code-1"
    printed = capsys.readouterr().out
    assert "client_id=id-1" in printed


def test_authorize_answers_a_wrong_state_with_400_and_keeps_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_authorize(monkeypatch, _free_redirect(), {})
    time.sleep(0.5)
    with pytest.raises(urllib.error.HTTPError) as caught:
        _callback(run["redirect"], "code=code-1&state=wrong-state")
    assert caught.value.code == HTTPStatus.BAD_REQUEST
    _callback(run["redirect"], "code=code-1&state=state-1")
    run["thread"].join(timeout=10)
    assert run["outcome"]["result"] == {"access-token": "a", "refresh-token": "r"}


def test_authorize_refuses_a_non_loopback_redirect() -> None:
    with pytest.raises(CLIENT.XError, match="http loopback"):
        CLIENT.authorize("id-1", "sec-1", "https://example.com/callback")


def test_authorize_reports_when_no_code_arrives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CLIENT, "SIGNIN_TIMEOUT_S", 0.0)
    run = _run_authorize(monkeypatch, _free_redirect(), {})
    run["thread"].join(timeout=10)
    assert isinstance(run["outcome"].get("error"), CLIENT.XError)
    assert "no sign-in code arrived" in str(run["outcome"]["error"])


def test_authorize_quotes_the_rejection_in_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run_authorize(monkeypatch, _free_redirect(), {})
    time.sleep(0.5)
    with pytest.raises(urllib.error.HTTPError):
        _callback(run["redirect"], "error=access_denied&error_description=user+denied+it")
    run["thread"].join(timeout=10)
    error = run["outcome"].get("error")
    assert isinstance(error, CLIENT.XError)
    assert "user denied it" in str(error)
    assert "\n" not in str(error)


def test_whoami_reads_the_authenticated_user(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = Captured()
    monkeypatch.setattr(
        CLIENT.urllib.request,
        "urlopen",
        _answer({"data": {"id": "1", "username": "lab", "name": "Laboratorio"}}, captured),
    )
    user = CLIENT.whoami(TOKEN)
    assert user == {"id": "1", "username": "lab", "name": "Laboratorio"}
    assert captured.url == "https://api.x.com/2/users/me"
    assert captured.auth == "Bearer token-1"


def test_whoami_refuses_an_answer_without_a_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", _answer({"data": {}}, Captured()))
    with pytest.raises(CLIENT.XError, match="not a user"):
        CLIENT.whoami(TOKEN)


def test_create_post_sends_text_media_and_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = Captured()
    monkeypatch.setattr(
        CLIENT.urllib.request,
        "urlopen",
        _answer({"data": {"id": "9", "text": "hola"}}, captured),
    )
    created = CLIENT.create_post(TOKEN, "hola", media_ids=["1", "2"], reply_to="8")
    assert created == {"id": "9", "text": "hola"}
    assert captured.url == "https://api.x.com/2/tweets"
    assert captured.auth == "Bearer token-1"
    assert captured.json() == {
        "text": "hola",
        "media": {"media_ids": ["1", "2"]},
        "reply": {"in_reply_to_tweet_id": "8"},
    }


def test_create_post_refuses_an_answer_without_an_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", _answer({"data": {}}, Captured()))
    with pytest.raises(CLIENT.XError, match="no post id"):
        CLIENT.create_post(TOKEN, "hola")


def test_get_posts_asks_for_text_and_attachments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = Captured()
    monkeypatch.setattr(
        CLIENT.urllib.request,
        "urlopen",
        _answer({"data": [{"id": "1", "text": "hola"}]}, captured),
    )
    found = CLIENT.get_posts(TOKEN, ["1", "2"])
    assert found == [{"id": "1", "text": "hola"}]
    assert "ids=1%2C2" in captured.url
    assert "tweet.fields=text%2Cattachments" in captured.url
    assert captured.auth == "Bearer token-1"


def test_get_posts_refuses_an_answer_without_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", _answer({"data": {}}, Captured()))
    with pytest.raises(CLIENT.XError, match="no posts"):
        CLIENT.get_posts(TOKEN, ["1"])


def test_set_alt_text_posts_the_v2_metadata_call(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = Captured()
    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", _answer({}, captured))
    CLIENT.set_alt_text(TOKEN, "77", "La escuadra.")
    assert captured.url == "https://api.x.com/2/media/metadata"
    assert captured.auth == "Bearer token-1"
    assert captured.json() == {"media_id": "77", "alt_text": {"text": "La escuadra."}}


def test_a_refused_call_carries_the_servers_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: Any, timeout: float | None = None) -> FakeResponse:
        body = io.BytesIO(b'{"errors": [{"message": "read only token"}]}')
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", None, body)

    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", refuse)
    with pytest.raises(CLIENT.XError) as caught:
        CLIENT.whoami(TOKEN)
    assert caught.value.status == FORBIDDEN
    assert "read only token" in str(caught.value)


def test_upload_media_sends_init_chunks_and_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bytes | None, str]] = []

    def fake_open(request: Any, timeout: float | None = None) -> FakeResponse:
        calls.append((request.full_url, request.data, request.get_header("Authorization") or ""))
        if request.full_url.endswith("/initialize"):
            return FakeResponse(json.dumps({"data": {"id": "77"}}).encode())
        if "/append" in request.full_url:
            return FakeResponse(b"{}")
        if request.full_url.endswith("/finalize"):
            return FakeResponse(
                json.dumps({"data": {"processing_info": {"state": "succeeded"}}}).encode()
            )
        raise AssertionError(request.full_url)

    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", fake_open)
    data = b"x" * (CLIENT.CHUNK_SIZE + 1)
    chunks = (len(data) + CLIENT.CHUNK_SIZE - 1) // CLIENT.CHUNK_SIZE
    assert CLIENT.upload_media(TOKEN, data, "video/mp4", "tweet_video") == "77"
    init = [call for call in calls if call[0].endswith("/initialize")]
    assert len(init) == 1
    assert json.loads(init[0][1] or b"") == {
        "media_category": "tweet_video",
        "media_type": "video/mp4",
        "total_bytes": len(data),
    }
    appends = [call for call in calls if "/append" in call[0]]
    assert len(appends) == chunks
    assert all(call[0] == "https://api.x.com/2/media/upload/77/append" for call in appends)
    bodies = [call[1] or b"" for call in appends]
    assert b'name="segment_index"\r\n\r\n0' in bodies[0]
    assert b'name="segment_index"\r\n\r\n1' in bodies[1]
    assert all(call[2] == "Bearer token-1" for call in calls)


def test_upload_media_refuses_an_init_without_an_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", _answer({"data": {}}, Captured()))
    with pytest.raises(CLIENT.XError, match="no media id"):
        CLIENT.upload_media(TOKEN, b"x", "image/png", "tweet_image")


def test_wait_processing_polls_until_the_media_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(
        [
            {"processing_info": {"state": "in_progress", "check_after_secs": 0}},
            {"processing_info": {"state": "succeeded"}},
        ]
    )
    sleeps: list[float] = []
    monkeypatch.setattr(CLIENT, "_media_status", lambda token, media_id: next(answers))
    monkeypatch.setattr(CLIENT.time, "sleep", sleeps.append)
    CLIENT._wait_processing(
        TOKEN, "77", {"processing_info": {"state": "pending", "check_after_secs": 0}}
    )
    assert sleeps == [CLIENT.CHECK_AFTER_MIN_S, CLIENT.CHECK_AFTER_MIN_S]


def test_wait_processing_returns_when_there_is_nothing_to_wait_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        CLIENT, "_media_status", lambda token, media_id: seen.append(media_id) or {}
    )
    CLIENT._wait_processing(TOKEN, "77", {})
    CLIENT._wait_processing(TOKEN, "77", {"processing_info": {"state": "succeeded"}})
    assert seen == []


def test_wait_processing_names_a_failed_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    info = {"state": "failed", "error": {"message": "unsupported codec"}}
    with pytest.raises(CLIENT.XError, match="unsupported codec"):
        CLIENT._wait_processing(TOKEN, "77", {"processing_info": info})


def test_wait_processing_gives_up_after_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CLIENT, "PROCESSING_TIMEOUT_S", 0.0)
    with pytest.raises(CLIENT.XError, match="did not finish"):
        CLIENT._wait_processing(TOKEN, "77", {"processing_info": {"state": "pending"}})


def test_the_processing_delay_is_clamped_and_tolerates_junk() -> None:
    assert CLIENT._processing_delay({}) == DEFAULT_CHECK_AFTER
    assert CLIENT._processing_delay({"check_after_secs": 0}) == CLIENT.CHECK_AFTER_MIN_S
    assert CLIENT._processing_delay({"check_after_secs": 999}) == CLIENT.CHECK_AFTER_MAX_S
    assert CLIENT._processing_delay({"check_after_secs": "soon"}) == DEFAULT_CHECK_AFTER


@pytest.mark.parametrize(
    ("status", "expected"),
    [(400, True), (401, False), (403, False), (422, True)],
)
def test_probe_write_reads_the_refusal(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: bool
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise CLIENT.XError("POST /2/tweets", status, "refused")

    monkeypatch.setattr(CLIENT, "_request", refuse)
    assert CLIENT.probe_write(TOKEN) is expected


def test_probe_write_returns_true_when_the_network_takes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(CLIENT, "_request", lambda *args, **kwargs: {"data": {"id": "1"}})
    assert CLIENT.probe_write(TOKEN) is True


def test_probe_write_does_not_guess_about_an_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise CLIENT.XError("POST /2/tweets", None, "unreachable")

    monkeypatch.setattr(CLIENT, "_request", broken)
    with pytest.raises(CLIENT.XError, match="unreachable"):
        CLIENT.probe_write(TOKEN)
