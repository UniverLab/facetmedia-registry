"""The linkedin package's thin Posts API client over ``urllib``.

Stdlib only: OAuth sign-in, code exchange and refresh, the member read
(userinfo), the organization role read (organizationAcls), the image
asset upload in two steps (initializeUpload plus the bytes PUT), the
organization post creation (text-only, single-image or MultiImage), and
the post read-back. Every call below names the endpoint it hits and
returns plain data, so a failure reads as the endpoint, the HTTP status
and LinkedIn's own reason.

Requires: stdlib
"""

from __future__ import annotations

import html
import http.server
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
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
#: The host every marketing API call below goes to.
API_HOST = "https://api.linkedin.com"
#: The version header every rest call carries, in YYYYMM format.
LINKEDIN_VERSION = "202611"
#: The Restli protocol every rest call carries.
RESTLI_PROTOCOL = "2.0.0"
#: The organization post creation and read-back endpoint (it replaces legacy ugcPosts).
POSTS = "/rest/posts"
#: The image asset init endpoint; the upload URL rides the answer.
IMAGES_INIT = "/rest/images?action=initializeUpload"
#: The member's organization roles: proves the Company Page role behind the token.
ORGANIZATION_ACLS = "/rest/organizationAcls?q=roleAssignee"
#: The organization's record: its display name rides the receipt's account.
ORGANIZATIONS = "/rest/organizations"
#: The OpenID member read that names who signed in.
USERINFO = "/v2/userinfo"
#: Where the browser sign-in starts.
AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
#: The token endpoint for the code exchange and the refresh.
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
#: The scopes the organization flow needs: write plus the read-back.
SCOPES = ("w_organization_social", "r_organization_social")
#: The Company Page roles that may post for the organization.
ORG_ROLES = ("ADMINISTRATOR", "DIRECT_SPONSORED_CONTENT_POSTER", "CONTENT_ADMIN")
#: The fragment LinkedIn answers when the token expired.
TOKEN_EXPIRED = "expired"
#: The fragment LinkedIn answers when the grant misses a scope or role.
ACCESS_DENIED = "Not enough permissions"


class LinkedInError(Exception):
    """One failed LinkedIn call: the endpoint, the status and LinkedIn's reason."""

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
    scopes: tuple[str, ...]


def _scopes(value: object) -> tuple[str, ...]:
    """The scope string of a token answer as granted scope names."""
    if not isinstance(value, str) or not value:
        return ()
    return tuple(part.strip() for part in value.replace(",", " ").split() if part.strip())


def _tokens(data: dict[str, Any]) -> Tokens:
    """The stored secrets of a token answer; a field missing refuses."""
    access = data.get("access_token")
    refresh = data.get("refresh_token")
    if not isinstance(access, str) or not access:
        raise LinkedInError(TOKEN_URL, None, "the token answer holds no access token")
    if not isinstance(refresh, str) or not refresh:
        raise LinkedInError(TOKEN_URL, None, "the token answer holds no refresh token")
    return Tokens(access_token=access, refresh_token=refresh, scopes=_scopes(data.get("scope")))


def _exchange(
    method: str,
    path_or_url: str,
    body: dict[str, Any] | bytes | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """One HTTP exchange; the answer rides as status, headers and raw bytes."""
    url = path_or_url if path_or_url.startswith("http") else API_HOST + path_or_url
    if isinstance(body, bytes):
        payload: bytes | None = body
        content_type = "application/octet-stream"
    else:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        content_type = "application/json"
    request = urllib.request.Request(url, data=payload, method=method)
    request.add_header("Content-Type", content_type)
    request.add_header("Linkedin-Version", LINKEDIN_VERSION)
    request.add_header("X-Restli-Protocol-Version", RESTLI_PROTOCOL)
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
            return response.status, headers, response.read()
    except urllib.error.HTTPError as exc:
        raise _http_error(path_or_url, exc) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LinkedInError(path_or_url, None, f"the call failed: {exc}") from exc


def _http_error(path_or_url: str, exc: urllib.error.HTTPError) -> LinkedInError:
    """LinkedIn's HTTP failure as its endpoint, status and own reason."""
    try:
        decoded = json.loads(exc.read().decode("utf-8"))
    except (OSError, ValueError):
        return LinkedInError(path_or_url, exc.code, "refused")
    if not isinstance(decoded, dict):
        return LinkedInError(path_or_url, exc.code, "refused")
    message = decoded.get("message") or decoded.get("serviceErrorCode") or "refused"
    return LinkedInError(path_or_url, exc.code, str(message))


def _call(
    method: str,
    path_or_url: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any:
    """One JSON call; LinkedIn's refusal becomes a LinkedInError."""
    status, _headers, raw = _exchange(method, path_or_url, body, token)
    if status == HTTPStatus.NO_CONTENT or not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise LinkedInError(path_or_url, status, f"the answer is not JSON: {exc}") from exc


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    """The browser address that starts the lab's OAuth sign-in."""
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(SCOPES),
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> Tokens:
    """Trade the sign-in code for the token pair facet stores."""
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    payload = urllib.parse.urlencode(body).encode("utf-8")
    request = urllib.request.Request(TOKEN_URL, data=payload, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(TOKEN_URL, exc) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LinkedInError(TOKEN_URL, None, f"the call failed: {exc}") from exc
    if not isinstance(decoded, dict):
        raise LinkedInError(TOKEN_URL, None, "the answer is not a JSON object")
    if "error" in decoded:
        detail = decoded.get("error_description") or decoded.get("error")
        raise LinkedInError(TOKEN_URL, None, str(detail))
    return _tokens(decoded)


def refresh_tokens(client_id: str, client_secret: str, refresh_token: str) -> Tokens:
    """Trade an expired pair's refresh token for a fresh pair."""
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    payload = urllib.parse.urlencode(body).encode("utf-8")
    request = urllib.request.Request(TOKEN_URL, data=payload, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(TOKEN_URL, exc) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LinkedInError(TOKEN_URL, None, f"the call failed: {exc}") from exc
    if not isinstance(decoded, dict):
        raise LinkedInError(TOKEN_URL, None, "the answer is not a JSON object")
    if "error" in decoded:
        detail = decoded.get("error_description") or decoded.get("error")
        raise LinkedInError(TOKEN_URL, None, str(detail))
    return _tokens(decoded)


def userinfo(access_token: str) -> dict[str, Any]:
    """The token's member: the subject who signed in, plus the profile link."""
    data = _call("GET", USERINFO, token=access_token)
    if not isinstance(data, dict):
        raise LinkedInError(USERINFO, None, "the answer is not a JSON object")
    return data


def organization_acls(access_token: str) -> list[dict[str, Any]]:
    """The member's organization roles: every company the token may act for."""
    data = _call("GET", ORGANIZATION_ACLS, token=access_token)
    if not isinstance(data, dict):
        raise LinkedInError(ORGANIZATION_ACLS, None, "the answer is not a JSON object")
    elements = data.get("elements", [])
    if not isinstance(elements, list):
        raise LinkedInError(ORGANIZATION_ACLS, None, "the answer holds no role list")
    return [entry for entry in elements if isinstance(entry, dict)]


def organization(access_token: str, org_id: str) -> dict[str, Any]:
    """The organization's record: its display name for the receipt's account."""
    data = _call("GET", f"{ORGANIZATIONS}/{org_id}", token=access_token)
    if not isinstance(data, dict):
        raise LinkedInError(ORGANIZATIONS, None, "the answer is not a JSON object")
    return data


def init_image_upload(access_token: str, owner: str) -> tuple[str, str]:
    """Start the image asset upload; answer the upload URL and the image URN."""
    data = _call(
        "POST",
        IMAGES_INIT,
        {"initializeUploadRequest": {"owner": owner}},
        token=access_token,
    )
    if not isinstance(data, dict):
        raise LinkedInError(IMAGES_INIT, None, "the answer is not a JSON object")
    value = data.get("value")
    if not isinstance(value, dict):
        raise LinkedInError(IMAGES_INIT, None, "the init answer holds no upload")
    upload_url = value.get("uploadUrl")
    image_urn = value.get("image")
    if not isinstance(upload_url, str) or not upload_url:
        raise LinkedInError(IMAGES_INIT, None, "the init answer holds no upload URL")
    if not isinstance(image_urn, str) or not image_urn:
        raise LinkedInError(IMAGES_INIT, None, "the init answer holds no image URN")
    return upload_url, image_urn


def upload_image(upload_url: str, mime: str, data: bytes) -> None:
    """PUT the image bytes; anything but success raises LinkedIn's reason."""
    request = urllib.request.Request(upload_url, data=data, method="PUT")
    request.add_header("Content-Type", mime)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        raise _http_error(upload_url, exc) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise LinkedInError(upload_url, None, f"the image upload failed: {exc}") from exc
    if status not in (HTTPStatus.OK, HTTPStatus.CREATED):
        raise LinkedInError(upload_url, status, "the image upload was refused")


def create_post(access_token: str, body: dict[str, Any]) -> str:
    """Create the organization post; answer the Post ID of the x-restli-id header."""
    status, headers, _raw = _exchange("POST", POSTS, body, token=access_token)
    if status != HTTPStatus.CREATED:
        raise LinkedInError(POSTS, status, "the post was refused")
    post_id = headers.get("x-restli-id")
    if not post_id:
        raise LinkedInError(POSTS, status, "the answer holds no Post ID")
    return post_id


def get_post(access_token: str, post_id: str) -> dict[str, Any]:
    """Read the post back; the read proves it exists with its text and media."""
    encoded = urllib.parse.quote(post_id, safe="")
    data = _call("GET", f"{POSTS}/{encoded}", token=access_token)
    if not isinstance(data, dict):
        raise LinkedInError(POSTS, None, "the answer is not a JSON object")
    return data


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
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    announce: Callable[[str], None] = _print_address,
) -> dict[str, str]:
    """Run the browser sign-in and answer the secrets map facet stores."""
    state = secrets.token_urlsafe(16)
    address = authorize_url(client_id, redirect_uri, state)
    announce(address)
    parsed = urllib.parse.urlparse(redirect_uri)
    if not parsed.hostname or (parsed.scheme == "http" and parsed.hostname != "localhost"):
        raise LinkedInError(
            AUTHORIZE_URL, None, "the redirect URI must be a localhost or https address"
        )
    code_holder: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                _send_html(self, 400, _render_oauth_page(False, "LinkedIn", "OAuth state mismatch"))
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
                _send_html(self, 400, _render_oauth_page(False, "LinkedIn", detail))
                return
            code_holder["code"] = found
            _send_html(self, 200, _render_oauth_page(True, "LinkedIn"))

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
        raise LinkedInError(AUTHORIZE_URL, None, code_holder["error"])
    code = code_holder.get("code")
    if not code:
        raise LinkedInError(AUTHORIZE_URL, None, "no sign-in code arrived; try again")
    tokens = exchange_code(client_id, client_secret, code, redirect_uri)
    return {"access-token": tokens.access_token, "refresh-token": tokens.refresh_token}
