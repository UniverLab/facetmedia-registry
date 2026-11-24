"""The x package's thin X API v2 client over OAuth 2.0 with PKCE.

Stdlib only (``urllib``): the browser sign-in (Authorization Code with
PKCE for a confidential client), the code exchange and the refresh at
the token endpoint, the user lookup, post creation, a write probe the
doctor uses and the read-back the ``verify`` verb needs, plus the v2
chunked media upload (initialize/append/finalize/status with a bearer
token) and the alt-text metadata call. Every call below names the
endpoint it hits, sends bearer or Basic auth, and returns the decoded
response, so a failure reads as the HTTP status and the error the
server answered with.

Requires: stdlib
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

#: How long one API call may take; the network answers in milliseconds.
TIMEOUT_S = 30.0
#: How long the sign-in waits for the browser to return to the loopback port.
SIGNIN_TIMEOUT_S = 300.0
#: The v2 posts, users and media endpoints.
API_HOST = "https://api.x.com"
#: Where the browser sign-in starts.
AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
#: The token endpoint for the code exchange and the refresh.
TOKEN_URL = "https://api.x.com/2/oauth2/token"
#: The scopes the send needs: read and write posts, read the account, upload media.
SCOPES = ("tweet.read", "tweet.write", "users.read", "media.write", "offline.access")
#: The loopback address the sign-in listens on unless the caller overrides it.
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8080/callback"
#: Append chunks of at most four megabytes, inside the server maximum of eight.
CHUNK_SIZE = 4 * 1024 * 1024
#: How long a video or GIF may take to process before the upload is refused.
PROCESSING_TIMEOUT_S = 900.0
#: The network's next-check hint, clamped so a stuck upload cannot spin or park.
CHECK_AFTER_MIN_S = 2.0
CHECK_AFTER_MAX_S = 20.0
GIF_MIME = "image/gif"
IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
VIDEO_MIME = {".mp4": "video/mp4", ".mov": "video/quicktime"}


class XError(Exception):
    """One failed X call: the endpoint, the status and the error name."""

    def __init__(self, endpoint: str, status: int | None, error: str) -> None:
        super().__init__(f"{endpoint}: {error} (status {status})")
        self.endpoint = endpoint
        self.status = status
        self.error = error


@dataclass(frozen=True)
class Tokens:
    """A token answer: the access token and a new refresh token when one came."""

    access_token: str
    refresh_token: str | None


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    """The browser address that starts the lab's OAuth 2.0 sign-in with PKCE."""
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def _challenge(verifier: str) -> str:
    """The S256 code challenge of one PKCE verifier, without padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _basic(client_id: str, client_secret: str) -> str:
    """The Basic auth of one confidential client at the token endpoint."""
    pair = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(pair).decode()


def _token_answer(data: Mapping[str, Any]) -> Tokens:
    """The stored tokens of a token answer; a field missing refuses."""
    access = data.get("access_token")
    if not isinstance(access, str) or not access:
        raise XError(TOKEN_URL, None, "the token answer holds no access token")
    refresh = data.get("refresh_token")
    if refresh is not None and (not isinstance(refresh, str) or not refresh):
        raise XError(TOKEN_URL, None, "the token answer holds a broken refresh token")
    return Tokens(access_token=access, refresh_token=refresh)


def _token_call(client_id: str, client_secret: str, fields: dict[str, str]) -> Tokens:
    """One form call to the token endpoint with the client's Basic auth."""
    body = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    request.add_header("Authorization", _basic(client_id, client_secret))
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(TOKEN_URL, exc) from exc
    except urllib.error.URLError as exc:
        raise XError(TOKEN_URL, None, f"unreachable: {exc.reason}") from exc
    if not isinstance(decoded, dict):
        raise XError(TOKEN_URL, None, "the token answer is not a JSON object")
    return _token_answer(decoded)


def exchange_code(
    client_id: str, client_secret: str, code: str, redirect_uri: str, verifier: str
) -> Tokens:
    """Trade the sign-in code for the token pair facet stores."""
    return _token_call(
        client_id,
        client_secret,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
    )


def refresh_tokens(client_id: str, client_secret: str, refresh_token: str) -> Tokens:
    """Trade a refresh token for a fresh access token and its rotation."""
    return _token_call(
        client_id,
        client_secret,
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
    )


def authorize(client_id: str, client_secret: str, redirect_uri: str) -> dict[str, str]:
    """Run the browser sign-in and answer the secrets map facet stores."""
    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    address = authorize_url(client_id, redirect_uri, state, _challenge(verifier))
    print(f"open this address and sign in:\n{address}")
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme != "http" or not parsed.hostname:
        raise XError(AUTHORIZE_URL, None, "the redirect URI must be an http loopback address")
    holder: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            error = query.get("error", [""])[0]
            if error:
                detail = query.get("error_description", [error])[0] or error
                holder["error"] = detail
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"sign-in rejected: {detail}".encode())
                return
            if query.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"wrong state; sign in again from the terminal")
                return
            found = query.get("code", [""])[0]
            if found:
                holder["code"] = found
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"signed in; return to the terminal")

        def log_message(self, *args: object) -> None:
            return

    server = http.server.HTTPServer((parsed.hostname, parsed.port or 80), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + SIGNIN_TIMEOUT_S
    while "code" not in holder and "error" not in holder and time.monotonic() < deadline:
        time.sleep(0.2)
    server.shutdown()
    server.server_close()
    if "error" in holder:
        raise XError(AUTHORIZE_URL, None, f"the sign-in was rejected: {holder['error']}")
    code = holder.get("code")
    if not code:
        raise XError(AUTHORIZE_URL, None, "no sign-in code arrived; try again")
    tokens = exchange_code(client_id, client_secret, code, redirect_uri, verifier)
    if not tokens.refresh_token:
        raise XError(TOKEN_URL, None, "the token answer holds no refresh token")
    return {"access-token": tokens.access_token, "refresh-token": tokens.refresh_token}


def _request(
    url: str,
    *,
    method: str,
    token: str,
    query: Mapping[str, str] | None = None,
    payload: Any | None = None,
    raw: bytes | None = None,
    content_type: str = "application/json",
) -> Any:
    """One bearer request, answered as decoded JSON."""
    target = url
    if query and method == "GET":
        target += "?" + urllib.parse.urlencode({k: str(v) for k, v in query.items()})
    data = (
        raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    )
    request = urllib.request.Request(target, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(f"{method} {url}", exc) from exc
    except urllib.error.URLError as exc:
        raise XError(f"{method} {url}", None, f"unreachable: {exc.reason}") from exc


def _http_error(endpoint: str, exc: urllib.error.HTTPError) -> XError:
    """The server's own error detail when it gives one, else the HTTP reason."""
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except (OSError, ValueError):
        body = {}
    detail = ""
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            detail = str(errors[0].get("message") or errors[0].get("title") or "")
        detail = detail or str(body.get("title") or body.get("detail") or body.get("error") or "")
    return XError(endpoint, exc.code, detail or exc.reason)


def whoami(token: str) -> dict[str, Any]:
    """The authenticated account: its id, name and username."""
    answer = _request(f"{API_HOST}/2/users/me", method="GET", token=token)
    if not isinstance(answer, dict) or not isinstance(answer.get("data"), dict):
        raise XError("GET /2/users/me", None, "not a user")
    user = answer["data"]
    if not user.get("id") or not user.get("username"):
        raise XError("GET /2/users/me", None, "not a user")
    return dict(user)


def create_post(
    token: str,
    text: str,
    *,
    media_ids: list[str] | None = None,
    reply_to: str | None = None,
) -> dict[str, str]:
    """Create one post, optionally carrying media and replying to another."""
    payload: dict[str, Any] = {"text": text}
    if media_ids:
        payload["media"] = {"media_ids": media_ids}
    if reply_to is not None:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to}
    answer = _request(f"{API_HOST}/2/tweets", method="POST", token=token, payload=payload)
    if not isinstance(answer, dict) or not isinstance(answer.get("data"), dict):
        raise XError("POST /2/tweets", None, "no post id")
    data = answer["data"]
    if not data.get("id"):
        raise XError("POST /2/tweets", None, "no post id")
    return {"id": str(data["id"]), "text": str(data.get("text", ""))}


def get_posts(token: str, ids: list[str]) -> list[dict[str, Any]]:
    """Read posts back by id, with text and attachments."""
    answer = _request(
        f"{API_HOST}/2/tweets",
        method="GET",
        token=token,
        query={"ids": ",".join(ids), "tweet.fields": "text,attachments"},
    )
    if not isinstance(answer, dict) or not isinstance(answer.get("data"), list):
        raise XError("GET /2/tweets", None, "no posts in the answer")
    return [post for post in answer["data"] if isinstance(post, dict)]


def probe_write(token: str) -> bool:
    """Whether the token may write, proved by a request that creates nothing.

    A post with no text and no media is invalid for every account, so a
    writable token is answered with a 400 before any post exists; a
    read-only token is refused earlier with a 401 or 403.  Anything else is
    an unexpected failure the doctor reports rather than guesses about.
    """
    try:
        _request(f"{API_HOST}/2/tweets", method="POST", token=token, payload={"text": ""})
    except XError as exc:
        if exc.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            return False
        if exc.status is None:
            raise
        if HTTPStatus.BAD_REQUEST <= exc.status < HTTPStatus.INTERNAL_SERVER_ERROR:
            return True
        raise
    return True


def _media_id(answer: Any, endpoint: str) -> str:
    """The upload id of an initialize or finalize answer, wherever it rides."""
    data = answer.get("data") if isinstance(answer, dict) else None
    if isinstance(data, dict):
        found = data.get("id") or data.get("media_id_string") or data.get("media_id")
        if found:
            return str(found)
    if isinstance(answer, dict):
        found = answer.get("media_id_string") or answer.get("media_id")
        if found:
            return str(found)
    raise XError(endpoint, None, "no media id")


def _media_data(answer: Any) -> dict[str, Any]:
    """The data object of a finalize or status answer, empty when missing."""
    if isinstance(answer, dict) and isinstance(answer.get("data"), dict):
        return dict(answer["data"])
    return answer if isinstance(answer, dict) else {}


def _media_init(token: str, mime: str, category: str, total_bytes: int) -> str:
    """Start the v2 chunked upload and answer its media id."""
    endpoint = "POST /2/media/upload/initialize"
    answer = _request(
        f"{API_HOST}/2/media/upload/initialize",
        method="POST",
        token=token,
        payload={
            "media_category": category,
            "media_type": mime,
            "total_bytes": total_bytes,
        },
    )
    return _media_id(answer, endpoint)


def _media_append(token: str, media_id: str, segment: int, chunk: bytes, mime: str) -> None:
    """One APPEND segment of a chunked upload, as raw multipart bytes."""
    boundary = secrets.token_hex(16)
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="segment_index"\r\n\r\n{segment}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="media"; '
        f'filename="chunk"\r\nContent-Type: {mime}\r\n\r\n'
    ).encode()
    body = head + chunk + f"\r\n--{boundary}--\r\n".encode()
    _request(
        f"{API_HOST}/2/media/upload/{media_id}/append",
        method="POST",
        token=token,
        raw=body,
        content_type=f"multipart/form-data; boundary={boundary}",
    )


def _media_finalize(token: str, media_id: str) -> dict[str, Any]:
    """Complete the chunked upload; the answer may carry processing info."""
    answer = _request(f"{API_HOST}/2/media/upload/{media_id}/finalize", method="POST", token=token)
    return _media_data(answer)


def _media_status(token: str, media_id: str) -> dict[str, Any]:
    """One STATUS read: what the upload's processing says now."""
    answer = _request(
        f"{API_HOST}/2/media/upload",
        method="GET",
        token=token,
        query={"command": "STATUS", "media_id": media_id},
    )
    return _media_data(answer)


def upload_media(token: str, data: bytes, mime: str, category: str) -> str:
    """Upload one file with the v2 chunked initialize/append/finalize flow, then wait."""
    media_id = _media_init(token, mime, category, len(data))
    for segment, start in enumerate(range(0, len(data), CHUNK_SIZE)):
        _media_append(token, media_id, segment, data[start : start + CHUNK_SIZE], mime)
    final = _media_finalize(token, media_id)
    _wait_processing(token, media_id, final)
    return media_id


def _processing_delay(info: Mapping[str, Any]) -> float:
    """The network's next-check hint, clamped so a stuck upload ends."""
    try:
        seconds = float(info.get("check_after_secs", 5))
    except (TypeError, ValueError):
        seconds = 5.0
    return min(max(seconds, CHECK_AFTER_MIN_S), CHECK_AFTER_MAX_S)


def _processing_failure(info: Mapping[str, Any]) -> str:
    """The reason a video or GIF failed processing, or a plain one."""
    error = info.get("error")
    if isinstance(error, Mapping):
        return str(error.get("message") or error.get("code") or "processing failed")
    return "processing failed"


def _wait_processing(token: str, media_id: str, answer: Mapping[str, Any]) -> None:
    """Poll STATUS until a video or GIF is ready, and refuse one that cannot be.

    A FINALIZE with no ``processing_info`` is already ready: an image takes
    that path, and treating the missing block as pending would hang it.
    """
    info = answer.get("processing_info")
    deadline = time.monotonic() + PROCESSING_TIMEOUT_S
    while isinstance(info, Mapping):
        state = str(info.get("state", ""))
        if state == "succeeded":
            return
        if state == "failed":
            raise XError("POST /2/media/upload/{id}/finalize", None, _processing_failure(info))
        if time.monotonic() >= deadline:
            raise XError(
                "POST /2/media/upload/{id}/finalize", None, "processing did not finish in time"
            )
        time.sleep(_processing_delay(info))
        info = _media_status(token, media_id).get("processing_info")


def set_alt_text(token: str, media_id: str, alt: str) -> None:
    """Attach alt text to one uploaded image."""
    _request(
        f"{API_HOST}/2/media/metadata",
        method="POST",
        token=token,
        payload={"media_id": media_id, "alt_text": {"text": alt}},
    )
