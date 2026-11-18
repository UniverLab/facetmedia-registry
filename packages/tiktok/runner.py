"""The tiktok package runner: send a draft to the inbox, then read it back.

Six verbs on the runner SDK. ``dry-run`` sends nothing: it checks the
video against TikTok's format and size limits (MP4, WebM or MOV, at most
4 GiB, chunked per TikTok's 5 MB to 64 MB rule), or warns that photo URLs
must ride a domain the TikTok app verified, and shows what will land in
the inbox. ``run`` uploads one video in chunks or one photo set by URL,
then answers the receipt's ``post`` object with state ``draft`` and the
account's profile URL, since a draft has no URL of its own. ``verify``
reads the publish status back and passes only when TikTok reports the
draft reached the inbox. ``preview`` writes the post schema's preview
beside the receipt. ``doctor`` checks the secrets at ``quick`` and the
account plus the ``video.upload`` grant at ``full``. ``auth`` runs the
lab's OAuth sign-in and stores the tokens through facet's secrets store.
"""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Callable, Mapping
from http import HTTPStatus
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tiktok_client
from facet_runner_sdk import Request, Runner, renew_secret, secret
from tiktok_client import TikTokError

runner = Runner()

#: The network this package posts to, as receipts and previews name it.
NETWORK = "tiktok"
#: The containers TikTok's upload takes: MP4, WebM and MOV.
VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}
#: The largest video TikTok's upload takes.
VIDEO_LIMIT = 4 * 1024 * 1024 * 1024
#: The smallest chunk TikTok's upload takes, except a merged final one.
MIN_CHUNK = 5 * 1024 * 1024
#: The chunk size the runner uploads with, inside TikTok's 5 MB to 64 MB rule.
CHUNK_SIZE = 10 * 1024 * 1024
#: What the dry run names as the account: it sends nothing, so it reads none.
UNREAD_ACCOUNT = "@not-read"
#: The caption rides nowhere: the user pastes it in the app.
PASTE_WARNING = "paste the caption in the TikTok app: the inbox flow takes no caption"
#: A draft never lands on the profile: it waits in the app's inbox.
INBOX_WARNING = "lands in the account's inbox as a draft, not on the profile"
#: Photo URLs must ride a domain the TikTok app verified.
DOMAIN_WARNING = (
    "photo URLs must ride a domain the TikTok app verified, "
    "over https with no redirect, or TikTok refuses the upload"
)


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _inputs(req: Request) -> dict[str, Any]:
    """The piece's inputs as a plain map."""
    return dict(req.inputs)


def _caption(inputs: Mapping[str, Any]) -> str:
    """The caption the user will paste in the app; a piece without one is refused."""
    caption = inputs.get("caption")
    if not isinstance(caption, str) or not caption:
        raise ValueError("the piece has no caption")
    return caption


def _resolve_video(req: Request, inputs: Mapping[str, Any]) -> Path | None:
    """The video file, resolved relative to the piece, or nothing when absent."""
    value = inputs.get("video")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("the piece's video is not a path")
    path = Path(value)
    if not path.is_absolute():
        path = req.piece_dir / path
    return path


def _photo_urls(inputs: Mapping[str, Any]) -> list[str] | None:
    """The photo set's URLs, or nothing when the piece carries no photos."""
    value = inputs.get("photos")
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError("the piece's photos are not a URL list")
    urls: list[str] = []
    for position, item in enumerate(value, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            raise ValueError(f"photos[{position}]: no photo URL")
        url = str(item["url"])
        if not url.startswith("https://"):
            raise ValueError(f"photos[{position}]: the URL must use https")
        urls.append(url)
    return urls


def _kind(video: Path | None, urls: list[str] | None) -> str:
    """Which inbox flow the piece takes; a piece takes exactly one."""
    if video is not None and urls is not None:
        raise ValueError("the piece carries a video and photos: send exactly one")
    if video is None and urls is None:
        raise ValueError("the piece carries no video and no photos")
    return "video" if video is not None else "photos"


def _check_video(path: Path) -> int:
    """Refuse a video TikTok would reject, and answer its byte size."""
    if path.suffix.lower() not in VIDEO_MIME:
        raise ValueError(f"{path.name} is not an MP4, WebM or MOV video")
    try:
        size = path.stat().st_size
    except OSError:
        raise ValueError(f"{path} is not a file") from None
    if size <= 0:
        raise ValueError(f"{path.name} is empty")
    if size > VIDEO_LIMIT:
        raise ValueError(f"{path.name} is {size} bytes, over the {VIDEO_LIMIT} limit")
    return size


def _chunk_plan(size: int) -> tuple[int, int]:
    """The chunk size and count inside TikTok's chunk rule.

    Every chunk but the last rides at ``CHUNK_SIZE``; a trailing fragment
    below the minimum merges into the previous chunk instead of riding
    alone, which TikTok would refuse.
    """
    if size < MIN_CHUNK:
        return size, 1
    count = (size + CHUNK_SIZE - 1) // CHUNK_SIZE
    if count > 1 and size % CHUNK_SIZE != 0 and size % CHUNK_SIZE < MIN_CHUNK:
        count -= 1
    return CHUNK_SIZE, count


def _expired(exc: TikTokError) -> bool:
    """Whether the token expired, as opposed to missing a granted scope.

    TikTok answers both an expired token and a missing grant with 401,
    so a missing scope must not trigger a refresh round trip: nothing a
    fresh token carries would grant it.
    """
    if tiktok_client.SCOPE_MISSING in exc.error:
        return False
    return exc.status == HTTPStatus.UNAUTHORIZED or tiktok_client.TOKEN_INVALID in exc.error


def _stored(name: str) -> str:
    """One stored secret; a missing one names the sign-in that stores it."""
    try:
        return secret(name)
    except KeyError as exc:
        raise ValueError(str(exc)) from exc


def _refresh() -> str:
    """Trade the stored refresh token for a fresh pair, kept via store-back.

    Both renewed tokens ride facet's store-back mechanism at once, so a
    rotated token is kept even when the verb fails later; a renewed token
    never lives only in this process's memory.
    """
    key = _stored("client-key")
    client_secret = _stored("client-secret")
    refresh_token = _stored("refresh-token")
    try:
        tokens = tiktok_client.refresh_tokens(key, client_secret, refresh_token)
    except TikTokError as exc:
        raise ValueError(f"the token refresh failed: {exc}") from exc
    renew_secret("access-token", tokens.access_token)
    renew_secret("refresh-token", tokens.refresh_token)
    return tokens.access_token


def _with_token(action: Callable[[str], Any]) -> tuple[Any, str]:
    """Run ``action`` with a working token, refreshing once on expiry.

    The refresh rides the store-back mechanism, so the rotated pair is
    kept; anything else TikTok refuses fails with TikTok's own reason.
    """
    access = _stored("access-token")
    try:
        return action(access), access
    except TikTokError as exc:
        if not _expired(exc):
            raise ValueError(f"TikTok refused: {exc}") from exc
    fresh = _refresh()
    try:
        return action(fresh), fresh
    except TikTokError as exc:
        raise ValueError(f"TikTok refused: {exc}") from exc


def _creator_handle(creator: Mapping[str, Any]) -> str:
    """The account's handle, read from the creator TikTok names."""
    username = creator.get("creator_username")
    if not isinstance(username, str) or not username:
        raise ValueError("the account read no handle")
    return "@" + username.lstrip("@")


def _account() -> tuple[str, str]:
    """The account's handle and a working token, refreshing once on expiry."""
    creator, access = _with_token(tiktok_client.creator_info)
    if not isinstance(creator, dict):
        raise ValueError("the account read no creator")
    return _creator_handle(creator), access


def _profile_url(handle: str) -> str:
    """The account's public profile URL: a draft has no URL of its own."""
    return f"https://www.tiktok.com/{handle}"


def _dry_run_video(path: Path) -> tuple[list[str], list[str]]:
    """The dry run's media and warnings for one video, sending nothing."""
    warnings: list[str] = []
    if path.suffix.lower() not in VIDEO_MIME:
        raise ValueError(f"{path.name} is not an MP4, WebM or MOV video")
    if not path.is_file():
        raise ValueError(f"{path} is not a file")
    try:
        size = path.stat().st_size
    except OSError:
        raise ValueError(f"{path} cannot be read") from None
    if size > VIDEO_LIMIT:
        warnings.append(f"{path.name} is {size} bytes, over the {VIDEO_LIMIT} limit")
    return [str(path)], warnings


@runner.verb("dry-run")
def dry_run(req: Request) -> dict[str, Any]:
    inputs = _inputs(req)
    caption = _caption(inputs)
    video = _resolve_video(req, inputs)
    urls = _photo_urls(inputs)
    kind = _kind(video, urls)
    post_warnings: list[str] = []
    if kind == "video":
        assert video is not None
        media, post_warnings = _dry_run_video(video)
    else:
        assert urls is not None
        media = list(urls)
        post_warnings = [DOMAIN_WARNING]
    rendered = {
        "text": caption,
        "account": UNREAD_ACCOUNT,
        "media": media,
        "warnings": post_warnings,
        "cost": None,
    }
    group = [
        f"this {kind} {INBOX_WARNING}",
        PASTE_WARNING,
    ]
    return {"posts": [rendered], "warnings": group}


def _send_video(access: str, path: Path) -> str:
    """Upload one video in chunks and answer its publish id."""
    size = _check_video(path)
    chunk_size, count = _chunk_plan(size)
    mime = VIDEO_MIME[path.suffix.lower()]
    try:
        publish_id, upload_url = tiktok_client.init_video_upload(access, size, chunk_size, count)
    except TikTokError as exc:
        raise ValueError(f"the upload init failed: {exc}") from exc
    try:
        with open(path, "rb") as handle:
            for index in range(count):
                first = index * chunk_size
                handle.seek(first)
                data = handle.read(chunk_size if index < count - 1 else size - first)
                last = first + len(data) - 1
                done = tiktok_client.upload_chunk(upload_url, mime, data, first, last, size)
                if done and index < count - 1:
                    raise ValueError("TikTok closed the upload before the last chunk")
    except OSError as exc:
        raise ValueError(f"{path} cannot be read") from exc
    except TikTokError as exc:
        raise ValueError(f"the video upload failed: {exc}") from exc
    return publish_id


def _send_photos(access: str, urls: list[str]) -> str:
    """Start the photo upload by URL and answer its publish id.

    TikTok downloads the photos itself, so a URL it refuses fails here,
    before anything lands in the inbox.
    """
    try:
        return tiktok_client.init_photo_upload(access, urls)
    except TikTokError as exc:
        raise ValueError(f"the photo upload failed: {exc}") from exc


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    inputs = _inputs(req)
    _caption(inputs)
    video = _resolve_video(req, inputs)
    urls = _photo_urls(inputs)
    kind = _kind(video, urls)
    if kind == "video":
        assert video is not None
        _check_video(video)
    handle, access = _account()
    if kind == "video":
        assert video is not None
        publish_id = _send_video(access, video)
    else:
        assert urls is not None
        publish_id = _send_photos(access, urls)
    return {
        "tool": _tool(),
        "post": {
            "network": NETWORK,
            "account": handle,
            "state": "draft",
            "posts": [{"id": publish_id, "url": _profile_url(handle)}],
            "cost": None,
        },
    }


def _is_video_piece(inputs: Mapping[str, Any]) -> bool:
    """Whether the piece sent a video rather than a photo set."""
    return inputs.get("video") is not None


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    refs = req.post.get("posts")
    if not isinstance(refs, list) or not refs:
        raise ValueError("the receipt names no posts")
    first = refs[0]
    if not isinstance(first, dict) or not isinstance(first.get("id"), str):
        raise ValueError("the receipt names no publish id")
    publish_id = str(first["id"])
    outcome, _ = _with_token(lambda token: tiktok_client.publish_status(token, publish_id))
    status, reason = outcome
    if status == tiktok_client.FAILED_STATUS:
        detail = f": {reason}" if reason else ""
        raise ValueError(f"TikTok reports the upload failed{detail}")
    if status != tiktok_client.INBOX_STATUS:
        raise ValueError(f"the draft is not in the inbox yet: {status}")
    media: list[dict[str, Any]] = []
    if _is_video_piece(dict(req.inputs)):
        media = [{"file": f"{publish_id}.video", "alt": None}]
    return {"state": "draft", "media": media}


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    if not req.assets:
        raise ValueError("preview needs the receipt")
    receipt = json.loads(req.assets[0].read_text(encoding="utf-8"))
    inputs = _inputs(req)
    caption = _caption(inputs)
    refs = receipt.get("posts")
    if not isinstance(refs, list) or not refs or not isinstance(refs[0], dict):
        raise ValueError("the receipt holds no post")
    url = refs[0].get("url")
    if not isinstance(url, str):
        raise ValueError("the receipt names no url")
    video = _resolve_video(req, inputs)
    images: list[str] = []
    media: list[dict[str, Any]] = []
    if video is not None:
        images = [video.name]
        media = [{"file": video.name, "alt": None}]
    network = str(receipt.get("network", NETWORK))
    account = str(receipt.get("account", ""))
    state = str(receipt.get("state", "draft"))
    summary = (f"draft on {network} as {account}, waiting in the app's inbox: {PASTE_WARNING}")[
        :160
    ]
    data = {
        "preview": 1,
        "kind": "post",
        "summary": summary,
        "network": network,
        "account": account,
        "state": state,
        "images": images,
        "posts": [{"text": caption, "url": url, "media": media}],
    }
    name = f"{req.assets[0].name}.preview.json"
    (req.out_dir / name).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
    return {"assets": [{"file": name}]}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names what fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_imports() -> dict[str, Any]:
    """The vendored client answers its own smoke test."""
    if not callable(tiktok_client.publish_status):
        return _check("imports", False, "the TikTok client is missing", "facet pull tiktok")
    return _check("imports", True, "client answers")


def _doctor_secrets() -> list[dict[str, Any]]:
    """All five secrets are stored; a value never appears in a detail."""
    checks = []
    for name in ("client-key", "client-secret", "access-token", "refresh-token", "open-id"):
        try:
            secret(name)
        except KeyError as exc:
            checks.append(_check(name, False, f"{name} is not stored", str(exc)))
        else:
            checks.append(_check(name, True, f"{name} is stored"))
    return checks


def _doctor_session() -> dict[str, Any]:
    """Read the account and prove the video.upload grant, refreshing once.

    The refresh rides the store-back mechanism, so a rotated token is
    kept; the user read names the account and the creator read proves the
    grant, since TikTok answers it only to a video.upload token.
    """
    try:
        outcome, _ = _with_token(tiktok_client.user_info)
    except ValueError as exc:
        return _check("session", False, str(exc), "facet auth tiktok")
    user = outcome if isinstance(outcome, dict) else {}
    name = user.get("display_name") or user.get("open_id") or ""
    try:
        creator, _ = _with_token(tiktok_client.creator_info)
    except ValueError as exc:
        if tiktok_client.SCOPE_MISSING in str(exc):
            return _check(
                "session",
                False,
                f"signed in as {name}: the video.upload scope was not granted",
                "approve video.upload for the app, then run facet auth tiktok",
            )
        return _check("session", False, str(exc), "facet auth tiktok")
    if not isinstance(creator, dict):
        return _check("session", False, "the account read no creator", "facet auth tiktok")
    try:
        handle = _creator_handle(creator)
    except ValueError as exc:
        return _check("session", False, str(exc), "facet auth tiktok")
    nickname = creator.get("creator_nickname") or name
    return _check(
        "session",
        True,
        f"signed in as {nickname} ({handle}): the video.upload scope was granted",
    )


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_imports(), *_doctor_secrets()]
    if req.depth == "full":
        checks.append(_doctor_session())
    return {"checks": checks}


@runner.verb("auth")
def auth(req: Request) -> dict[str, Any]:
    try:
        key = secret("client-key")
        client_secret = secret("client-secret")
    except KeyError as exc:
        raise ValueError(str(exc)) from exc
    redirect = req.inputs.get("redirect-uri")
    if redirect is not None and (not isinstance(redirect, str) or not redirect):
        raise ValueError("the redirect URI is not a URI")
    uri = str(redirect) if isinstance(redirect, str) else "http://127.0.0.1:8080/callback"
    try:
        secrets = tiktok_client.authorize(key, client_secret, uri)
    except TikTokError as exc:
        raise ValueError(str(exc)) from exc
    return {"secrets": secrets}


runner.main()
