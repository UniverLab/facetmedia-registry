"""The tiktok package's thin Content Posting API client over ``urllib``.

Stdlib only: OAuth sign-in, token exchange and refresh through Login Kit,
the account read (user info plus creator info), the inbox video upload in
chunks, the inbox photo upload by URL, and the publish-status read-back.
Every call below names the endpoint it hits, sends JSON or bytes, and
returns the decoded ``data`` object, so a failure reads as the endpoint,
the HTTP status and TikTok's own reason.

Requires: stdlib
"""

from __future__ import annotations

import hashlib
import html
import http.server
import json
import secrets
import string
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

try:
    from facet_lib.oauth_page import render as _render_oauth_page
except ImportError:  # pragma: no cover - standalone test fallback
    try:
        from lib.oauth_page import render as _render_oauth_page
    except ImportError:

        def _render_oauth_page(ok: bool, provider: str, detail: str = "") -> bytes:
            msg = f"{provider} signed in; return to the terminal" if ok else f"{provider}: {detail}"
            return f"<!doctype html><html><body><p>{html.escape(msg)}</p></body></html>".encode()


#: How long one API call may take; the endpoints answer in milliseconds.
TIMEOUT_S = 30.0
#: The host every JSON call below goes to.
API_HOST = "https://open.tiktokapis.com"
#: Where the browser sign-in starts.
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
#: The scopes the draft flow needs: identity plus the inbox upload.
SCOPES = ("user.info.basic", "video.upload")
#: The inbox video init and status endpoints (the draft flow, no audit).
INBOX_VIDEO_INIT = "/v2/post/publish/inbox/video/init/"
#: The photo init endpoint; ``post_mode`` MEDIA_UPLOAD is the inbox draft.
PHOTO_INIT = "/v2/post/publish/content/init/"
#: The publish-status read-back both flows share.
STATUS_FETCH = "/v2/post/publish/status/fetch/"
#: The creator read that names the account's handle.
CREATOR_INFO = "/v2/post/publish/creator_info/query/"
#: The user read that names the account's display name and open id.
USER_INFO = "/v2/user/info/"
#: The token endpoint for the code exchange and the refresh.
TOKEN_URL = "/v2/oauth/token/"
#: The status that means TikTok moved the draft to the account's inbox.
INBOX_STATUS = "SEND_TO_USER_INBOX"
#: The status that means TikTok refused the upload.
FAILED_STATUS = "FAILED"
#: The error code TikTok answers when the access token expired.
TOKEN_INVALID = "access_token_invalid"
#: The error code TikTok answers when the grant misses a scope.
SCOPE_MISSING = "scope_not_authorized"
#: Unreserved PKCE verifier alphabet (RFC 7636).
PKCE_ALPHABET = string.ascii_letters + string.digits + "-._~"
#: Default PKCE verifier length (>= 64, <= 128).
PKCE_VERIFIER_LEN = 64


class TikTokError(Exception):
    """One failed TikTok call: the endpoint, the status and TikTok's reason."""

    def __init__(self, endpoint: str, status: int | None, error: str) -> None:
        super().__init__(f"{endpoint}: {error} (status {status})")
        self.endpoint = endpoint
        self.status = status
        self.error = error


@dataclass(frozen=True)
class Tokens:
    """A fresh token pair: what facet stores through its secrets store."""

    access_token: str
    refresh_token: str
    open_id: str
    scopes: tuple[str, ...]


def _scopes(value: object) -> tuple[str, ...]:
    """The scope string of a token answer as granted scope names."""
    if not isinstance(value, str) or not value:
        return ()
    return tuple(part.strip() for part in value.replace(",", " ").split() if part.strip())


def _tokens(data: Mapping[str, Any]) -> Tokens:
    """The stored secrets of a token answer; a field missing refuses."""
    access = data.get("access_token")
    refresh = data.get("refresh_token")
    open_id = data.get("open_id")
    if not isinstance(access, str) or not access:
        raise TikTokError(TOKEN_URL, None, "the token answer holds no access token")
    if not isinstance(refresh, str) or not refresh:
        raise TikTokError(TOKEN_URL, None, "the token answer holds no refresh token")
    if not isinstance(open_id, str) or not open_id:
        raise TikTokError(TOKEN_URL, None, "the token answer holds no open id")
    return Tokens(
        access_token=access,
        refresh_token=refresh,
        open_id=open_id,
        scopes=_scopes(data.get("scope")),
    )


def _call(
    method: str,
    path_or_url: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """One JSON call; TikTok's error envelope becomes a TikTokError."""
    url = path_or_url if path_or_url.startswith("http") else API_HOST + path_or_url
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method=method)
    request.add_header("Content-Type", "application/json; charset=UTF-8")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(path_or_url, exc) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise TikTokError(path_or_url, None, f"the call failed: {exc}") from exc
    if not isinstance(decoded, dict):
        raise TikTokError(path_or_url, None, "the answer is not a JSON object")
    error = decoded.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if code != "ok":
        message = error.get("message") if isinstance(error, dict) else None
        raise TikTokError(path_or_url, None, f"{code}: {message or 'refused'}")
    data = decoded.get("data", {})
    if not isinstance(data, dict):
        raise TikTokError(path_or_url, None, "the answer holds no data object")
    return data


def _http_error(path_or_url: str, exc: urllib.error.HTTPError) -> TikTokError:
    """TikTok's HTTP failure as its endpoint, status and own reason."""
    try:
        decoded = json.loads(exc.read().decode("utf-8"))
    except (OSError, ValueError):
        return TikTokError(path_or_url, exc.code, "refused")
    error = decoded.get("error") if isinstance(decoded, dict) else None
    if not isinstance(error, dict):
        return TikTokError(path_or_url, exc.code, "refused")
    code = error.get("code") or "refused"
    message = error.get("message") or ""
    detail = f"{code}: {message}" if message else str(code)
    return TikTokError(path_or_url, exc.code, detail)


def make_verifier() -> str:
    """Create a random PKCE code verifier from the unreserved character set."""
    return "".join(secrets.choice(PKCE_ALPHABET) for _ in range(PKCE_VERIFIER_LEN))


def challenge_of(verifier: str) -> str:
    """Return TikTok's lowercase hexadecimal SHA-256 PKCE code challenge."""
    return hashlib.sha256(verifier.encode("ascii")).hexdigest()


def authorize_url(client_key: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    """The browser address that starts the lab's OAuth sign-in."""
    query = urllib.parse.urlencode(
        {
            "client_key": client_key,
            "response_type": "code",
            "scope": ",".join(SCOPES),
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(
    client_key: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> Tokens:
    """Trade the sign-in code for the token pair facet stores."""
    return _tokens(
        _call(
            "POST",
            TOKEN_URL,
            {
                "client_key": client_key,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
        )
    )


def refresh_tokens(client_key: str, client_secret: str, refresh_token: str) -> Tokens:
    """Trade an expired pair's refresh token for a fresh pair."""
    return _tokens(
        _call(
            "POST",
            TOKEN_URL,
            {
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
    )


def user_info(access_token: str) -> dict[str, Any]:
    """The token's account: display name, open id and profile link."""
    fields = "open_id,union_id,avatar_url,display_name,profile_deep_link"
    return _call("GET", f"{USER_INFO}?fields={fields}", token=access_token).get("user", {})


def creator_info(access_token: str) -> dict[str, Any]:
    """The token's creator: handle, nickname and privacy options."""
    return _call("POST", CREATOR_INFO, {}, token=access_token)


def init_video_upload(
    access_token: str, size: int, chunk_size: int, chunk_count: int
) -> tuple[str, str]:
    """Start the inbox video upload; answer the publish id and upload URL."""
    data = _call(
        "POST",
        INBOX_VIDEO_INIT,
        {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": chunk_count,
            }
        },
        token=access_token,
    )
    publish_id = data.get("publish_id")
    upload_url = data.get("upload_url")
    if not isinstance(publish_id, str) or not publish_id:
        raise TikTokError(INBOX_VIDEO_INIT, None, "the init answer holds no publish id")
    if not isinstance(upload_url, str) or not upload_url:
        raise TikTokError(INBOX_VIDEO_INIT, None, "the init answer holds no upload URL")
    return publish_id, upload_url


def upload_chunk(
    upload_url: str, mime: str, data: bytes, first: int, last: int, total: int
) -> bool:
    """PUT one chunk; answer True when TikTok holds the whole video."""
    request = urllib.request.Request(upload_url, data=data, method="PUT")
    request.add_header("Content-Type", mime)
    request.add_header("Content-Length", str(len(data)))
    request.add_header("Content-Range", f"bytes {first}-{last}/{total}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        raise _http_error(upload_url, exc) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise TikTokError(upload_url, None, f"the chunk upload failed: {exc}") from exc
    if status == HTTPStatus.CREATED:
        return True
    if status == HTTPStatus.PARTIAL_CONTENT:
        return False
    raise TikTokError(upload_url, status, "the chunk upload was refused")


def init_photo_upload(access_token: str, photo_urls: list[str]) -> str:
    """Start the inbox photo upload by URL; answer the publish id."""
    data = _call(
        "POST",
        PHOTO_INIT,
        {
            "post_info": {},
            "source_info": {
                "source": "PULL_FROM_URL",
                "photo_cover_index": 0,
                "photo_images": photo_urls,
            },
            "post_mode": "MEDIA_UPLOAD",
            "media_type": "PHOTO",
        },
        token=access_token,
    )
    publish_id = data.get("publish_id")
    if not isinstance(publish_id, str) or not publish_id:
        raise TikTokError(PHOTO_INIT, None, "the init answer holds no publish id")
    return publish_id


def publish_status(access_token: str, publish_id: str) -> tuple[str, str]:
    """The publish status and TikTok's failure reason, empty when none."""
    data = _call("POST", STATUS_FETCH, {"publish_id": publish_id}, token=access_token)
    status = data.get("status")
    if not isinstance(status, str) or not status:
        raise TikTokError(STATUS_FETCH, None, "the status answer holds no status")
    reason = data.get("fail_reason")
    return status, reason if isinstance(reason, str) else ""


def _print_address(address: str) -> None:
    """Show the sign-in address on the terminal, whole and copyable."""
    print(f"open this address and sign in:\n{address}")


def _send_html(handler: http.server.BaseHTTPRequestHandler, status: int, body: bytes) -> None:
    """Send an HTML response with Content-Type and Content-Length."""
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def authorize(
    client_key: str,
    client_secret: str,
    redirect_uri: str,
    announce: Callable[[str], None] = _print_address,
) -> dict[str, str]:
    """Run the browser sign-in and answer the secrets map facet stores."""
    state = secrets.token_urlsafe(16)
    verifier = make_verifier()
    challenge = challenge_of(verifier)
    print(f"register this redirect URI in your TikTok app:\n{redirect_uri}")
    url = authorize_url(client_key, redirect_uri, state, challenge)
    announce(url)
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme != "http" or not parsed.hostname:
        raise TikTokError(AUTHORIZE_URL, None, "the redirect URI must be an http loopback address")
    expected_path = parsed.path.removesuffix("/")
    code_holder: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            req_url = urllib.parse.urlparse(self.path)
            if req_url.path.removesuffix("/") != expected_path:
                self.send_response(404)
                self.end_headers()
                return
            query = urllib.parse.parse_qs(req_url.query)
            if query.get("state", [""])[0] != state:
                _send_html(self, 400, _render_oauth_page(False, "TikTok", "OAuth state mismatch"))
                return
            error = query.get("error", [""])[0]
            found = query.get("code", [""])[0]
            if error or not found:
                detail = (
                    query.get("error_description", [""])[0]
                    or error
                    or "no authorization code returned"
                )
                code_holder["error"] = detail
                _send_html(self, 400, _render_oauth_page(False, "TikTok", detail))
                return
            code_holder["code"] = found
            _send_html(self, 200, _render_oauth_page(True, "TikTok"))

        def log_message(self, *args: object) -> None:
            return

    server = http.server.HTTPServer((parsed.hostname, parsed.port or 80), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    deadline = time.monotonic() + 300.0
    while "code" not in code_holder and "error" not in code_holder and time.monotonic() < deadline:
        time.sleep(0.2)
    server.server_close()
    if code_holder.get("error"):
        raise TikTokError(AUTHORIZE_URL, None, code_holder["error"])
    code = code_holder.get("code")
    if not code:
        raise TikTokError(AUTHORIZE_URL, None, "no sign-in code arrived; try again")
    tokens = exchange_code(client_key, client_secret, code, redirect_uri, verifier)
    return {
        "access-token": tokens.access_token,
        "refresh-token": tokens.refresh_token,
        "open-id": tokens.open_id,
    }
