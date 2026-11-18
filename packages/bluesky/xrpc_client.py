"""The bluesky package's thin AT Protocol client over XRPC.

Stdlib only (``urllib``, ``json``): session creation, blob upload,
post-record creation and the read-back the ``verify`` verb needs. No SDK:
every call below names the endpoint it hits, sends JSON or raw bytes, and
returns the decoded response, so a failure reads as the HTTP status and the
lexicon the server answered with.

Requires: stdlib
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

#: How long one XRPC call may take; the network answers in milliseconds.
TIMEOUT_S = 30.0
#: The directory service every session starts at; the session names the PDS.
BGS_HOST = "https://bsky.social"
#: The public AppView for reads that need no account, like a display name.
APPVIEW_HOST = "https://api.bsky.app"
#: The PLC directory that maps a DID to the PDS holding its records.
PLC_HOST = "https://plc.directory"
#: The post-record collection.
POST_COLLECTION = "app.bsky.feed.post"


class XrpcError(Exception):
    """One failed XRPC call: the endpoint, the status and the error name."""

    def __init__(self, endpoint: str, status: int | None, error: str) -> None:
        super().__init__(f"{endpoint}: {error} (status {status})")
        self.endpoint = endpoint
        self.status = status
        self.error = error


def _call(
    host: str,
    endpoint: str,
    *,
    token: str | None = None,
    data: bytes | None = None,
    content_type: str = "application/json",
    params: dict[str, str] | None = None,
) -> Any:
    """POST (``data`` given) or GET one XRPC endpoint, decoded as JSON."""
    url = f"{host}/xrpc/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", content_type)
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(endpoint, exc) from exc
    except urllib.error.URLError as exc:
        raise XrpcError(endpoint, None, f"unreachable: {exc.reason}") from exc


def _http_error(endpoint: str, exc: urllib.error.HTTPError) -> XrpcError:
    """The server's own error name when it gives one, else the HTTP reason."""
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except (OSError, ValueError):
        body = {}
    error = str(body.get("error") or body.get("message") or exc.reason)
    return XrpcError(endpoint, exc.code, error)


def create_session(handle: str, app_password: str) -> dict[str, Any]:
    """Sign in as ``handle``; answers the DID, the tokens and the account."""
    payload = json.dumps({"identifier": handle, "password": app_password}).encode()
    session = _call(BGS_HOST, "com.atproto.server.createSession", data=payload)
    if not isinstance(session, dict):
        raise XrpcError("com.atproto.server.createSession", None, "not a session")
    return session


def pds_for(did: str) -> str:
    """The PDS endpoint holding ``did``'s records, from its DID document."""
    if not did:
        raise XrpcError("plc.directory", None, "no did to find a PDS for")
    url = f"{PLC_HOST}/{urllib.parse.quote(did, safe='')}"
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            document = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error("plc.directory", exc) from exc
    except urllib.error.URLError as exc:
        raise XrpcError("plc.directory", None, f"unreachable: {exc.reason}") from exc
    if isinstance(document, dict):
        for service in document.get("service", []):
            if isinstance(service, dict) and service.get("id") == "#atproto_pds":
                endpoint = str(service.get("serviceEndpoint", "")).rstrip("/")
                if endpoint:
                    return endpoint
    raise XrpcError("plc.directory", None, f"no PDS for {did}")


def get_record(host: str, did: str, collection: str, rkey: str) -> dict[str, Any]:
    """One record straight from the PDS: what the network holds right now."""
    record = _call(
        host,
        "com.atproto.repo.getRecord",
        params={"repo": did, "collection": collection, "rkey": rkey},
    )
    if not isinstance(record, dict) or not isinstance(record.get("value"), dict):
        raise XrpcError("com.atproto.repo.getRecord", None, f"no record at {rkey}")
    return record


def resolve_handle(handle: str) -> str:
    """The DID the directory service holds for ``handle``."""
    answer = _call(BGS_HOST, "com.atproto.identity.resolveHandle", params={"handle": handle})
    if not isinstance(answer, dict) or not answer.get("did"):
        raise XrpcError("com.atproto.identity.resolveHandle", None, f"no did for {handle}")
    return str(answer["did"])


def get_profile(host: str, actor: str, *, token: str | None = None) -> dict[str, Any]:
    """The public profile (handle, display name) of ``actor``."""
    profile = _call(host, "app.bsky.actor.getProfile", token=token, params={"actor": actor})
    if not isinstance(profile, dict):
        raise XrpcError("app.bsky.actor.getProfile", None, "not a profile")
    return profile


def upload_blob(host: str, token: str, path: str, data: bytes, mime: str) -> dict[str, Any]:
    """Upload one file as a blob; answers the blob reference the record embeds."""
    answer = _call(host, "com.atproto.repo.uploadBlob", token=token, data=data, content_type=mime)
    if not isinstance(answer, dict) or not isinstance(answer.get("blob"), dict):
        raise XrpcError("com.atproto.repo.uploadBlob", None, f"no blob for {path}")
    return dict(answer["blob"])


def create_record(host: str, token: str, did: str, record: dict[str, Any]) -> dict[str, str]:
    """Write one post record; answers its ``uri`` and ``cid`` for the thread."""
    payload = json.dumps({"repo": did, "collection": POST_COLLECTION, "record": record}).encode()
    answer = _call(host, "com.atproto.repo.createRecord", token=token, data=payload)
    if not isinstance(answer, dict) or not answer.get("uri") or not answer.get("cid"):
        raise XrpcError("com.atproto.repo.createRecord", None, "no uri for the post")
    return {"uri": str(answer["uri"]), "cid": str(answer["cid"])}


def get_posts(host: str, uris: list[str], *, token: str | None = None) -> list[dict[str, Any]]:
    """Read posts back by URI; the reply order follows ``uris``."""
    params = [("uris", uri) for uri in uris]
    url = f"{host}/xrpc/app.bsky.feed.getPosts?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, method="GET")
    request.add_header("Accept", "application/json")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            answer = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error("app.bsky.feed.getPosts", exc) from exc
    except urllib.error.URLError as exc:
        raise XrpcError("app.bsky.feed.getPosts", None, f"unreachable: {exc.reason}") from exc
    if not isinstance(answer, dict) or not isinstance(answer.get("posts"), list):
        raise XrpcError("app.bsky.feed.getPosts", None, "no posts in the answer")
    return [post for post in answer["posts"] if isinstance(post, dict)]
