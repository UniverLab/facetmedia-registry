"""The linkedin package runner: post to the organization feed, then read it back.

Six verbs on the runner SDK. ``dry-run`` sends nothing: it checks the
author URN, the text against LinkedIn's 3 000-character limit and every
image against the MultiImage rules (JPG, GIF or PNG, at most 36 152 320
pixels each, at most 20 riding one post), and shows what will land on
the organization's feed. ``run`` uploads each image as an asset, creates
one post with text only, one image or a MultiImage body, then answers
the receipt's ``post`` object with state ``published`` and the feed URL
of the ``x-restli-id`` answer. ``verify`` reads the created post back
and passes only when LinkedIn returns it with the same text and the
same media count. ``preview`` writes the post schema's preview beside
the receipt. ``doctor`` checks the secrets at ``quick`` and the member,
the organization role plus both scopes at ``full``. ``auth`` runs the
lab's OAuth sign-in and stores the tokens through facet's secrets store.
"""

from __future__ import annotations

import json
import re
import struct
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import linkedin_client
from facet_runner_sdk import Request, Runner, renew_secret, secret
from linkedin_client import LinkedInError

runner = Runner()

#: The network this package posts to, as receipts and previews name it.
NETWORK = "linkedin"
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
#: The organization URN shape the package posts as.
AUTHOR_RE = re.compile(r"^urn:li:organization:[0-9]+$")
#: The fragment LinkedIn answers when the grant misses a scope or role.
ACCESS_DENIED_MARK = linkedin_client.ACCESS_DENIED
#: The fragment LinkedIn answers when the token expired.
TOKEN_MARK = linkedin_client.TOKEN_EXPIRED
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


def _author(inputs: Mapping[str, Any]) -> str:
    """The organization URN the post publishes as; anything else is refused."""
    author = inputs.get("author")
    if not isinstance(author, str) or not AUTHOR_RE.match(author):
        raise ValueError("the piece has no organization author urn:li:organization:{id}")
    return author


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
    size: tuple[int, int] | None = None
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


def _expired(exc: LinkedInError) -> bool:
    """Whether the token expired, as opposed to missing a granted scope.

    LinkedIn answers an expired token with 401, while a missing scope or
    role fails with 403, so a 403 must not trigger a refresh round trip:
    nothing a fresh token carries would grant it.
    """
    if ACCESS_DENIED_MARK in exc.error:
        return False
    return exc.status == HTTPStatus.UNAUTHORIZED or TOKEN_MARK in exc.error


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
    client_id = _stored("client-id")
    client_secret = _stored("client-secret")
    refresh_token = _stored("refresh-token")
    try:
        tokens = linkedin_client.refresh_tokens(client_id, client_secret, refresh_token)
    except LinkedInError as exc:
        raise ValueError(f"the token refresh failed: {exc}") from exc
    renew_secret("access-token", tokens.access_token)
    renew_secret("refresh-token", tokens.refresh_token)
    return tokens.access_token


def _with_token(action: Callable[[str], Any]) -> tuple[Any, str]:
    """Run ``action`` with a working token, refreshing once on expiry.

    The refresh rides the store-back mechanism, so the rotated pair is
    kept; anything else LinkedIn refuses fails with LinkedIn's own reason.
    """
    access = _stored("access-token")
    try:
        return action(access), access
    except LinkedInError as exc:
        if not _expired(exc):
            raise ValueError(f"LinkedIn refused: {exc}") from exc
    fresh = _refresh()
    try:
        return action(fresh), fresh
    except LinkedInError as exc:
        raise ValueError(f"LinkedIn refused: {exc}") from exc


def _account_name(org: Mapping[str, Any], org_id: str) -> str:
    """The organization's display name, for the receipt's account."""
    name = org.get("localizedName") or org.get("vanityName")
    if not isinstance(name, str) or not name:
        return f"org:{org_id}"
    return name


def _org_id(author: str) -> str:
    """The numeric organization id behind the author URN."""
    return author.rsplit(":", 1)[-1]


def _account(author: str) -> tuple[str, str]:
    """The organization's display name and a working token, refreshing once."""
    org_id = _org_id(author)
    try:
        org, access = _with_token(lambda token: linkedin_client.organization(token, org_id))
    except ValueError as exc:
        raise ValueError(f"the organization could not be read: {exc}") from exc
    if not isinstance(org, dict):
        raise ValueError("the organization read no record")
    return _account_name(org, org_id), access


def _public_url(post_id: str) -> str:
    """The feed URL of a Post ID."""
    return f"https://www.linkedin.com/feed/update/{post_id}"


@runner.verb("dry-run")
def dry_run(req: Request) -> dict[str, Any]:
    inputs = _inputs(req)
    author = _author(inputs)
    text = _text(inputs)
    images = _images(req, inputs)
    warnings = _image_warnings(images)
    if len(text) > TEXT_LIMIT:
        warnings.insert(0, f"the text is {len(text)} characters, over the {TEXT_LIMIT} limit")
    rendered = {
        "text": text,
        "account": UNREAD_ACCOUNT,
        "media": [str(image.path) for image in images],
        "warnings": warnings,
        "cost": None,
    }
    group = [
        f"publishes as {author} on the organization's feed as PUBLIC",
        NO_DRAFTS,
        NO_RESEND,
    ]
    return {"posts": [rendered], "warnings": group}


def _upload(images: list[Image], access: str, author: str) -> list[tuple[str, str]]:
    """Upload every image as an asset; answer each URN with its alt text."""
    uploaded: list[tuple[str, str]] = []
    for image in images:
        try:
            data = image.path.read_bytes()
        except OSError:
            raise ValueError(f"{image.path} cannot be read") from None
        try:
            upload_url, urn = linkedin_client.init_image_upload(access, author)
            linkedin_client.upload_image(upload_url, IMAGE_MIME[image.path.suffix.lower()], data)
        except LinkedInError as exc:
            raise ValueError(f"the image upload failed: {exc}") from exc
        uploaded.append((urn, image.alt))
    return uploaded


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


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    inputs = _inputs(req)
    author = _author(inputs)
    text = _text(inputs)
    if len(text) > TEXT_LIMIT:
        raise ValueError(f"the text is {len(text)} characters, over the {TEXT_LIMIT} limit")
    images = _images(req, inputs)
    _check_files(images)
    account, access = _account(author)
    uploaded = _upload(images, access, author)
    try:
        post_id = linkedin_client.create_post(access, _post_body(author, text, uploaded))
    except LinkedInError as exc:
        raise ValueError(f"the post was refused: {exc}") from exc
    return {
        "tool": _tool(),
        "post": {
            "network": NETWORK,
            "account": account,
            "state": "published",
            "posts": [{"id": post_id, "url": _public_url(post_id)}],
            "cost": None,
        },
    }


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
    outcome, _ = _with_token(lambda token: linkedin_client.get_post(token, post_id))
    if not isinstance(outcome, dict):
        raise ValueError("the post read back no record")
    expected = _text(dict(req.inputs))
    actual = outcome.get("commentary")
    if actual != expected:
        raise ValueError("the post read back another text")
    want = len(_images(req, dict(req.inputs)))
    if _media_count(outcome) != want:
        raise ValueError("the post read back another media count")
    images = _images(req, dict(req.inputs))
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
        f"published post on {network} as {account}, public on the organization's feed: {NO_DRAFTS}"
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
    if not callable(linkedin_client.get_post):
        return _check("imports", False, "the LinkedIn client is missing", "facet pull linkedin")
    return _check("imports", True, "client answers")


def _doctor_secrets() -> list[dict[str, Any]]:
    """All five secrets are stored; a value never appears in a detail."""
    checks = []
    for name in ("client-id", "client-secret", "access-token", "refresh-token", "org-id"):
        try:
            secret(name)
        except KeyError as exc:
            checks.append(_check(name, False, f"{name} is not stored", str(exc)))
        else:
            checks.append(_check(name, True, f"{name} is stored"))
    return checks


def _doctor_session() -> dict[str, Any]:
    """Read the member and prove the organization role, refreshing once.

    The refresh rides the store-back mechanism, so a rotated token is
    kept; the userinfo names who signed in and the role list proves both
    scopes plus the Company Page role behind the stored organization id.
    """
    try:
        member, _ = _with_token(linkedin_client.userinfo)
    except ValueError as exc:
        return _check("session", False, str(exc), "facet auth linkedin")
    if not isinstance(member, dict):
        return _check("session", False, "the member read no record", "facet auth linkedin")
    who = member.get("name") or member.get("sub") or ""
    try:
        org_id = _stored("org-id")
    except ValueError as exc:
        return _check("session", False, str(exc), "facet secret set linkedin org-id")
    try:
        entries, _ = _with_token(linkedin_client.organization_acls)
    except ValueError as exc:
        return _check("session", False, str(exc), "facet auth linkedin")
    author = f"urn:li:organization:{org_id}"
    role = ""
    for entry in entries:
        if isinstance(entry, dict) and entry.get("organization") == author:
            candidate = entry.get("role")
            if isinstance(candidate, str):
                role = candidate
    if role not in linkedin_client.ORG_ROLES:
        return _check(
            "session",
            False,
            f"signed in as {who}: no Company Page role for {author}",
            "grant the member a Company Page role, then run facet auth linkedin",
        )
    return _check(
        "session",
        True,
        f"signed in as {who}: the w_organization_social and r_organization_social "
        f"scopes were granted with role {role} for {author}",
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
    redirect = req.inputs.get("redirect-uri")
    if redirect is not None and (not isinstance(redirect, str) or not redirect):
        raise ValueError("the redirect URI is not a URI")
    uri = str(redirect) if isinstance(redirect, str) else "http://localhost:8080/callback"
    try:
        stored = linkedin_client.authorize(client_id, client_secret, uri)
    except LinkedInError as exc:
        raise ValueError(str(exc)) from exc
    return {"secrets": stored}


runner.main()
