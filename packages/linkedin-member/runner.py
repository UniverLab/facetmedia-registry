"""The linkedin-member package runner: post to the owner's personal LinkedIn profile.

Six verbs on the runner SDK. ``dry-run`` sends nothing: it checks the text
against LinkedIn's 3 000-character limit and every image against the
MultiImage rules (JPG, GIF or PNG, at most 36 152 320 pixels each, at most
20 riding one post), and shows what will land on the personal profile.
``run`` uploads each image as an asset owned by ``urn:li:person:{member-id}``,
creates one post with text only, one image or a MultiImage body, then reads
it back; if the read-back succeeds the receipt state is ``published``, and if
LinkedIn refuses the read-back as forbidden the receipt keeps the URN and
public URL with state ``unknown`` and a warning. ``verify`` reads the created
post back and passes when LinkedIn returns it with matching text and media
count, or reports ``unknown`` with a warning when read-back is forbidden.
``preview`` writes the post schema's preview beside the receipt. ``doctor``
checks the stored secrets (with ``refresh-token`` optional) at ``quick`` and
reads ``/v2/userinfo`` at ``full``. ``auth`` runs the OAuth sign-in and
stores ``access-token``, ``member-id`` and optional ``refresh-token``.
"""

from __future__ import annotations

import json
import struct
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import linkedin_member_client
from facet_runner_sdk import Request, Runner, renew_secret, secret
from linkedin_member_client import LinkedInError

runner = Runner()

#: The network this package posts to, as receipts and previews name it.
NETWORK = "linkedin-member"
#: The image containers LinkedIn's upload takes.
IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
}
#: At most twenty images ride one post; the twenty-first is refused.
MAX_IMAGES = 20
#: The MultiImage pixel cap: images above it never leave the machine.
PIXEL_LIMIT = 36152320
#: The longest commentary LinkedIn's post takes.
TEXT_LIMIT = 3000
#: What the dry run names as the account: it sends nothing, so it reads none.
UNREAD_ACCOUNT = "@not-read"
#: The fragment LinkedIn answers when the grant misses a scope.
ACCESS_DENIED_MARK = linkedin_member_client.ACCESS_DENIED
#: The fragment LinkedIn answers when the token expired.
TOKEN_MARK = linkedin_member_client.TOKEN_EXPIRED
#: An accepted post is public at once: LinkedIn keeps no drafts.
NO_DRAFTS = "accepted posts are public at once: LinkedIn keeps no drafts"
#: An upload with at least two images rides a MultiImage post.
MULTI_MIN = 2
#: The shortest byte runs that still hold PNG, GIF and JPEG dims.
PNG_MIN = 33
GIF_MIN = 10
JPEG_MIN = 4
#: The byte opening every JPEG marker.
JPEG_PREFIX = 0xFF
#: The markers opening a start-of-frame segment with the pixel size.
JPEG_SOF = (0xC0, 0xC1, 0xC2)
#: The markers without a length field: standalone plus the RST0-RST7 run.
JPEG_LENGTHLESS = (0xD8, 0xD9, 0x01, *range(0xD0, 0xD8))
#: A real upload is never retried over an existing receipt.
NO_RESEND = "never re-send a receipt: a second send posts a duplicate"
#: Actionable message when the token expired and no refresh-token is stored.
REAUTH_MSG = (
    "the access token expired and no refresh-token is stored; "
    "run facet auth logout linkedin-member then facet auth login linkedin-member"
)


@dataclass(frozen=True)
class Image:
    """One image of the piece: its file and the alt text it rides with."""

    path: Path
    alt: str


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _inputs(req: Request) -> dict[str, Any]:
    """The piece's inputs as a plain map."""
    return dict(req.inputs)


def _text(inputs: Mapping[str, Any]) -> str:
    """The post's commentary; a piece without one is refused."""
    text = inputs.get("text")
    if not isinstance(text, str) or not text:
        raise ValueError("the piece has no text")
    return text


def _images(req: Request, inputs: Mapping[str, Any]) -> list[Image]:
    """The piece's images, resolved relative to the piece, at most twenty."""
    value = inputs.get("images", [])
    if not isinstance(value, list):
        raise ValueError("the piece's images are not a list")
    found: list[Image] = []
    for position, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"images[{position}]: no image entry")
        path = item.get("path")
        alt = item.get("alt")
        if not isinstance(path, str) or not path:
            raise ValueError(f"images[{position}]: no image path")
        if not isinstance(alt, str) or not alt:
            raise ValueError(f"images[{position}]: an image without alt text is refused")
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = req.piece_dir / resolved
        found.append(Image(path=resolved, alt=alt))
    if len(found) > MAX_IMAGES:
        raise ValueError(f"the piece carries {len(found)} images, over the {MAX_IMAGES} limit")
    return found


def _png_size(data: bytes) -> tuple[int, int] | None:
    """The pixel size of a PNG from its IHDR chunk, or nothing unreadable."""
    if len(data) < PNG_MIN or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return (width, height) if width > 0 and height > 0 else None


def _gif_size(data: bytes) -> tuple[int, int] | None:
    """The pixel size of a GIF from its screen descriptor, or nothing unreadable."""
    if len(data) < GIF_MIN or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return (width, height) if width > 0 and height > 0 else None


def _jpeg_frame(data: bytes, cursor: int) -> tuple[int, int] | None:
    """The pixel size of a JPEG once the cursor reaches its SOF marker."""
    while cursor + 9 <= len(data):
        if data[cursor] != JPEG_PREFIX:
            cursor += 1
            continue
        marker = data[cursor + 1]
        if marker in JPEG_SOF:
            height, width = struct.unpack(">HH", data[cursor + 5 : cursor + 9])
            return (width, height) if width > 0 and height > 0 else None
        if marker in JPEG_LENGTHLESS:
            cursor += 2
        else:
            if cursor + 4 > len(data):
                return None
            cursor += 2 + struct.unpack(">H", data[cursor + 2 : cursor + 4])[0]
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """The pixel size of a JPEG from its frame header, or nothing unreadable."""
    if len(data) < JPEG_MIN or data[:2] != b"\xff\xd8":
        return None
    return _jpeg_frame(data, 2)


def _pixels(path: Path) -> int | None:
    """The image's pixel count, or nothing when its dims cannot be read."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    suffix = path.suffix.lower()
    if suffix == ".png":
        size = _png_size(data)
    elif suffix == ".gif":
        size = _gif_size(data)
    else:
        size = _jpeg_size(data)
    if size is None:
        return None
    return size[0] * size[1]


def _check_files(images: list[Image]) -> None:
    """Refuse an upload LinkedIn would reject, before anything leaves."""
    for image in images:
        suffix = image.path.suffix.lower()
        if suffix not in IMAGE_MIME:
            raise ValueError(f"{image.path.name} is not a JPG, GIF or PNG image")
        if not image.path.is_file():
            raise ValueError(f"{image.path} is not a file")
        pixels = _pixels(image.path)
        if pixels is not None and pixels >= PIXEL_LIMIT:
            raise ValueError(f"{image.path.name} is {pixels} pixels, over the {PIXEL_LIMIT} limit")


def _image_warnings(images: list[Image]) -> list[str]:
    """What the dry run says about the images without sending anything."""
    warnings: list[str] = []
    for image in images:
        if image.path.suffix.lower() not in IMAGE_MIME:
            raise ValueError(f"{image.path.name} is not a JPG, GIF or PNG image")
        if not image.path.is_file():
            raise ValueError(f"{image.path} is not a file")
        pixels = _pixels(image.path)
        if pixels is None:
            warnings.append(f"{image.path.name}: its size could not be read")
        elif pixels >= PIXEL_LIMIT:
            warnings.append(f"{image.path.name} is {pixels} pixels, over the {PIXEL_LIMIT} limit")
    if len(images) >= MULTI_MIN:
        warnings.append(f"{len(images)} images ride one MultiImage post")
    return warnings


def _forbidden(exc: LinkedInError) -> bool:
    """Whether LinkedIn refused the call for missing permissions or scope."""
    return exc.status == HTTPStatus.FORBIDDEN or ACCESS_DENIED_MARK in exc.error


def _expired(exc: LinkedInError) -> bool:
    """Whether the token expired, as opposed to missing a granted scope."""
    if _forbidden(exc):
        return False
    return exc.status == HTTPStatus.UNAUTHORIZED or TOKEN_MARK in exc.error


def _stored(name: str) -> str:
    """One stored secret; a missing one names the sign-in that stores it."""
    try:
        return secret(name)
    except KeyError as exc:
        raise ValueError(str(exc)) from exc


def _optional_secret(name: str) -> str | None:
    """An optional stored secret, or None when absent."""
    try:
        value = secret(name)
    except KeyError:
        return None
    return value or None


def _refresh() -> str:
    """Trade the stored refresh token for fresh tokens, or instruct re-login."""
    refresh_token = _optional_secret("refresh-token")
    if not refresh_token:
        raise ValueError(REAUTH_MSG)
    client_id = _stored("client-id")
    client_secret = _stored("client-secret")
    try:
        tokens = linkedin_member_client.refresh_tokens(client_id, client_secret, refresh_token)
    except LinkedInError as exc:
        raise ValueError(f"the token refresh failed: {exc}") from exc
    renew_secret("access-token", tokens.access_token)
    if tokens.refresh_token:
        renew_secret("refresh-token", tokens.refresh_token)
    return tokens.access_token


def _with_token(action: Callable[[str], Any], access: str | None = None) -> tuple[Any, str]:
    """Run ``action`` with a working token, refreshing once on expiry."""
    token = access if access is not None else _stored("access-token")
    try:
        return action(token), token
    except LinkedInError as exc:
        if not _expired(exc):
            raise ValueError(f"LinkedIn refused: {exc}") from exc
    fresh = _refresh()
    try:
        return action(fresh), fresh
    except LinkedInError as exc:
        raise ValueError(f"LinkedIn refused: {exc}") from exc


def _account(member_id: str) -> tuple[str, str]:
    """The member's display name and a working token, refreshing once."""
    try:
        member, access = _with_token(linkedin_member_client.userinfo)
    except ValueError as exc:
        if REAUTH_MSG in str(exc):
            raise
        raise ValueError(f"the member could not be read: {exc}") from exc
    if not isinstance(member, dict):
        return f"person:{member_id}", access
    name = member.get("name")
    if isinstance(name, str) and name:
        return name, access
    return f"person:{member_id}", access


def _public_url(post_id: str) -> str:
    """The feed URL of a Post ID."""
    return f"https://www.linkedin.com/feed/update/{post_id}"


@runner.verb("dry-run")
def dry_run(req: Request) -> dict[str, Any]:
    inputs = _inputs(req)
    text = _text(inputs)
    images = _images(req, inputs)
    warnings = _image_warnings(images)
    if len(text) > TEXT_LIMIT:
        warnings.insert(0, f"the text is {len(text)} characters, over the {TEXT_LIMIT} limit")
    member_id = _optional_secret("member-id")
    who = f"urn:li:person:{member_id}" if member_id else "the signed-in member's personal profile"
    rendered = {
        "text": text,
        "account": UNREAD_ACCOUNT,
        "media": [str(image.path) for image in images],
        "warnings": warnings,
        "cost": None,
    }
    group = [
        f"publishes as {who} on the owner's personal LinkedIn profile as PUBLIC",
        NO_DRAFTS,
        NO_RESEND,
    ]
    return {"posts": [rendered], "warnings": group}


def _upload(images: list[Image], access: str, author: str) -> tuple[list[tuple[str, str]], str]:
    """Upload every image as an asset; answer each URN with its alt text."""
    uploaded: list[tuple[str, str]] = []
    token = access
    for image in images:
        try:
            data = image.path.read_bytes()
        except OSError:
            raise ValueError(f"{image.path} cannot be read") from None
        try:
            (upload_url, urn), token = _with_token(
                lambda tok: linkedin_member_client.init_image_upload(tok, author),
                access=token,
            )
            mime = IMAGE_MIME[image.path.suffix.lower()]
            linkedin_member_client.upload_image(upload_url, mime, data)
        except LinkedInError as exc:
            raise ValueError(f"the image upload failed: {exc}") from exc
        except ValueError as exc:
            if REAUTH_MSG in str(exc):
                raise
            raise ValueError(f"the image upload failed: {exc}") from exc
        uploaded.append((urn, image.alt))
    return uploaded, token


def _post_body(author: str, text: str, uploaded: list[tuple[str, str]]) -> dict[str, Any]:
    """The Posts API body: text only, one image, or a MultiImage post."""
    body: dict[str, Any] = {
        "author": author,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if len(uploaded) == 1:
        urn, alt = uploaded[0]
        body["content"] = {"media": {"id": urn, "title": alt}}
    elif len(uploaded) >= MULTI_MIN:
        body["content"] = {
            "multiImage": {"images": [{"id": urn, "altText": alt} for urn, alt in uploaded]}
        }
    return body


def _read_back_after_create(access: str, post_id: str) -> tuple[str, list[str]]:
    """Read back a newly created post; forbidden read-back yields unknown + warning."""
    try:
        _with_token(lambda tok: linkedin_member_client.get_post(tok, post_id), access=access)
        return "published", []
    except ValueError as exc:
        detail = str(exc)
        if REAUTH_MSG in detail or "token refresh failed" in detail:
            raise
        if "403" in detail or ACCESS_DENIED_MARK in detail or "status 403" in detail:
            return (
                "unknown",
                [f"read-back forbidden ({detail}): post {post_id} was created, state is unknown"],
            )
        raise ValueError(f"the post read-back failed: {detail}") from exc


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    inputs = _inputs(req)
    text = _text(inputs)
    if len(text) > TEXT_LIMIT:
        raise ValueError(f"the text is {len(text)} characters, over the {TEXT_LIMIT} limit")
    images = _images(req, inputs)
    _check_files(images)
    member_id = _stored("member-id")
    author = f"urn:li:person:{member_id}"
    account, access = _account(member_id)
    uploaded, access = _upload(images, access, author)
    try:
        post_id, access = _with_token(
            lambda tok: linkedin_member_client.create_post(tok, _post_body(author, text, uploaded)),
            access=access,
        )
    except ValueError as exc:
        if REAUTH_MSG in str(exc):
            raise
        raise ValueError(f"the post was refused: {exc}") from exc
    state, warnings = _read_back_after_create(access, post_id)
    post: dict[str, Any] = {
        "network": NETWORK,
        "account": account,
        "state": state,
        "posts": [{"id": post_id, "url": _public_url(post_id)}],
        "cost": None,
    }
    if warnings:
        post["warnings"] = warnings
    return {"tool": _tool(), "post": post}


def _media_count(post: Mapping[str, Any]) -> int:
    """How many images the post read back carries."""
    content = post.get("content")
    if not isinstance(content, dict):
        return 0
    multi = content.get("multiImage")
    if isinstance(multi, dict) and isinstance(multi.get("images"), list):
        return len(multi["images"])
    media = content.get("media")
    if isinstance(media, dict) and isinstance(media.get("id"), str):
        return 1
    return 0


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    refs = req.post.get("posts")
    if not isinstance(refs, list) or not refs:
        raise ValueError("the receipt names no posts")
    first = refs[0]
    if not isinstance(first, dict) or not isinstance(first.get("id"), str):
        raise ValueError("the receipt names no Post ID")
    post_id = str(first["id"])
    inputs = _inputs(req)
    images = _images(req, inputs)
    try:
        outcome, _ = _with_token(lambda token: linkedin_member_client.get_post(token, post_id))
    except ValueError as exc:
        detail = str(exc)
        if "403" in detail or ACCESS_DENIED_MARK in detail or "status 403" in detail:
            return {
                "state": "unknown",
                "media": [{"file": image.path.name, "alt": image.alt} for image in images],
                "warnings": [f"read-back forbidden ({detail}): post {post_id} state is unknown"],
            }
        raise
    if not isinstance(outcome, dict):
        raise ValueError("the post read back no record")
    if outcome.get("commentary") != _text(inputs):
        raise ValueError("the post read back another text")
    if _media_count(outcome) != len(images):
        raise ValueError("the post read back another media count")
    return {
        "state": "published",
        "media": [{"file": image.path.name, "alt": image.alt} for image in images],
    }


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    if not req.assets:
        raise ValueError("preview needs the receipt")
    receipt = json.loads(req.assets[0].read_text(encoding="utf-8"))
    inputs = _inputs(req)
    text = _text(inputs)
    refs = receipt.get("posts")
    if not isinstance(refs, list) or not refs or not isinstance(refs[0], dict):
        raise ValueError("the receipt holds no post")
    url = refs[0].get("url")
    if not isinstance(url, str):
        raise ValueError("the receipt names no url")
    images = _images(req, inputs)
    network = str(receipt.get("network", NETWORK))
    account = str(receipt.get("account", ""))
    state = str(receipt.get("state", "published"))
    summary = (
        f"post on {network} as {account} ({state}), public on personal profile: {NO_DRAFTS}"
    )[:160]
    data = {
        "preview": 1,
        "kind": "post",
        "summary": summary,
        "network": network,
        "account": account,
        "state": state,
        "images": [image.path.name for image in images],
        "posts": [
            {
                "text": text,
                "url": url,
                "media": [{"file": image.path.name, "alt": image.alt} for image in images],
            }
        ],
    }
    name = f"{req.assets[0].name}.preview.json"
    (req.out_dir / name).write_text(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
    return {"assets": [{"file": name}]}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names what fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_imports() -> dict[str, Any]:
    """The vendored client answers its own smoke test."""
    if not callable(linkedin_member_client.get_post):
        return _check(
            "imports", False, "the LinkedIn Member client is missing", "facet pull linkedin-member"
        )
    return _check("imports", True, "client answers")


def _doctor_secrets() -> list[dict[str, Any]]:
    """Required secrets are stored; refresh-token is optional."""
    checks = []
    for name in ("client-id", "client-secret", "access-token", "member-id"):
        try:
            secret(name)
        except KeyError as exc:
            checks.append(_check(name, False, f"{name} is not stored", str(exc)))
        else:
            checks.append(_check(name, True, f"{name} is stored"))
    if _optional_secret("refresh-token") is not None:
        checks.append(_check("refresh-token", True, "refresh-token is stored"))
    else:
        checks.append(
            _check(
                "refresh-token",
                True,
                "refresh-token is not stored (optional; self-serve apps may not receive one)",
            )
        )
    return checks


def _doctor_session() -> dict[str, Any]:
    """Read /v2/userinfo and report the signed-in member's name."""
    try:
        member, _ = _with_token(linkedin_member_client.userinfo)
    except ValueError as exc:
        return _check("session", False, str(exc), "facet auth login linkedin-member")
    if not isinstance(member, dict):
        return _check(
            "session", False, "the member read no record", "facet auth login linkedin-member"
        )
    who = member.get("name") or member.get("sub") or ""
    if not who:
        return _check(
            "session",
            False,
            "the member record has no name or sub",
            "facet auth login linkedin-member",
        )
    return _check(
        "session",
        True,
        f"signed in as {who} (personal profile with openid, profile and w_member_social)",
    )


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_imports(), *_doctor_secrets()]
    if req.depth == "full":
        checks.append(_doctor_session())
    return {"checks": checks}


@runner.verb("auth")
def auth(req: Request) -> dict[str, Any]:
    client_id = _stored("client-id")
    client_secret = _stored("client-secret")
    redirect = req.inputs.get("redirect-uri")
    if redirect is not None and (not isinstance(redirect, str) or not redirect):
        raise ValueError("the redirect URI is not a URI")
    uri = str(redirect) if isinstance(redirect, str) else "http://localhost:8080/callback"
    try:
        stored = linkedin_member_client.authorize(client_id, client_secret, uri)
    except LinkedInError as exc:
        raise ValueError(str(exc)) from exc
    return {"secrets": stored}


runner.main()
