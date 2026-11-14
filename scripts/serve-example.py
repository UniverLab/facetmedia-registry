#!/usr/bin/env python3
"""Serve a viewer example over facet's own routes.

    python3 scripts/serve-example.py <kind> [--port N]

``/viewer/`` is ``viewers/<kind>/``, ``/kit/`` is ``viewers/_kit/`` and
``/asset/`` is ``viewers/_examples/<kind>/`` — the same routes ``facet
preview`` serves on 127.0.0.1. The ``gallery`` kind has no single asset, so it
also answers ``/gallery.json`` (``viewers/_examples/gallery.json``),
``/thumb/<n>`` and ``/open/<n>``, the routes ``facet preview <folder>``
serves. The first line printed is the URL to open; anything outside those
routes (and any directory, or any path that escapes its root with ``..``) is
a 404. No other host is ever bound.

Assets answer byte ranges (``206``), because a browser cannot seek an
``<audio>`` element — the audio viewer's click-to-seek and playhead — over a
server that always returns the whole file.
"""

from __future__ import annotations

import argparse
import base64
import mimetypes
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
VIEWERS = ROOT / "viewers"
#: Content types the platform's mimetypes table gets wrong or lacks.
CONTENT_TYPES = {".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript"}
#: The kind that browses a folder instead of rendering one asset.
GALLERY = "gallery"
#: A 1x1 PNG: whatever a gallery asset looks like, its example thumbnail is this.
THUMB_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGOQqveuAAAC+AFdTecdpwAAAA"
    "BJRU5ErkJggg=="
)
#: The page an example card's ``open`` lands on, with a way back.
OPEN_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>facet — gallery example asset {n}</title>
    <link rel="icon" href="data:," />
  </head>
  <body>
    <h1>asset {n}</h1>
    <p><a href="/viewer/index.html">back to the gallery</a></p>
  </body>
</html>
"""


def example_kinds() -> list[str]:
    """Every kind that has examples on disk, sorted."""
    base = VIEWERS / "_examples"
    if not base.is_dir():
        return []
    return sorted(entry.name for entry in base.iterdir() if entry.is_dir())


def available_kinds() -> list[str]:
    """Every kind the server accepts: the example dirs and the gallery."""
    return sorted({*example_kinds(), GALLERY})


def route_roots(kind: str) -> dict[str, Path]:
    """The directory each route prefix serves from."""
    roots = {"/viewer/": VIEWERS / kind, "/kit/": VIEWERS / "_kit"}
    examples = VIEWERS / "_examples" / kind
    if examples.is_dir():
        roots["/asset/"] = examples
    return roots


def gallery_file() -> Path:
    """The example ``/gallery.json``: a folder of cards, not one asset."""
    return VIEWERS / "_examples" / f"{GALLERY}.json"


def gallery_response(path: str) -> tuple[bytes, str] | None:
    """The (body, Content-Type) an example gallery route answers with, or None
    so the ordinary routes (and their 404s) answer instead."""
    if path == "/gallery.json":
        return gallery_file().read_bytes(), "application/json"
    if path.startswith("/thumb/"):
        number = path.removeprefix("/thumb/")
        return (THUMB_PNG, "image/png") if number.isdigit() else None
    if path.startswith("/open/"):
        number = path.removeprefix("/open/")
        return (OPEN_PAGE.format(n=number).encode(), "text/html") if number.isdigit() else None
    return None


def example_asset(kind: str) -> str:
    """The example asset's name: the file whose own record sits beside it."""
    folder = VIEWERS / "_examples" / kind
    for entry in sorted(folder.iterdir()):
        if entry.is_file() and Path(f"{entry}.facet.json").is_file():
            return entry.name
    raise SystemExit(f"serve-example: no asset in {folder}")


def resolve_route(roots: dict[str, Path], path: str) -> Path | None:
    """The file a request path names, or None for any 404 (unknown route,
    directory or listing, missing file, or a path escaping its root)."""
    matched = next((prefix for prefix in roots if path.startswith(prefix)), None)
    if matched is None:
        return None
    relative = unquote(path[len(matched) :])
    if not relative or relative.endswith("/"):
        return None  # a bare prefix is a directory: never listed
    root = roots[matched].resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def content_type_of(path: Path) -> str:
    """The Content-Type to send for `path`."""
    return (
        CONTENT_TYPES.get(path.suffix)
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """The single byte span (start, end, both inclusive) a ``Range`` header
    asks for, or None to send the whole file.

    Multiple ranges, a header that is not ``bytes=`` and a malformed range all
    send the whole file. A span with ``start > end`` asks for nothing, so the
    caller answers 416.
    """
    if not header or not header.startswith("bytes="):
        return None
    first, _, rest = header[len("bytes=") :].partition(",")
    if rest.strip():  # more than one range: the whole file is a valid answer
        return None
    start_text, _, end_text = first.strip().partition("-")
    if not start_text:  # "bytes=-N": the last N bytes
        if not end_text.isdigit() or int(end_text) == 0:
            return None
        return max(0, size - int(end_text)), size - 1
    if not start_text.isdigit():
        return None
    start = int(start_text)
    end = min(int(end_text), size - 1) if end_text.isdigit() else size - 1
    return start, end


def make_handler(kind: str) -> type[BaseHTTPRequestHandler]:
    roots = route_roots(kind)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server's naming
            path = urlsplit(self.path).path
            if kind == GALLERY:
                gallery = gallery_response(path)
                if gallery is not None:
                    self.send_body(*gallery)
                    return
            target = resolve_route(roots, path)
            if target is None:
                self.send_error(404, "not found")
                return
            self.send_body(target.read_bytes(), content_type_of(target))

        def send_body(self, body: bytes, content_type: str) -> None:
            """The whole file, or the byte range asked for (206)."""
            span = parse_range(self.headers.get("Range"), len(body))
            if span is None:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(body)
                return
            start, end = span
            if start > end:
                self.send_error(416, "range not satisfiable")
                return
            self.send_response(206)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(body[start : end + 1])

    return Handler


def make_server(kind: str, port: int = 0) -> ThreadingHTTPServer:
    """A server bound to 127.0.0.1 only; port 0 picks a free one."""
    if kind not in available_kinds():
        raise SystemExit(f"serve-example: no examples for kind {kind!r}")
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(kind))


def main(argv: Sequence[str] | None = None) -> int:
    kinds = available_kinds()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=kinds, help="the example kind to serve")
    parser.add_argument("--port", type=int, default=0, help="port (0 picks a free one)")
    parser.add_argument(
        "--role",
        default=None,
        help="append ?role=<role> to the printed viewer URL (audience, presenter)",
    )
    args = parser.parse_args(argv)

    server = make_server(args.kind, args.port)
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}/viewer/index.html"
    if args.kind == GALLERY:
        print(base, flush=True)
    else:
        url = f"{base}?asset={example_asset(args.kind)}"
        if args.role:
            url += f"&role={args.role}"
        print(url, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
