"""The x client: every network call the runner makes, replaced at the edge.

These tests load ``x_client`` on its own and replace ``urlopen`` (or the
one helper above it), so no account, credit or socket is touched. They
pin the request bodies, the OAuth signing of a multipart chunk, the
video/GIF processing poll and the write probe the doctor relies on.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "x"
#: What the network answers when the token may not write.
FORBIDDEN = 403
#: What the network's next-check hint defaults to when it gives none.
DEFAULT_CHECK_AFTER = 5.0


def _load_client() -> Any:
    spec = importlib.util.spec_from_file_location("x_client", PACKAGE / "x_client.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["x_client"] = module
    spec.loader.exec_module(module)
    return module


CLIENT = _load_client()
KEYS = CLIENT.Keys("consumer", "app-secret", "token", "token-secret")


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

    def json(self) -> Any:
        assert self.data is not None
        return json.loads(self.data)


def _answer(payload: Any, captured: Captured) -> Any:
    def fake_open(request: Any, timeout: float | None = None) -> FakeResponse:
        captured.url = request.full_url
        captured.data = request.data
        captured.auth = request.get_header("Authorization") or ""
        return FakeResponse(json.dumps(payload).encode())

    return fake_open


def test_whoami_reads_the_authenticated_user(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = Captured()
    monkeypatch.setattr(
        CLIENT.urllib.request,
        "urlopen",
        _answer({"data": {"id": "1", "username": "lab", "name": "Laboratorio"}}, captured),
    )
    user = CLIENT.whoami(KEYS)
    assert user == {"id": "1", "username": "lab", "name": "Laboratorio"}
    assert captured.url == "https://api.x.com/2/users/me"
    assert captured.auth.startswith("OAuth ")


def test_whoami_refuses_an_answer_without_a_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", _answer({"data": {}}, Captured()))
    with pytest.raises(CLIENT.XError, match="not a user"):
        CLIENT.whoami(KEYS)


def test_create_post_sends_text_media_and_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = Captured()
    monkeypatch.setattr(
        CLIENT.urllib.request,
        "urlopen",
        _answer({"data": {"id": "9", "text": "hola"}}, captured),
    )
    created = CLIENT.create_post(KEYS, "hola", media_ids=["1", "2"], reply_to="8")
    assert created == {"id": "9", "text": "hola"}
    assert captured.url == "https://api.x.com/2/tweets"
    assert captured.json() == {
        "text": "hola",
        "media": {"media_ids": ["1", "2"]},
        "reply": {"in_reply_to_tweet_id": "8"},
    }


def test_create_post_refuses_an_answer_without_an_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", _answer({"data": {}}, Captured()))
    with pytest.raises(CLIENT.XError, match="no post id"):
        CLIENT.create_post(KEYS, "hola")


def test_get_posts_asks_for_text_and_attachments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = Captured()
    monkeypatch.setattr(
        CLIENT.urllib.request,
        "urlopen",
        _answer({"data": [{"id": "1", "text": "hola"}]}, captured),
    )
    found = CLIENT.get_posts(KEYS, ["1", "2"])
    assert found == [{"id": "1", "text": "hola"}]
    assert "ids=1%2C2" in captured.url
    assert "tweet.fields=text%2Cattachments" in captured.url


def test_get_posts_refuses_an_answer_without_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", _answer({"data": {}}, Captured()))
    with pytest.raises(CLIENT.XError, match="no posts"):
        CLIENT.get_posts(KEYS, ["1"])


def test_set_alt_text_posts_the_metadata_call(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = Captured()
    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", _answer({}, captured))
    CLIENT.set_alt_text(KEYS, "77", "La escuadra.")
    assert captured.url.endswith("/1.1/media/metadata/create.json")
    assert captured.json() == {"media_id": "77", "alt_text": {"text": "La escuadra."}}


def test_a_refused_call_carries_the_servers_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: Any, timeout: float | None = None) -> FakeResponse:
        body = io.BytesIO(b'{"errors": [{"message": "read only token"}]}')
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", None, body)

    monkeypatch.setattr(CLIENT.urllib.request, "urlopen", refuse)
    with pytest.raises(CLIENT.XError) as caught:
        CLIENT.whoami(KEYS)
    assert caught.value.status == FORBIDDEN
    assert "read only token" in str(caught.value)


def test_append_chunk_does_not_sign_the_multipart_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_auth(method: str, url: str, query: Any, body: Any, keys: Any) -> str:
        captured.update(method=method, url=url, query=query, body=body)
        return "OAuth test"

    monkeypatch.setattr(CLIENT, "_auth_header", fake_auth)
    monkeypatch.setattr(
        CLIENT.urllib.request, "urlopen", lambda request, timeout=None: FakeResponse(b"")
    )
    CLIENT._append_chunk(KEYS, "77", 2, b"abc")
    assert captured["method"] == "POST"
    assert captured["url"] == "https://upload.x.com/1.1/media/upload.json"
    assert captured["query"] == {}
    assert captured["body"] == {}


def test_upload_media_sends_init_chunks_and_finalize(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, str]] = []
    appends: list[tuple[str, int, int]] = []

    def fake_v11(keys: Any, fields: dict[str, str]) -> dict[str, Any]:
        calls.append(fields)
        if fields["command"] == "INIT":
            return {"media_id_string": "77"}
        if fields["command"] == "FINALIZE":
            return {"processing_info": {"state": "succeeded"}}
        return {}

    def fake_append(keys: Any, media_id: str, segment: int, chunk: bytes) -> None:
        appends.append((media_id, segment, len(chunk)))

    monkeypatch.setattr(CLIENT, "_v11", fake_v11)
    monkeypatch.setattr(CLIENT, "_append_chunk", fake_append)
    data = b"x" * (CLIENT.CHUNK_SIZE + 1)
    assert CLIENT.upload_media(KEYS, data, "video/mp4", "tweet_video") == "77"
    assert [call["command"] for call in calls] == ["INIT", "FINALIZE"]
    assert appends == [("77", 0, CLIENT.CHUNK_SIZE), ("77", 1, 1)]


def test_upload_media_refuses_an_init_without_an_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CLIENT, "_v11", lambda keys, fields: {})
    with pytest.raises(CLIENT.XError, match="no media id"):
        CLIENT.upload_media(KEYS, b"x", "image/png", "tweet_image")


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
    monkeypatch.setattr(CLIENT, "_v11_status", lambda keys, media_id: next(answers))
    monkeypatch.setattr(CLIENT.time, "sleep", sleeps.append)
    CLIENT._wait_processing(
        KEYS, "77", {"processing_info": {"state": "pending", "check_after_secs": 0}}
    )
    assert sleeps == [CLIENT.CHECK_AFTER_MIN_S, CLIENT.CHECK_AFTER_MIN_S]


def test_wait_processing_returns_when_there_is_nothing_to_wait_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(CLIENT, "_v11_status", lambda keys, media_id: {})
    CLIENT._wait_processing(KEYS, "77", {})
    CLIENT._wait_processing(KEYS, "77", {"processing_info": {"state": "succeeded"}})


def test_wait_processing_names_a_failed_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    info = {"state": "failed", "error": {"message": "unsupported codec"}}
    with pytest.raises(CLIENT.XError, match="unsupported codec"):
        CLIENT._wait_processing(KEYS, "77", {"processing_info": info})


def test_wait_processing_gives_up_after_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CLIENT, "PROCESSING_TIMEOUT_S", 0.0)
    with pytest.raises(CLIENT.XError, match="did not finish"):
        CLIENT._wait_processing(KEYS, "77", {"processing_info": {"state": "pending"}})


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
    assert CLIENT.probe_write(KEYS) is expected


def test_probe_write_returns_true_when_the_network_takes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(CLIENT, "_request", lambda *args, **kwargs: {"data": {"id": "1"}})
    assert CLIENT.probe_write(KEYS) is True


def test_probe_write_does_not_guess_about_an_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise CLIENT.XError("POST /2/tweets", None, "unreachable")

    monkeypatch.setattr(CLIENT, "_request", broken)
    with pytest.raises(CLIENT.XError, match="unreachable"):
        CLIENT.probe_write(KEYS)
