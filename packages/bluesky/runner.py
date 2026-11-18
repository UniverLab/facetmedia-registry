"""The bluesky package runner: post a thread, read it back, preview it.

Five verbs on the runner SDK. ``dry-run`` sends nothing: it renders every
post, counts graphemes against the network's limit and warns about
over-long text, images over the byte limit and a link card without a
thumbnail. ``run`` signs in with the stored handle and app password,
uploads the media, sends the posts in order with each later post replying
to the previous one, and answers the receipt's ``post`` object.
``verify`` reads every receipt post back and checks it exists, its text
matches the piece and its media count matches. ``preview`` writes the
post schema's preview file beside the receipt. ``doctor`` checks the
secrets at ``quick`` and signs in at ``full``.
"""

from __future__ import annotations

import datetime
import json
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import richtext
import xrpc_client
from facet_runner_sdk import Request, Runner, secret
from xrpc_client import XrpcError

runner = Runner()

#: The network this package posts to, as receipts and previews name it.
NETWORK = "bluesky"
#: At most four images ride one post; one video rides alone instead.
MAX_IMAGES_PER_POST = 4
#: A Bluesky image blob carries at most one megabyte.
IMAGE_BLOB_LIMIT = 1_000_000
#: A Bluesky video blob carries at most one hundred megabytes.
VIDEO_BLOB_LIMIT = 100_000_000
IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
VIDEO_MIME = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}


@dataclass(frozen=True)
class Attachment:
    """One upload of a post: an image, its video, or its card thumbnail."""

    post: int
    path: Path
    alt: str | None
    kind: str


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _account() -> str:
    """The brand account's handle, from the secrets store."""
    return secret("handle")


def _posts(inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The thread's posts; a piece without one is refused before anything leaves."""
    posts = inputs.get("posts")
    if not isinstance(posts, list) or not posts:
        raise ValueError("the piece has no posts")
    return [dict(item) for item in posts if isinstance(item, dict)]


def _image_rows(inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The piece's image table, empty when the thread carries none."""
    images = inputs.get("images", [])
    if not isinstance(images, list):
        raise ValueError("the piece's images are not a list")
    return [dict(item) for item in images if isinstance(item, dict)]


def _attachments(
    posts: list[dict[str, Any]], image_rows: list[dict[str, Any]]
) -> dict[int, list[Attachment]]:
    """Every post's uploads, checked: alts, counts, indexes and card bodies."""
    media: dict[int, list[Attachment]] = {index: [] for index in range(1, len(posts) + 1)}
    for position, item in enumerate(image_rows, start=1):
        post = item.get("post")
        path = item.get("path")
        alt = item.get("alt")
        if not isinstance(post, int) or isinstance(post, bool) or post not in media:
            raise ValueError(f"images[{position}]: no post {post!r} in this thread")
        if not isinstance(path, str) or not path:
            raise ValueError(f"images[{position}]: no image path")
        if not isinstance(alt, str) or not alt:
            raise ValueError(f"images[{position}]: an image without alt text is refused")
        media[post].append(Attachment(post=post, path=Path(path), alt=alt, kind="image"))
    for index, post in enumerate(posts, start=1):
        _check_card(index, post)
        has_card = post.get("card-url") is not None
        video = post.get("video")
        if video is not None:
            if media[index]:
                raise ValueError(f"post {index}: a video post carries no images")
            if has_card:
                raise ValueError(f"post {index}: a post carries one embed, not video and a card")
            if not isinstance(video, str) or not video:
                raise ValueError(f"post {index}: no video path")
            media[index].append(Attachment(post=index, path=Path(video), alt=None, kind="video"))
        if video is None and has_card and media[index]:
            raise ValueError(f"post {index}: a post carries one embed, not images and a card")
        thumb = post.get("card-thumb")
        if thumb is not None:
            if not isinstance(thumb, str) or not thumb:
                raise ValueError(f"post {index}: no card thumbnail path")
            media[index].append(Attachment(post=index, path=Path(thumb), alt=None, kind="thumb"))
        images = [entry for entry in media[index] if entry.kind == "image"]
        if len(images) > MAX_IMAGES_PER_POST:
            raise ValueError(
                f"post {index}: at most {MAX_IMAGES_PER_POST} images, not {len(images)}"
            )
    return media


def _check_card(index: int, post: dict[str, Any]) -> None:
    """A card is a URL with its title and description, or nothing at all."""
    url = post.get("card-url")
    if url is None:
        return
    if not isinstance(url, str) or not url:
        raise ValueError(f"post {index}: no card URL")
    for key in ("card-title", "card-description"):
        value = post.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"post {index}: a card needs its {key} with the URL")


def _post_warnings(
    index: int, text: str, entries: list[Attachment], post: dict[str, Any]
) -> list[str]:
    """What the dry run says about one post without sending anything."""
    warnings: list[str] = []
    if not text:
        raise ValueError(f"post {index}: no text")
    count = richtext.grapheme_count(text)
    if count > richtext.GRAPHEME_LIMIT:
        warnings.append(
            f"post {index} is {count} graphemes, over the {richtext.GRAPHEME_LIMIT} limit"
        )
    for entry in entries:
        warnings.extend(_size_warning(index, entry))
    if post.get("card-url") is not None and post.get("card-thumb") is None:
        warnings.append(f"post {index} card has no thumbnail")
    return warnings


def _size_warning(index: int, entry: Attachment) -> list[str]:
    """The over-limit warning for one upload, empty when it fits."""
    try:
        size = entry.path.stat().st_size
    except OSError:
        raise ValueError(f"post {index}: {entry.path} is not a file") from None
    limit = VIDEO_BLOB_LIMIT if entry.kind == "video" else IMAGE_BLOB_LIMIT
    if size > limit:
        return [f"post {index} {entry.path.name} is {size} bytes, over the {limit} limit"]
    return []


def _check_sizes(index: int, entries: list[Attachment]) -> None:
    """Refuse an upload the network would reject, before anything leaves."""
    for entry in entries:
        try:
            size = entry.path.stat().st_size
        except OSError:
            raise ValueError(f"post {index}: {entry.path} is not a file") from None
        limit = VIDEO_BLOB_LIMIT if entry.kind == "video" else IMAGE_BLOB_LIMIT
        if size > limit:
            raise ValueError(f"post {index}: {entry.path.name} is {size} bytes, over {limit}")


def _created_at() -> str:
    """Now, as a post record stamps it: UTC with milliseconds."""
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _public_url(handle: str, uri: str) -> str:
    """The bsky.app URL of a post URI."""
    return f"https://bsky.app/profile/{handle}/post/{uri.rsplit('/', 1)[-1]}"


def _embed(
    host: str, token: str, entries: list[Attachment], post: dict[str, Any]
) -> dict[str, Any] | None:
    """The record's embed: images, video, or the external link card."""
    images = [entry for entry in entries if entry.kind == "image"]
    videos = [entry for entry in entries if entry.kind == "video"]
    thumbs = [entry for entry in entries if entry.kind == "thumb"]
    if images:
        return {
            "$type": "app.bsky.embed.images",
            "images": [
                {
                    "alt": str(entry.alt),
                    "aspectRatio": _aspect_ratio(entry.path),
                    "image": _upload(host, token, entry),
                }
                for entry in images
            ],
        }
    if videos:
        return {"$type": "app.bsky.embed.video", "video": _upload(host, token, videos[0])}
    url = post.get("card-url")
    if url is not None:
        card: dict[str, Any] = {
            "uri": url,
            "title": post.get("card-title"),
            "description": post.get("card-description"),
        }
        if thumbs:
            card["thumb"] = _upload(host, token, thumbs[0])
        return {"$type": "app.bsky.embed.external", "external": card}
    return None


def _upload(host: str, token: str, entry: Attachment) -> dict[str, Any]:
    """Upload one file; its suffix decides the MIME the blob carries."""
    suffix = entry.path.suffix.lower()
    mime = dict(IMAGE_MIME, **VIDEO_MIME).get(suffix)
    if mime is None:
        raise ValueError(f"post {entry.post}: {entry.path.name} is not a postable file")
    try:
        data = entry.path.read_bytes()
    except OSError:
        raise ValueError(f"post {entry.post}: {entry.path} cannot be read") from None
    return xrpc_client.upload_blob(host, token, entry.path.name, data, mime)


def _aspect_ratio(path: Path) -> dict[str, int] | None:
    """Width and height from a still's own header, else nothing to declare."""
    try:
        with path.open("rb") as handle:
            head = handle.read(64)
    except OSError:
        return None
    size = _still_size(path.suffix.lower(), head)
    if size is None:
        return None
    width, height = size
    return {"width": width, "height": height}


#: A PNG header holds its size once the IHDR chunk opened.
PNG_HEAD_LEN = 24
#: A JPEG starts with its SOI marker; size waits in a start-of-frame one.
JPEG_SOI = b"\xff\xd8"
JPEG_SOF = {0xC0, 0xC1, 0xC2}
#: A JPEG segment names its own length; shorter is corrupt.
MIN_SEGMENT_LEN = 2


def _still_size(suffix: str, head: bytes) -> tuple[int, int] | None:
    """Pixel size of a PNG or JPEG header, without an image library."""
    if suffix == ".png" and len(head) >= PNG_HEAD_LEN and head[12:16] == b"IHDR":
        width = int.from_bytes(head[16:20], "big")
        height = int.from_bytes(head[20:24], "big")
        if width > 0 and height > 0:
            return width, height
    if suffix in {".jpg", ".jpeg"} and head[: len(JPEG_SOI)] == JPEG_SOI:
        return _jpeg_size(head)
    return None


def _jpeg_size(head: bytes) -> tuple[int, int] | None:
    """Pixel size of a JPEG start-of-frame marker in the first bytes."""
    position = len(JPEG_SOI)
    while position + 9 <= len(head):
        if head[position] != JPEG_SOI[0]:
            return None
        marker = head[position + 1]
        if marker in JPEG_SOF:
            height = int.from_bytes(head[position + 5 : position + 7], "big")
            width = int.from_bytes(head[position + 7 : position + 9], "big")
            if width > 0 and height > 0:
                return width, height
            return None
        length = int.from_bytes(head[position + 2 : position + 4], "big")
        if length < MIN_SEGMENT_LEN:
            return None
        position += len(JPEG_SOI) + length
    return None


def _record(
    text: str,
    post: dict[str, Any],
    embed: dict[str, Any] | None,
    resolve: Callable[[str], str | None],
    reply: dict[str, Any] | None,
) -> dict[str, Any]:
    """One post record: text, facets, language, embed and thread reply."""
    record: dict[str, Any] = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": _created_at(),
    }
    facets = richtext.facets_for(text, resolve)
    if facets:
        record["facets"] = facets
    lang = post.get("lang")
    if lang is not None:
        record["langs"] = [lang]
    if embed is not None:
        record["embed"] = embed
    if reply is not None:
        record["reply"] = reply
    return record


@runner.verb("dry-run")
def dry_run(req: Request) -> dict[str, Any]:
    posts = _posts(dict(req.inputs))
    media = _attachments(posts, _image_rows(dict(req.inputs)))
    account = _account()
    rendered = []
    for index, post in enumerate(posts, start=1):
        text = post.get("text")
        if not isinstance(text, str):
            raise ValueError(f"post {index}: no text")
        entries = media[index]
        warnings = _post_warnings(index, text, entries, post)
        rendered.append(
            {
                "text": text,
                "account": account,
                "media": [str(entry.path) for entry in entries],
                "warnings": warnings,
                "cost": None,
            }
        )
    return {"posts": rendered, "warnings": []}


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    posts = _posts(dict(req.inputs))
    media = _attachments(posts, _image_rows(dict(req.inputs)))
    account = _account()
    password = secret("app-password")
    for index, post in enumerate(posts, start=1):
        text = post.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError(f"post {index}: no text")
        if richtext.grapheme_count(text) > richtext.GRAPHEME_LIMIT:
            raise ValueError(f"post {index}: text is over the {richtext.GRAPHEME_LIMIT} limit")
        _check_sizes(index, media[index])
    try:
        session = xrpc_client.create_session(account, password)
        host = xrpc_client.pds_for(str(session.get("did", "")))
        token = str(session["accessJwt"])
        did = str(session["did"])
    except (XrpcError, KeyError) as exc:
        raise ValueError(f"sign-in failed: {exc}") from exc
    resolve = _mention_resolver()
    sent: list[dict[str, str]] = []
    root: dict[str, str] | None = None
    parent: dict[str, str] | None = None
    for index, post in enumerate(posts, start=1):
        reply = None if parent is None else {"root": root, "parent": parent}
        record = _record(
            str(post["text"]),
            post,
            _embed(host, token, media[index], post),
            resolve,
            reply,
        )
        try:
            ref = xrpc_client.create_record(host, token, did, record)
        except XrpcError as exc:
            raise ValueError(f"post {index}: {exc}") from exc
        root = ref if root is None else root
        parent = ref
        sent.append({"id": ref["uri"], "url": _public_url(account, ref["uri"])})
    return {
        "tool": _tool(),
        "post": {
            "network": NETWORK,
            "account": account,
            "state": "published",
            "posts": sent,
            "cost": None,
        },
    }


def _mention_resolver() -> Callable[[str], str | None]:
    """Mention handles to DIDs, cached so one thread resolves each once."""
    cache: dict[str, str | None] = {}

    def resolve(handle: str) -> str | None:
        if handle not in cache:
            try:
                cache[handle] = xrpc_client.resolve_handle(handle)
            except XrpcError:
                cache[handle] = None
        return cache[handle]

    return resolve


def _split_uri(uri: str) -> tuple[str, str, str]:
    """A post ``at://`` URI into its DID, collection and record key."""
    rest = uri.removeprefix("at://")
    did, _, tail = rest.partition("/")
    collection, _, rkey = tail.partition("/")
    if not did or not collection or not rkey:
        raise ValueError(f"{uri}: not a post URI")
    return did, collection, rkey


def _read_images(embed: dict[str, Any]) -> list[dict[str, Any]]:
    """The image entries of an images embed, with the alt text each holds."""
    images = embed.get("images")
    if not isinstance(images, list):
        return []
    return [
        {"file": f"image-{position}.blob", "alt": item.get("alt")}
        for position, item in enumerate(images, start=1)
        if isinstance(item, dict)
    ]


def _read_media(embed: Any) -> list[dict[str, Any]]:
    """The attachments a read-back record holds, images with their alt text."""
    if not isinstance(embed, dict):
        return []
    kind = embed.get("$type")
    if kind == "app.bsky.embed.images":
        return _read_images(embed)
    if kind == "app.bsky.embed.video":
        return [{"file": "video.blob", "alt": None}]
    if kind == "app.bsky.embed.external":
        external = embed.get("external")
        if isinstance(external, dict) and isinstance(external.get("thumb"), dict):
            return [{"file": "card-thumb.blob", "alt": None}]
    if kind == "app.bsky.embed.recordWithMedia":
        return _read_media(embed.get("media"))
    return []


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    refs = req.post.get("posts")
    if not isinstance(refs, list) or not refs:
        raise ValueError("the receipt names no posts")
    expected = req.inputs.get("posts")
    texts: list[str] | None = None
    if isinstance(expected, list) and expected:
        texts = [item.get("text") if isinstance(item, dict) else None for item in expected]
    measured: list[dict[str, Any]] = []
    for index, ref in enumerate(refs, start=1):
        if not isinstance(ref, dict) or not isinstance(ref.get("id"), str):
            raise ValueError(f"post {index}: the receipt names no id")
        uri = str(ref["id"])
        try:
            did, collection, rkey = _split_uri(uri)
            host = xrpc_client.pds_for(did)
            record = xrpc_client.get_record(host, did, collection, rkey)
        except (ValueError, XrpcError) as exc:
            raise ValueError(f"post {index}: {exc}") from exc
        value = record["value"]
        if texts is not None and (index - 1 >= len(texts) or value.get("text") != texts[index - 1]):
            raise ValueError(f"post {index}: the network holds different text")
        measured.extend(_read_media(value.get("embed")))
    return {"state": "published", "media": measured}


def _preview_media(
    entries: list[Attachment],
) -> tuple[list[str], list[dict[str, Any]]]:
    """One post's preview lines: top-level names plus its media table."""
    names: list[str] = []
    media: list[dict[str, Any]] = []
    for entry in entries:
        name = entry.path.name
        names.append(name)
        if entry.kind in {"thumb", "video"}:
            media.append({"file": name, "alt": None})
        else:
            media.append({"file": name, "alt": entry.alt})
    return names, media


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    if not req.assets:
        raise ValueError("preview needs the receipt")
    receipt = json.loads(req.assets[0].read_text(encoding="utf-8"))
    posts = _posts(dict(req.inputs))
    media = _attachments(posts, _image_rows(dict(req.inputs)))
    refs = receipt.get("posts")
    if not isinstance(refs, list) or len(refs) != len(posts):
        raise ValueError("the receipt holds another thread")
    images: list[str] = []
    rendered = []
    for index, (post, ref) in enumerate(zip(posts, refs, strict=True), start=1):
        if not isinstance(ref, dict) or not isinstance(ref.get("url"), str):
            raise ValueError(f"post {index}: the receipt names no url")
        names, entries = _preview_media(media[index])
        images.extend(names)
        rendered.append({"text": str(post["text"]), "url": str(ref["url"]), "media": entries})
    network = receipt.get("network", NETWORK)
    account = receipt.get("account", "")
    state = receipt.get("state", "published")
    count = len(posts)
    noun = "post" if count == 1 else "posts"
    summary = f"{count} {noun} on {network} as {account}, {state}"[:160]
    data = {
        "preview": 1,
        "kind": "post",
        "summary": summary,
        "network": network,
        "account": account,
        "state": state,
        "images": images,
        "posts": rendered,
    }
    name = f"{req.assets[0].name}.preview.json"
    (req.out_dir / name).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
    return {"assets": [{"file": name}]}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names what fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_imports() -> dict[str, Any]:
    """The vendored client and the facet counter answer their own smoke test."""
    if richtext.grapheme_count("hola") != len("hola"):
        return _check("imports", False, "richtext counts wrong", "facet pull bluesky")
    if not callable(xrpc_client.create_session):
        return _check("imports", False, "the XRPC client is missing", "facet pull bluesky")
    return _check("imports", True, "client and richtext answer")


def _missing_secret(name: str) -> str | None:
    """The secret's absence as its fix, or nothing when it is stored."""
    try:
        secret(name)
    except KeyError as exc:
        return str(exc)
    return None


def _doctor_secrets() -> list[dict[str, Any]]:
    """Both credentials are stored; a value never appears in a detail."""
    checks = []
    for name in ("handle", "app-password"):
        missing = _missing_secret(name)
        if missing is None:
            checks.append(_check(name, True, f"{name} is stored"))
        else:
            checks.append(_check(name, False, f"{name} is not stored", missing))
    return checks


def _doctor_session() -> dict[str, Any]:
    """Sign in with the stored credentials and name the account they open."""
    try:
        handle = secret("handle")
        password = secret("app-password")
    except KeyError as exc:
        return _check("session", False, str(exc), str(exc))
    try:
        session = xrpc_client.create_session(handle, password)
        profile = xrpc_client.get_profile(xrpc_client.APPVIEW_HOST, str(session.get("did", handle)))
    except XrpcError as exc:
        return _check(
            "session",
            False,
            f"sign-in failed: {exc}",
            "check the handle, then create a new app password and run "
            "facet secret set bluesky app-password",
        )
    name = profile.get("displayName") or profile.get("handle") or handle
    return _check("session", True, f"signed in as {profile.get('handle', handle)} ({name})")


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_imports(), *_doctor_secrets()]
    if req.depth == "full":
        checks.append(_doctor_session())
    return {"checks": checks}


runner.main()
