"""The youtube package runner: upload one video, then read it back."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import video_meta
import youtube_client
from facet_runner_sdk import Request, Runner, secret
from video_meta import SHORTS_MAX_S
from youtube_client import YouTubeError

runner = Runner()

NETWORK = "youtube"
TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 5000
THUMBNAIL_LIMIT = 2 * 1024 * 1024
UNREAD_ACCOUNT = "@not-read"


def _manifest() -> dict[str, Any]:
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _resolve_path(req: Request, value: Any, field: str, required: bool = True) -> Path | None:
    if value is None:
        if required:
            raise ValueError(f"the piece has no {field}")
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"the piece has no {field}")
    path = Path(value)
    if not path.is_absolute():
        path = req.piece_dir / path
    return path


def _inputs(req: Request) -> dict[str, Any]:
    return dict(req.inputs)


def _text(title: Any, description: Any) -> str:
    if not isinstance(title, str):
        raise ValueError("the piece has no title")
    if not isinstance(description, str):
        raise ValueError("the piece has no description")
    return f"{title}\n\n{description}"


def _tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("tags must be a list")
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and isinstance(item.get("tag"), str):
            out.append(item["tag"])
        else:
            raise ValueError("each tag must be a string or an object with tag")
    return out


def _privacy(value: Any) -> str:
    if value is None:
        return "private"
    if not isinstance(value, str) or value not in {"private", "unlisted", "public"}:
        raise ValueError("privacy must be private, unlisted or public")
    return value


def _state_for_privacy(privacy: str) -> str:
    return "private" if privacy == "private" else "published"


def _is_synthetic(req: Request, inputs: dict[str, Any]) -> bool:
    if bool(inputs.get("synthetic", False)):
        return True
    for source in getattr(req, "sources", []) or []:
        if isinstance(source, dict) and source.get("generated"):
            return True
        generated = getattr(source, "generated", None)
        if generated:
            return True
    return False


def _warnings(
    req: Request, inputs: dict[str, Any], info: video_meta.VideoInfo | None
) -> tuple[list[str], list[str]]:
    title = inputs.get("title")
    description = inputs.get("description")
    post_warnings: list[str] = []
    if isinstance(title, str) and len(title) > TITLE_LIMIT:
        post_warnings.append(f"title is {len(title)} characters, over the {TITLE_LIMIT} limit")
    if isinstance(description, str) and len(description) > DESCRIPTION_LIMIT:
        post_warnings.append(
            f"description is {len(description)} characters, over the {DESCRIPTION_LIMIT} limit"
        )
    video = _resolve_path(req, inputs.get("video"), "video", required=True)
    if video is None or not video.is_file():
        raise ValueError(f"video: {video} is not a file")
    if info is not None and info.height > info.width and info.duration_s <= SHORTS_MAX_S:
        post_warnings.append("a vertical video under 180 s will become a Short")
    thumb = _resolve_path(req, inputs.get("thumbnail"), "thumbnail", required=False)
    if thumb is not None and not thumb.is_file():
        raise ValueError(f"thumbnail: {thumb} is not a file")
    if thumb is not None:
        try:
            size = thumb.stat().st_size
        except OSError as exc:
            raise ValueError(f"thumbnail: {thumb} cannot be read") from exc
        if size > THUMBNAIL_LIMIT:
            post_warnings.append(
                f"thumbnail {thumb.name} is {size} bytes, over the {THUMBNAIL_LIMIT} limit"
            )
    privacy = _privacy(inputs.get("privacy"))
    synthetic = _is_synthetic(req, inputs)
    made_for_kids = inputs.get("made-for-kids")
    category = inputs.get("category")
    tags = _tags(inputs.get("tags"))
    notify = bool(inputs.get("notify-subscribers", True))
    group = [
        f"privacy: {privacy}",
        f"synthetic: {'yes' if synthetic else 'no'}",
        f"made for kids: {'yes' if bool(made_for_kids) else 'no'}",
        f"category: {category}",
        f"tags: {', '.join(tags) if tags else '(none)'}",
        f"notify subscribers: {'yes' if notify else 'no'}",
    ]
    return post_warnings, group


@runner.verb("dry-run")
def dry_run(req: Request) -> dict[str, Any]:
    inputs = _inputs(req)
    title = inputs.get("title")
    description = inputs.get("description")
    if not isinstance(title, str) or not title:
        raise ValueError("the piece has no title")
    if not isinstance(description, str):
        raise ValueError("the piece has no description")
    if not isinstance(inputs.get("category"), str) or not inputs.get("category"):
        raise ValueError("the piece has no category")
    if "made-for-kids" not in inputs or not isinstance(inputs.get("made-for-kids"), bool):
        raise ValueError("made-for-kids is required")
    video = _resolve_path(req, inputs.get("video"), "video", required=True)
    assert video is not None
    info = video_meta.probe(video)
    post_warnings, group = _warnings(req, inputs, info)
    media = [str(video)]
    thumb = _resolve_path(req, inputs.get("thumbnail"), "thumbnail", required=False)
    if thumb is not None:
        media.append(str(thumb))
    post = {
        "text": _text(title, description),
        "account": UNREAD_ACCOUNT,
        "media": media,
        "warnings": post_warnings,
        "cost": None,
    }
    return {"posts": [post], "warnings": group}


def _client_secrets() -> tuple[str, str, str]:
    return secret("client-id"), secret("client-secret"), secret("refresh-token")


def _channel_label(info: youtube_client.ChannelInfo) -> str:
    return info.handle or info.title or info.id


def _channel_display(info: youtube_client.ChannelInfo) -> str:
    handle = info.handle or "(no handle)"
    return f"{info.title} ({handle})"


def _public_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    inputs = _inputs(req)
    title = inputs.get("title")
    description = inputs.get("description")
    category = inputs.get("category")
    if not isinstance(title, str) or not title:
        raise ValueError("the piece has no title")
    if not isinstance(description, str):
        raise ValueError("the piece has no description")
    if not isinstance(category, str) or not category:
        raise ValueError("the piece has no category")
    if "made-for-kids" not in inputs or not isinstance(inputs.get("made-for-kids"), bool):
        raise ValueError("made-for-kids is required")
    if len(title) > TITLE_LIMIT:
        raise ValueError(f"title is over the {TITLE_LIMIT} limit")
    if len(description) > DESCRIPTION_LIMIT:
        raise ValueError(f"description is over the {DESCRIPTION_LIMIT} limit")
    video = _resolve_path(req, inputs.get("video"), "video", required=True)
    assert video is not None
    if not video.is_file():
        raise ValueError(f"video: {video} is not a file")
    thumb = _resolve_path(req, inputs.get("thumbnail"), "thumbnail", required=False)
    if thumb is not None and not thumb.is_file():
        raise ValueError(f"thumbnail: {thumb} is not a file")
    privacy = _privacy(inputs.get("privacy"))
    synthetic = _is_synthetic(req, inputs)
    made_for_kids = bool(inputs.get("made-for-kids"))
    notify = bool(inputs.get("notify-subscribers", True))
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": _tags(inputs.get("tags")),
            "categoryId": str(category),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": made_for_kids,
            "containsSyntheticMedia": synthetic,
        },
    }
    client_id, client_secret, refresh_token = _client_secrets()
    try:
        channel_info = youtube_client.channel(client_id, client_secret, refresh_token)
        account = _channel_label(channel_info)
    except YouTubeError as exc:
        raise ValueError(f"the channel could not be read: {exc}") from exc
    try:
        video_id = youtube_client.upload_video(
            client_id, client_secret, refresh_token, video, body, notify
        )
    except YouTubeError as exc:
        raise ValueError(f"upload failed: {exc}") from exc
    warnings: list[str] = []
    if thumb is not None:
        try:
            youtube_client.set_thumbnail(client_id, client_secret, refresh_token, video_id, thumb)
        except YouTubeError as exc:
            warnings.append(f"thumbnail upload failed: {exc}")
    state = _state_for_privacy(privacy)
    post = {
        "network": NETWORK,
        "account": account,
        "state": state,
        "posts": [{"id": video_id, "url": _public_url(video_id)}],
        "cost": None,
    }
    if warnings:
        post["warnings"] = warnings
    return {"tool": _tool(), "post": post}


def _privacy_matches_receipt(privacy_status: str, receipt_state: str) -> bool:
    if receipt_state == "private":
        return privacy_status == "private"
    if receipt_state == "published":
        return privacy_status in {"public", "unlisted"}
    return privacy_status == receipt_state


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    refs = req.post.get("posts")
    if not isinstance(refs, list) or not refs:
        raise ValueError("the receipt names no posts")
    first = refs[0]
    if not isinstance(first, dict) or not isinstance(first.get("id"), str):
        raise ValueError("the receipt names no video id")
    video_id = str(first["id"])
    client_id, client_secret, refresh_token = _client_secrets()
    try:
        state = youtube_client.video_state(client_id, client_secret, refresh_token, video_id)
    except YouTubeError as exc:
        msg = str(exc).lower()
        if "not found" in msg:
            raise ValueError(f"the network holds no video {video_id}") from exc
        raise ValueError(f"the read-back failed: {exc}") from exc
    status = state.get("status") or {}
    processing = state.get("processingDetails") or {}
    privacy_status = str(status.get("privacyStatus") or "")
    receipt_state = str(req.post.get("state") or "")
    if not _privacy_matches_receipt(privacy_status, receipt_state):
        raise ValueError("the network holds a different privacy")
    upload_status = str(status.get("uploadStatus") or "")
    if upload_status in {"failed", "rejected", "deleted"}:
        raise ValueError(f"processing did not succeed: uploadStatus {upload_status}")
    processing_status = str(processing.get("processingStatus") or "")
    if processing_status in {"failed", "terminated"}:
        raise ValueError(f"processing did not succeed: processingStatus {processing_status}")
    sources = getattr(req, "sources", []) or []
    media = [{"file": f"{video_id}.video", "alt": None} for _ in sources]
    return {"state": receipt_state, "media": media}


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    if not req.assets:
        raise ValueError("preview needs the receipt")
    receipt = json.loads(req.assets[0].read_text(encoding="utf-8"))
    inputs = _inputs(req)
    title = inputs.get("title")
    description = inputs.get("description")
    if not isinstance(title, str) or not isinstance(description, str):
        raise ValueError("the piece has no title or description")
    refs = receipt.get("posts")
    if not isinstance(refs, list) or not refs or not isinstance(refs[0], dict):
        raise ValueError("the receipt holds no post")
    url = refs[0].get("url")
    if not isinstance(url, str):
        raise ValueError("the receipt names no url")
    images: list[str] = []
    media: list[dict[str, Any]] = []
    video = _resolve_path(req, inputs.get("video"), "video", required=False)
    if video is not None:
        images.append(video.name)
        media.append({"file": video.name, "alt": None})
    thumb = _resolve_path(req, inputs.get("thumbnail"), "thumbnail", required=False)
    if thumb is not None:
        images.append(thumb.name)
        media.append({"file": thumb.name, "alt": None})
    network = str(receipt.get("network", NETWORK))
    account = str(receipt.get("account", ""))
    state = str(receipt.get("state", "private"))
    data = {
        "preview": 1,
        "kind": "post",
        "summary": f"1 video on {network} as {account}, {state}"[:160],
        "network": network,
        "account": account,
        "state": state,
        "images": images,
        "posts": [{"text": _text(title, description), "url": url, "media": media}],
    }
    name = f"{req.assets[0].name}.preview.json"
    (req.out_dir / name).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
    return {"assets": [{"file": name}]}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_imports() -> dict[str, Any]:
    if not callable(youtube_client.channel):
        return _check("imports", False, "the YouTube client is missing", "facet pull youtube")
    return _check("imports", True, "client and probe answer")


def _missing_secret(name: str) -> str | None:
    try:
        secret(name)
    except KeyError as exc:
        return str(exc)
    return None


def _doctor_secrets() -> list[dict[str, Any]]:
    checks = []
    for name in ("client-id", "client-secret", "refresh-token"):
        missing = _missing_secret(name)
        if missing is None:
            checks.append(_check(name, True, f"{name} is stored"))
        else:
            checks.append(_check(name, False, f"{name} is not stored", missing))
    return checks


def _doctor_session() -> dict[str, Any]:
    try:
        client_id, client_secret, refresh_token = _client_secrets()
    except KeyError as exc:
        return _check("session", False, str(exc), "facet auth youtube")
    try:
        info = youtube_client.channel(client_id, client_secret, refresh_token)
    except YouTubeError as exc:
        return _check(
            "session",
            False,
            f"token check failed: {exc}",
            "facet auth youtube",
        )
    return _check(
        "session",
        True,
        f"token works for channel {_channel_display(info)}",
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
        client_id = secret("client-id")
        client_secret = secret("client-secret")
    except KeyError as exc:
        raise ValueError(str(exc)) from exc
    try:
        secrets = youtube_client.authorize(client_id, client_secret)
    except YouTubeError as exc:
        raise ValueError(str(exc)) from exc
    return {"secrets": secrets}


runner.main()
