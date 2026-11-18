"""Thin YouTube Data API v3 client for facet's youtube package.

Google libraries are imported lazily so tests can replace this module's
network-facing functions without the SDK installed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
UPLOAD_CHUNK_SIZE = -1
UPLOAD_RETRIES = 3


class YouTubeError(Exception):
    """A YouTube API or OAuth failure."""


@dataclass(frozen=True)
class ChannelInfo:
    """The channel the credentials belong to."""

    id: str
    title: str
    handle: str | None


def _lazy_google() -> dict[str, Any]:
    try:
        from google.oauth2.credentials import Credentials  # noqa: PLC0415
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415
        from googleapiclient.discovery import build  # noqa: PLC0415
        from googleapiclient.http import MediaFileUpload  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - exercised when deps missing
        raise YouTubeError(f"google libraries unavailable: {exc}") from exc
    return {
        "Credentials": Credentials,
        "InstalledAppFlow": InstalledAppFlow,
        "build": build,
        "MediaFileUpload": MediaFileUpload,
    }


def authorize(client_id: str, client_secret: str) -> dict[str, str]:
    """Run an installed-app OAuth flow and return the stored secrets."""
    libs = _lazy_google()
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = libs["InstalledAppFlow"].from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    refresh = getattr(creds, "refresh_token", None)
    if not isinstance(refresh, str) or not refresh:
        raise YouTubeError("no refresh token was returned; authorize again with consent")
    return {
        "client-id": client_id,
        "client-secret": client_secret,
        "refresh-token": refresh,
    }


def _credentials(client_id: str, client_secret: str, refresh_token: str) -> Any:
    libs = _lazy_google()
    creds = libs["Credentials"](
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    try:
        from google.auth.transport.requests import (  # noqa: PLC0415
            Request as GoogleRequest,
        )

        creds.refresh(GoogleRequest())
    except Exception as exc:
        raise YouTubeError(f"refresh token failed: {exc}") from exc
    return creds


def _service(client_id: str, client_secret: str, refresh_token: str) -> Any:
    libs = _lazy_google()
    creds = _credentials(client_id, client_secret, refresh_token)
    try:
        return libs["build"]("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:
        raise YouTubeError(f"youtube client unavailable: {exc}") from exc


def channel(client_id: str, client_secret: str, refresh_token: str) -> ChannelInfo:
    """Return the channel (title and handle) for the authenticated token."""
    service = _service(client_id, client_secret, refresh_token)
    try:
        response = service.channels().list(part="snippet", mine=True, maxResults=1).execute()
    except Exception as exc:
        raise YouTubeError(f"channel lookup failed: {exc}") from exc
    items = response.get("items") or [] if isinstance(response, dict) else []
    if not items:
        raise YouTubeError("no channel was found for this token")
    item = items[0] if isinstance(items[0], dict) else {}
    snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
    title = str(snippet.get("title") or "")
    handle = snippet.get("customUrl")
    if isinstance(handle, str) and handle and not handle.startswith("@"):
        handle = "@" + handle
    channel_id = str(item.get("id") or "")
    if not title:
        raise YouTubeError("the channel has no title")
    return ChannelInfo(
        id=channel_id, title=title, handle=handle if isinstance(handle, str) else None
    )


def upload_video(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    path: str | Path,
    body: dict[str, Any],
    notify_subscribers: bool,
    on_progress: Callable[[Any], None] | None = None,
) -> str:
    """Upload a video resumably and return its video id."""
    libs = _lazy_google()
    service = _service(client_id, client_secret, refresh_token)
    try:
        media = libs["MediaFileUpload"](str(path), chunksize=UPLOAD_CHUNK_SIZE, resumable=True)
        request = service.videos().insert(
            part="snippet,status",
            body=body,
            notifySubscribers=bool(notify_subscribers),
            media_body=media,
        )
    except Exception as exc:
        raise YouTubeError(f"upload could not start: {exc}") from exc
    response = None
    retries = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status and on_progress:
                on_progress(status)
        except Exception as exc:
            retries += 1
            if retries > UPLOAD_RETRIES:
                raise YouTubeError(f"upload failed: {exc}") from exc
    if not isinstance(response, dict) or not response.get("id"):
        raise YouTubeError("upload finished without a video id")
    return str(response["id"])


def set_thumbnail(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    video_id: str,
    path: str | Path,
) -> None:
    """Upload a custom thumbnail for ``video_id``."""
    libs = _lazy_google()
    service = _service(client_id, client_secret, refresh_token)
    try:
        media = libs["MediaFileUpload"](str(path), resumable=False)
        service.thumbnails().set(videoId=video_id, media_body=media).execute()
    except Exception as exc:
        raise YouTubeError(f"thumbnail upload failed: {exc}") from exc


def video_state(
    client_id: str, client_secret: str, refresh_token: str, video_id: str
) -> dict[str, Any]:
    """Return the video's status and processing details."""
    service = _service(client_id, client_secret, refresh_token)
    try:
        response = (
            service.videos()
            .list(part="status,processingDetails", id=video_id, maxResults=1)
            .execute()
        )
    except Exception as exc:
        raise YouTubeError(f"video lookup failed: {exc}") from exc
    items = response.get("items") or [] if isinstance(response, dict) else []
    if not items:
        raise YouTubeError("video not found")
    item = items[0] if isinstance(items[0], dict) else {}
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    processing = (
        item.get("processingDetails") if isinstance(item.get("processingDetails"), dict) else {}
    )
    return {"status": status, "processingDetails": processing}
