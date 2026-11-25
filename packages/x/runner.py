"""The x package runner: post a thread with its cost up front, then read it back.

Six verbs on the runner SDK. ``auth`` runs the lab's OAuth 2.0 sign-in
through the browser and stores the token pair through facet's secrets
store. ``dry-run`` sends nothing: it renders every
post, counts its weighted length the way X does (a URL counts as a fixed
length from the bundled rates, emoji and CJK twice), prices every post,
the read-back and the account read from those rates and shows them item by
item with the date the rates were read. ``run`` uploads the media, posts in
order with each later post replying to the previous one, and answers the
receipt's ``post`` object with the cost it computed. ``verify`` reads every
receipt post back through the account's own read and checks its text and
its media count. ``preview`` writes the post schema's preview file beside
the receipt. ``doctor`` checks the secrets at ``quick`` and the account,
its write access and the cost of the read-back at ``full``.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import x_client
from facet_runner_sdk import Request, Runner, announce_url, renew_secret, secret
from x_client import XError

runner = Runner()

#: The network this package posts to, as receipts and previews name it.
NETWORK = "x"
#: At most four images ride one post; one video or GIF rides alone instead.
MAX_IMAGES_PER_POST = 4
#: A photo upload carries at most five megabytes; the network refuses more.
IMAGE_UPLOAD_LIMIT = 5 * 1024 * 1024
#: An animated GIF carries at most fifteen megabytes.
GIF_UPLOAD_LIMIT = 15 * 1024 * 1024
#: A video post is refused past this many bytes before it uploads.
VIDEO_UPLOAD_LIMIT = 512 * 1024 * 1024
#: A post holds at most 280 weighted characters.
WEIGHT_LIMIT = 280
#: The t.co fixed length X counts for every URL, read 2026-11-17.
TCO_LENGTH = 23
#: What the dry run names as the account: it sends nothing, so it reads none.
UNREAD_ACCOUNT = "@not-read"
#: The weighted count's single-weight ranges, from X's counting rules.
SINGLE_WEIGHT_MAX = 0x10FF
SINGLE_WEIGHT_RANGES = ((0x2000, 0x200D), (0x2010, 0x2017), (0x2032, 0x2037))
#: What X draws as one emoji: a sequence of these counts as two.
EMOJI_RANGES = ((0x1F1E6, 0x1F1FF), (0x1F300, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF))
EMOJI_MODIFIERS = (0x1F3FB, 0x1F3FF)
ZERO_WIDTH_JOINER = "\u200d"
VARIATION_SELECTOR_16 = "\ufe0f"
KEYCAP = "\u20e3"
IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
#: What fixes a token that may not write: the sign-in grants the scopes again.
WRITE_FIX = (
    "check the app's User authentication settings grant the posting scopes, "
    "then run facet auth logout x and facet auth login x"
)
#: What fixes a refresh that fails: the stored pair is spent, so sign in again.
REFRESH_FIX = "run facet auth logout x then facet auth login x"


@dataclass(frozen=True)
class Rates:
    """The dated per-request prices this run charges against."""

    date: str
    currency: str
    post_no_url: float
    post_with_url: float
    read_post: float
    read_user: float
    url_length: int


@dataclass(frozen=True)
class Attachment:
    """One upload of a post: an image, its video, or its GIF."""

    post: int
    path: Path
    alt: str | None
    kind: str


def _rates() -> Rates:
    """The bundled per-request prices, with the date they were read."""
    data = json.loads((Path(__file__).parent / "rates.json").read_text(encoding="utf-8"))
    return Rates(
        date=str(data["date"]),
        currency=str(data["currency"]),
        post_no_url=float(data["post_no_url"]),
        post_with_url=float(data["post_with_url"]),
        read_post=float(data["read_post"]),
        read_user=float(data["read_user"]),
        url_length=int(data["url_length"]),
    )


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _stored(name: str) -> str:
    """One stored secret; a missing one names the sign-in that stores it."""
    try:
        return secret(name)
    except KeyError as exc:
        raise ValueError(str(exc)) from exc


def _credentials() -> tuple[str, str]:
    """The developer app's OAuth 2.0 client ID and secret."""
    return _stored("client-id"), _stored("client-secret")


def _refresh() -> str:
    """Trade the stored refresh token for a fresh pair, kept via store-back.

    Both renewed tokens ride facet's store-back mechanism at once, so a
    rotated token is kept even when the verb fails later; a renewed token
    never lives only in this process's memory.
    """
    client_id, client_secret = _credentials()
    refresh_token = _stored("refresh-token")
    try:
        tokens = x_client.refresh_tokens(client_id, client_secret, refresh_token)
    except XError as exc:
        raise ValueError(f"the token refresh failed: {exc}; {REFRESH_FIX}") from exc
    renew_secret("access-token", tokens.access_token)
    if tokens.refresh_token:
        renew_secret("refresh-token", tokens.refresh_token)
    return tokens.access_token


def _with_token(action: Callable[[str], Any]) -> tuple[Any, str]:
    """Run ``action`` with a working token, refreshing once on a 401.

    The refresh rides the store-back mechanism before the first request,
    so every verb starts from a fresh pair; a 401 refreshes once more and
    retries once, and anything else X refuses fails with X's own reason.
    """
    access = _refresh()
    try:
        return action(access), access
    except XError as exc:
        if exc.status != HTTPStatus.UNAUTHORIZED:
            raise ValueError(f"X refused: {exc}") from exc
    fresh = _refresh()
    try:
        return action(fresh), fresh
    except XError as exc:
        raise ValueError(f"X refused: {exc}") from exc


def _send(action: Callable[[str], Any], token: str) -> tuple[Any, str]:
    """One request with the current token; a 401 refreshes once and retries once.

    The verb already refreshed before its first request, so no refresh is
    spent up front here: a 401 means the token died mid-verb, and only then
    is the stored refresh token traded once and the one request replayed.
    """
    try:
        return action(token), token
    except XError as exc:
        if exc.status != HTTPStatus.UNAUTHORIZED:
            raise
    fresh = _refresh()
    return action(fresh), fresh


def _account(token: str) -> str:
    """The brand account's handle, read at send time so a refusal sends nothing."""
    user = x_client.whoami(token)
    username = user.get("username")
    if not isinstance(username, str) or not username:
        raise ValueError("the account read no username")
    return "@" + username


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
    """Every post's uploads, checked: alts, counts, indexes and single media."""
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
        video = post.get("video")
        gif = post.get("gif")
        singles = [name for name, value in (("video", video), ("gif", gif)) if value is not None]
        if len(singles) > 1:
            raise ValueError(f"post {index}: a post carries one video or GIF, not both")
        if singles and media[index]:
            raise ValueError(f"post {index}: a {singles[0]} post carries no images")
        for name in ("video", "gif"):
            value = post.get(name)
            if value is None:
                continue
            if not isinstance(value, str) or not value:
                raise ValueError(f"post {index}: no {name} path")
            media[index].append(Attachment(post=index, path=Path(value), alt=None, kind=name))
        images = [entry for entry in media[index] if entry.kind == "image"]
        if len(images) > MAX_IMAGES_PER_POST:
            raise ValueError(
                f"post {index}: at most {MAX_IMAGES_PER_POST} images, not {len(images)}"
            )
    return media


def _has_url(text: str) -> bool:
    """Whether the text carries a URL, which raises the price of the post."""
    return URL_RE.search(text) is not None


def _char_count(text: str, rates: Rates) -> int:
    """The weighted length X counts: every URL rides as its fixed length."""
    normalized = unicodedata.normalize("NFC", text)
    count = 0
    cursor = 0
    for match in URL_RE.finditer(normalized):
        count += _text_weight(normalized[cursor : match.start()]) + rates.url_length
        cursor = match.end()
    return count + _text_weight(normalized[cursor:])


def _text_weight(text: str) -> int:
    """X's weight for text without URLs: one a code point, two past Latin.

    Most characters count once, while CJK, emoji and other Unicode count
    twice; one emoji sequence (a skin tone, a flag, a ZWJ family) is one
    emoji and counts twice however many code points draw it.
    """
    total = 0
    index = 0
    while index < len(text):
        point = ord(text[index])
        if _is_emoji(point):
            total += 2
            index = _emoji_end(text, index)
        else:
            total += _point_weight(point)
            index += 1
    return total


def _point_weight(point: int) -> int:
    """One for a single-weight code point, two for the rest."""
    if point <= SINGLE_WEIGHT_MAX:
        return 1
    if any(start <= point <= end for start, end in SINGLE_WEIGHT_RANGES):
        return 1
    return 2


def _is_emoji(point: int) -> bool:
    """Whether this code point can begin the emoji X draws as one character."""
    return any(start <= point <= end for start, end in EMOJI_RANGES)


def _is_modifier(point: int) -> bool:
    """Whether this code point is an emoji skin-tone modifier."""
    return EMOJI_MODIFIERS[0] <= point <= EMOJI_MODIFIERS[1]


def _emoji_end(text: str, start: int) -> int:
    """The index after the emoji sequence that begins at ``start``."""
    index = start + 1
    point = ord(text[start])
    if _is_flag(point) and index < len(text) and _is_flag(ord(text[index])):
        return index + 1
    index = _skip_mark(text, index, VARIATION_SELECTOR_16)
    if index < len(text) and _is_modifier(ord(text[index])):
        index += 1
    if index < len(text) and text[index] == KEYCAP:
        return index + 1
    while index < len(text) and text[index] == ZERO_WIDTH_JOINER:
        index += 1
        if index < len(text):
            index += 1
        index = _skip_mark(text, index, VARIATION_SELECTOR_16)
        if index < len(text) and _is_modifier(ord(text[index])):
            index += 1
    return index


def _is_flag(point: int) -> bool:
    """Whether this code point is a regional indicator, half a flag."""
    return EMOJI_RANGES[0][0] <= point <= EMOJI_RANGES[0][1]


def _skip_mark(text: str, index: int, mark: str) -> int:
    """The index after one optional mark, so a sequence skips it once."""
    if index < len(text) and text[index] == mark:
        return index + 1
    return index


def _readable_text(text: str) -> str:
    """The text without URLs; X shortens links and may append a media one."""
    stripped = URL_RE.sub(" ", unicodedata.normalize("NFC", text))
    return " ".join(stripped.split())


def _same_text(actual: object, expected: object) -> bool:
    """Whether the network's text is the piece's, with X's URL rewriting allowed."""
    if not isinstance(actual, str) or not isinstance(expected, str):
        return False
    return _readable_text(actual) == _readable_text(expected)


def _post_price(text: str, rates: Rates) -> float:
    """The price of posting this text once, URL or not."""
    return rates.post_with_url if _has_url(text) else rates.post_no_url


def _money(amount: float, rates: Rates) -> dict[str, Any]:
    """One cost object in the receipt's shape."""
    return {"amount": round(amount, 4), "currency": rates.currency}


def _check_files(index: int, entries: list[Attachment]) -> None:
    """Refuse an upload the network would reject, before anything leaves."""
    for entry in entries:
        suffix = entry.path.suffix.lower()
        if entry.kind == "image" and suffix not in IMAGE_MIME:
            raise ValueError(f"post {index}: {entry.path.name} is not a postable image")
        if entry.kind == "video" and suffix not in x_client.VIDEO_MIME:
            raise ValueError(f"post {index}: {entry.path.name} is not a postable video")
        if entry.kind == "gif" and suffix != ".gif":
            raise ValueError(f"post {index}: {entry.path.name} is not a GIF")
        try:
            size = entry.path.stat().st_size
        except OSError:
            raise ValueError(f"post {index}: {entry.path} is not a file") from None
        if size > _upload_limit(entry.kind):
            raise ValueError(
                f"post {index}: {entry.path.name} is {size} bytes, over {_upload_limit(entry.kind)}"
            )


def _upload_limit(kind: str) -> int:
    """The byte cap the network enforces for one kind of upload."""
    if kind == "image":
        return IMAGE_UPLOAD_LIMIT
    return GIF_UPLOAD_LIMIT if kind == "gif" else VIDEO_UPLOAD_LIMIT


def _dry_run_posts(
    posts: list[dict[str, Any]], media: dict[int, list[Attachment]], rates: Rates
) -> tuple[list[dict[str, Any]], bool]:
    """One dry-run entry per post; the second answer names a URL surcharge."""
    rendered = []
    any_url = False
    for index, post in enumerate(posts, start=1):
        text = post.get("text")
        if not isinstance(text, str):
            raise ValueError(f"post {index}: no text")
        entries = media[index]
        warnings = _post_warnings(index, text, entries, rates)
        any_url = any_url or _has_url(text)
        rendered.append(
            {
                "text": text,
                "account": UNREAD_ACCOUNT,
                "media": [str(entry.path) for entry in entries],
                "warnings": warnings,
                "cost": _money(_post_price(text, rates), rates),
            }
        )
    return rendered, any_url


def _post_warnings(index: int, text: str, entries: list[Attachment], rates: Rates) -> list[str]:
    """What the dry run says about one post without sending anything."""
    if not text:
        raise ValueError(f"post {index}: no text")
    warnings: list[str] = []
    count = _char_count(text, rates)
    if count > WEIGHT_LIMIT:
        warnings.append(f"post {index} is {count} characters, over the {WEIGHT_LIMIT} limit")
    for entry in entries:
        warnings.extend(_size_warning(index, entry))
    if _has_url(text):
        warnings.append(f"post {index} carries a URL, priced above a text-only post")
    return warnings


def _size_warning(index: int, entry: Attachment) -> list[str]:
    """The over-limit warning for one upload, empty when it fits."""
    try:
        size = entry.path.stat().st_size
    except OSError:
        raise ValueError(f"post {index}: {entry.path} is not a file") from None
    limit = _upload_limit(entry.kind)
    if size > limit:
        return [f"post {index} {entry.path.name} is {size} bytes, over the {limit} limit"]
    return []


def _run_cost(posts: list[dict[str, Any]], rates: Rates) -> float:
    """The run's bill: every post, the read-back and the one account read."""
    posts_cost = sum(_post_price(str(post["text"]), rates) for post in posts)
    return posts_cost + rates.read_post * len(posts) + rates.read_user


def _group_warnings(
    posts: list[dict[str, Any]], rates: Rates, count: int, any_url: bool
) -> list[str]:
    """The itemized cost of the whole run: posts, the read-back and the account."""
    lines = []
    for index, post in enumerate(posts, start=1):
        text = str(post["text"])
        price = _post_price(text, rates)
        shape = "with URL" if _has_url(text) else "text-only"
        lines.append(f"post {index}: ${price:.3f} ({shape})")
    read_each = rates.read_post
    noun = "post" if count == 1 else "posts"
    lines.append(f"read-back: ${read_each * count:.3f} ({count} {noun} at ${read_each:.3f} each)")
    lines.append(f"account read: ${rates.read_user:.3f} (one user read at send time)")
    total = _run_cost(posts, rates)
    lines.append(f"total: ${total:.3f} {rates.currency}, rates read {rates.date}")
    if any_url:
        lines.insert(0, "a URL raises a post's price: check the itemized cost")
    return lines


@runner.verb("dry-run")
def dry_run(req: Request) -> dict[str, Any]:
    rates = _rates()
    posts = _posts(dict(req.inputs))
    media = _attachments(posts, _image_rows(dict(req.inputs)))
    rendered, any_url = _dry_run_posts(posts, media, rates)
    for index in range(1, len(posts) + 1):
        _check_paths(index, media[index])
    return {"posts": rendered, "warnings": _group_warnings(posts, rates, len(posts), any_url)}


def _check_paths(index: int, entries: list[Attachment]) -> None:
    """The dry run names a missing file instead of sending without it."""
    for entry in entries:
        if not entry.path.is_file():
            raise ValueError(f"post {index}: {entry.path} is not a file")


def _public_url(post_id: str) -> str:
    """The x.com URL of a post id."""
    return f"https://x.com/i/status/{post_id}"


def _upload(token: str, index: int, entry: Attachment) -> str:
    """Upload one file and answer its media id; an X refusal rides unchanged."""
    suffix = entry.path.suffix.lower()
    if entry.kind == "image":
        mime = IMAGE_MIME.get(suffix)
        category = "tweet_image"
    elif entry.kind == "gif":
        mime = x_client.GIF_MIME
        category = "tweet_gif"
    else:
        mime = x_client.VIDEO_MIME.get(suffix)
        category = "tweet_video"
    if mime is None:
        raise ValueError(f"post {index}: {entry.path.name} is not a postable file")
    try:
        data = entry.path.read_bytes()
    except OSError:
        raise ValueError(f"post {index}: {entry.path} cannot be read") from None
    media_id = x_client.upload_media(token, data, mime, category)
    if entry.kind == "image" and entry.alt:
        x_client.set_alt_text(token, media_id, entry.alt)
    return media_id


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    rates = _rates()
    posts = _posts(dict(req.inputs))
    media = _attachments(posts, _image_rows(dict(req.inputs)))
    for index, post in enumerate(posts, start=1):
        text = post.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError(f"post {index}: no text")
        if _char_count(text, rates) > WEIGHT_LIMIT:
            raise ValueError(f"post {index}: text is over the {WEIGHT_LIMIT} limit")
        _check_files(index, media[index])
    account, token = _with_token(_account)
    sent: list[dict[str, str]] = []
    reply_to: str | None = None
    for index, post in enumerate(posts, start=1):
        media_ids: list[str] = []
        for entry in media[index]:
            try:
                media_id, token = _send(partial(_upload, index=index, entry=entry), token)
            except XError as exc:
                raise ValueError(f"post {index}: {exc}") from exc
            media_ids.append(media_id)
        try:
            created, token = _send(
                partial(
                    x_client.create_post,
                    text=str(post["text"]),
                    media_ids=media_ids or None,
                    reply_to=reply_to,
                ),
                token,
            )
        except XError as exc:
            raise ValueError(f"post {index}: {exc}") from exc
        reply_to = created["id"]
        sent.append({"id": created["id"], "url": _public_url(created["id"])})
    return {
        "tool": _tool(),
        "post": {
            "network": NETWORK,
            "account": account,
            "state": "published",
            "posts": sent,
            "cost": _money(_run_cost(posts, rates), rates),
        },
    }


def _read_media(post: dict[str, Any]) -> list[dict[str, Any]]:
    """The attachments a read-back post carries: one entry per media key."""
    attachments = post.get("attachments")
    if not isinstance(attachments, dict):
        return []
    keys = attachments.get("media_keys")
    if not isinstance(keys, list):
        return []
    return [{"file": f"{key}.blob", "alt": None} for key in keys if isinstance(key, str)]


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    refs = req.post.get("posts")
    if not isinstance(refs, list) or not refs:
        raise ValueError("the receipt names no posts")
    expected = req.inputs.get("posts")
    texts: list[object] | None = None
    counts: list[int] | None = None
    if isinstance(expected, list) and expected:
        inputs = _posts(dict(req.inputs))
        media = _attachments(inputs, _image_rows(dict(req.inputs)))
        texts = [post.get("text") for post in inputs]
        counts = [len(media[index]) for index in range(1, len(inputs) + 1)]
    ids: list[str] = []
    for index, ref in enumerate(refs, start=1):
        if not isinstance(ref, dict) or not isinstance(ref.get("id"), str):
            raise ValueError(f"post {index}: the receipt names no id")
        ids.append(str(ref["id"]))
    try:
        found, _ = _with_token(lambda token: x_client.get_posts(token, ids))
    except ValueError as exc:
        raise ValueError(f"the read-back failed: {exc}") from exc
    by_id = {post.get("id"): post for post in found if isinstance(post, dict)}
    measured: list[dict[str, Any]] = []
    for index, post_id in enumerate(ids, start=1):
        post = by_id.get(post_id)
        if post is None:
            raise ValueError(f"post {index}: the network holds no post {post_id}")
        if texts is not None and (
            index - 1 >= len(texts) or not _same_text(post.get("text"), texts[index - 1])
        ):
            raise ValueError(f"post {index}: the network holds different text")
        entries = _read_media(post)
        if counts is not None and (index - 1 >= len(counts) or len(entries) != counts[index - 1]):
            raise ValueError(f"post {index}: the network holds a different media count")
        measured.extend(entries)
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
    """The vendored client and the rates file answer their own smoke test."""
    rates = _rates()
    if (
        rates.url_length != TCO_LENGTH
        or rates.post_no_url <= 0
        or rates.read_post <= 0
        or rates.read_user <= 0
    ):
        return _check("imports", False, "rates.json is not the dated price table", "facet pull x")
    if not callable(x_client.create_post):
        return _check("imports", False, "the X client is missing", "facet pull x")
    return _check("imports", True, "client and rates answer")


def _missing_secret(name: str) -> str | None:
    """The secret's absence as its fix, or nothing when it is stored."""
    try:
        secret(name)
    except KeyError as exc:
        return str(exc)
    return None


def _doctor_secrets() -> list[dict[str, Any]]:
    """All four credentials are stored; a value never appears in a detail."""
    checks = []
    for name in ("client-id", "client-secret", "access-token", "refresh-token"):
        missing = _missing_secret(name)
        if missing is None:
            checks.append(_check(name, True, f"{name} is stored"))
        elif name in ("access-token", "refresh-token"):
            checks.append(
                _check(
                    name,
                    False,
                    f"{name} is not stored",
                    f"run facet auth login x to sign in and store {name}",
                )
            )
        else:
            checks.append(_check(name, False, f"{name} is not stored", missing))
    return checks


def _doctor_session() -> dict[str, Any]:
    """Read the own account with a working token and state what that read costs."""
    try:
        user, _ = _with_token(x_client.whoami)
    except ValueError as exc:
        return _check("session", False, f"sign-in failed: {exc}", WRITE_FIX)
    if not isinstance(user, dict):
        return _check("session", False, "the account read no user", WRITE_FIX)
    rates = _rates()
    name = user.get("name") or user.get("username") or ""
    return _check(
        "session",
        True,
        f"signed in as @{user.get('username', '')} ({name}); "
        f"that read costs ${rates.read_user:.3f}",
    )


def _doctor_write() -> dict[str, Any]:
    """Probe the token's write access; a refusal names the sign-in that grants it."""
    try:
        allowed, _ = _with_token(x_client.probe_write)
    except ValueError as exc:
        return _check("write", False, f"the write probe failed: {exc}", WRITE_FIX)
    if allowed:
        return _check(
            "write",
            True,
            "the token may write: a probe the network rejects before creating a post was accepted",
        )
    return _check(
        "write", False, "the token cannot write: the network refused the probe", WRITE_FIX
    )


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_imports(), *_doctor_secrets()]
    if req.depth == "full":
        session = _doctor_session()
        checks.append(session)
        if session["ok"]:
            checks.append(_doctor_write())
    return {"checks": checks}


@runner.verb("auth")
def auth(req: Request) -> dict[str, Any]:
    try:
        client_id, client_secret = _credentials()
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    redirect = req.inputs.get("redirect-uri")
    if redirect is not None and (not isinstance(redirect, str) or not redirect):
        raise ValueError("the redirect URI is not a URI")
    uri = str(redirect) if isinstance(redirect, str) else x_client.DEFAULT_REDIRECT_URI
    try:
        secrets = x_client.authorize(client_id, client_secret, uri, announce=announce_url)
    except XError as exc:
        raise ValueError(str(exc)) from exc
    return {"secrets": secrets}


runner.main()
