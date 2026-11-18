"""The x package's thin X API v2 client over OAuth 1.0a.

Stdlib only (``urllib``, ``hmac``, ``hashlib``): user lookup, media upload
(INIT/APPEND/FINALIZE/STATUS plus metadata for alt text), post creation,
a write probe the doctor uses and the read-back the ``verify`` verb needs.
Every call below names the endpoint it hits, signs with OAuth 1.0a user
context, sends JSON or multipart bytes, and returns the decoded response,
so a failure reads as the HTTP status and the error the server answered
with.

Requires: stdlib
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

#: How long one API call may take; the network answers in milliseconds.
TIMEOUT_S = 30.0
#: The v2 posts and users endpoints.
API_HOST = "https://api.x.com"
#: The v1.1 media upload endpoint (chunked upload and metadata).
UPLOAD_HOST = "https://upload.x.com"
#: Append chunks of at most four megabytes.
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
class Keys:
    """One OAuth 1.0a user context: the app's pair and the account's pair."""

    consumer_key: str
    consumer_secret: str
    token: str
    token_secret: str


def _percent(value: str) -> str:
    """OAuth percent encoding: the unreserved set alone rides through."""
    return urllib.parse.quote(value, safe="~-._")


def _sign(method: str, url: str, params: Mapping[str, str], keys: Keys) -> str:
    """The OAuth 1.0a HMAC-SHA1 signature of one request."""
    ordered = "&".join(f"{_percent(key)}={_percent(params[key])}" for key in sorted(params))
    base = "&".join([method.upper(), _percent(url), _percent(ordered)])
    secret = f"{_percent(keys.consumer_secret)}&{_percent(keys.token_secret)}"
    digest = hmac.new(secret.encode(), base.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def _auth_header(
    method: str,
    url: str,
    query: Mapping[str, str],
    body: Mapping[str, str],
    keys: Keys,
) -> str:
    """The Authorization header of one OAuth 1.0a user-context request."""
    oauth = {
        "oauth_consumer_key": keys.consumer_key,
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": keys.token,
        "oauth_version": "1.0",
    }
    params = {
        **{k: str(v) for k, v in query.items()},
        **{k: str(v) for k, v in body.items()},
        **oauth,
    }
    oauth["oauth_signature"] = _sign(method, url, params, keys)
    pairs = " ".join(f'{_percent(k)}="{_percent(v)}"' for k, v in sorted(oauth.items()))
    return "OAuth " + pairs


def _request(
    url: str,
    *,
    method: str,
    keys: Keys,
    query: Mapping[str, str] | None = None,
    payload: Any | None = None,
    raw: bytes | None = None,
    content_type: str = "application/json",
) -> Any:
    """One signed request, answered as decoded JSON."""
    params = dict(query or {}) if method == "GET" else {}
    target = url
    if params:
        target += "?" + urllib.parse.urlencode(params)
    data = (
        raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    )
    header = _auth_header(method, url, params, {}, keys)
    request = urllib.request.Request(target, data=data, method=method)
    request.add_header("Authorization", header)
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
        detail = detail or str(body.get("title") or body.get("detail") or "")
    return XError(endpoint, exc.code, detail or exc.reason)


def whoami(keys: Keys) -> dict[str, Any]:
    """The authenticated account: its id, name and username."""
    answer = _request(f"{API_HOST}/2/users/me", method="GET", keys=keys)
    if not isinstance(answer, dict) or not isinstance(answer.get("data"), dict):
        raise XError("GET /2/users/me", None, "not a user")
    user = answer["data"]
    if not user.get("id") or not user.get("username"):
        raise XError("GET /2/users/me", None, "not a user")
    return dict(user)


def create_post(
    keys: Keys,
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
    answer = _request(f"{API_HOST}/2/tweets", method="POST", keys=keys, payload=payload)
    if not isinstance(answer, dict) or not isinstance(answer.get("data"), dict):
        raise XError("POST /2/tweets", None, "no post id")
    data = answer["data"]
    if not data.get("id"):
        raise XError("POST /2/tweets", None, "no post id")
    return {"id": str(data["id"]), "text": str(data.get("text", ""))}


def get_posts(keys: Keys, ids: list[str]) -> list[dict[str, Any]]:
    """Read posts back by id, with text and attachments."""
    answer = _request(
        f"{API_HOST}/2/tweets",
        method="GET",
        keys=keys,
        query={"ids": ",".join(ids), "tweet.fields": "text,attachments"},
    )
    if not isinstance(answer, dict) or not isinstance(answer.get("data"), list):
        raise XError("GET /2/tweets", None, "no posts in the answer")
    return [post for post in answer["data"] if isinstance(post, dict)]


def probe_write(keys: Keys) -> bool:
    """Whether the token may write, proved by a request that creates nothing.

    A post with no text and no media is invalid for every account, so a
    writable token is answered with a 400 before any post exists; a
    read-only token is refused earlier with a 401 or 403.  Anything else is
    an unexpected failure the doctor reports rather than guesses about.
    """
    try:
        _request(f"{API_HOST}/2/tweets", method="POST", keys=keys, payload={"text": ""})
    except XError as exc:
        if exc.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            return False
        if exc.status is None:
            raise
        if HTTPStatus.BAD_REQUEST <= exc.status < HTTPStatus.INTERNAL_SERVER_ERROR:
            return True
        raise
    return True


def _v11(keys: Keys, fields: Mapping[str, str]) -> dict[str, Any]:
    """One v1.1 media-upload call with form-encoded fields."""
    path = "/1.1/media/upload.json"
    body = urllib.parse.urlencode({k: str(v) for k, v in fields.items()}).encode()
    header = _auth_header(
        "POST", f"{UPLOAD_HOST}{path}", {}, {k: str(v) for k, v in fields.items()}, keys
    )
    request = urllib.request.Request(f"{UPLOAD_HOST}{path}", data=body, method="POST")
    request.add_header("Authorization", header)
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error("POST /1.1/media/upload.json", exc) from exc
    except urllib.error.URLError as exc:
        raise XError("POST /1.1/media/upload.json", None, f"unreachable: {exc.reason}") from exc


def _append_chunk(keys: Keys, media_id: str, segment: int, chunk: bytes) -> None:
    """One APPEND segment of a chunked upload, as raw multipart bytes."""
    boundary = uuid.uuid4().hex
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="command"\r\n\r\nAPPEND\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="media_id"\r\n\r\n{media_id}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="segment_index"\r\n\r\n{segment}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="media"; '
        f'filename="chunk"\r\nContent-Type: application/octet-stream\r\n\r\n'
    ).encode()
    body = head + chunk + f"\r\n--{boundary}--\r\n".encode()
    path = "/1.1/media/upload.json"
    # A multipart body is not part of the OAuth 1.0a signature base.
    header = _auth_header("POST", f"{UPLOAD_HOST}{path}", {}, {}, keys)
    request = urllib.request.Request(f"{UPLOAD_HOST}{path}", data=body, method="POST")
    request.add_header("Authorization", header)
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        raise _http_error("POST /1.1/media/upload.json", exc) from exc
    except urllib.error.URLError as exc:
        raise XError("POST /1.1/media/upload.json", None, f"unreachable: {exc.reason}") from exc


def upload_media(keys: Keys, data: bytes, mime: str, category: str) -> str:
    """Upload one file with the chunked INIT/APPEND/FINALIZE flow, then wait."""
    init = _v11(
        keys,
        {
            "command": "INIT",
            "total_bytes": str(len(data)),
            "media_type": mime,
            "media_category": category,
        },
    )
    media_id = str(init.get("media_id_string") or init.get("media_id") or "")
    if not media_id:
        raise XError("POST /1.1/media/upload.json", None, "no media id")
    for segment, start in enumerate(range(0, len(data), CHUNK_SIZE)):
        _append_chunk(keys, media_id, segment, data[start : start + CHUNK_SIZE])
    final = _v11(keys, {"command": "FINALIZE", "media_id": media_id})
    _wait_processing(keys, media_id, final)
    return media_id


def _v11_status(keys: Keys, media_id: str) -> dict[str, Any]:
    """One STATUS call: what the upload's processing says now."""
    answer = _request(
        f"{UPLOAD_HOST}/1.1/media/upload.json",
        method="GET",
        keys=keys,
        query={"command": "STATUS", "media_id": media_id},
    )
    return answer if isinstance(answer, dict) else {}


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


def _wait_processing(keys: Keys, media_id: str, answer: Mapping[str, Any]) -> None:
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
            raise XError("POST /1.1/media/upload.json", None, _processing_failure(info))
        if time.monotonic() >= deadline:
            raise XError("POST /1.1/media/upload.json", None, "processing did not finish in time")
        time.sleep(_processing_delay(info))
        info = _v11_status(keys, media_id).get("processing_info")


def set_alt_text(keys: Keys, media_id: str, alt: str) -> None:
    """Attach alt text to one uploaded image."""
    path = "/1.1/media/metadata/create.json"
    payload = {"media_id": media_id, "alt_text": {"text": alt}}
    _request(f"{UPLOAD_HOST}{path}", method="POST", keys=keys, payload=payload)
