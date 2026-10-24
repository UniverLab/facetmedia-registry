#!/usr/bin/env python3
"""Serve a viewer example over facet's own three routes.

    python3 scripts/serve-example.py <kind> [--port N]

``/viewer/`` is ``viewers/<kind>/``, ``/kit/`` is ``viewers/_kit/`` and
``/asset/`` is ``viewers/_examples/<kind>/`` — the same routes ``facet
preview`` serves on 127.0.0.1. The first line printed is the URL to open;
anything outside those three routes (and any directory, or any path that
escapes its root with ``..``) is a 404. No other host is ever bound.

Assets answer byte ranges (``206``), because a browser cannot seek an
``<audio>`` element — the audio viewer's click-to-seek and playhead — over a
server that always returns the whole file.
"""

from __future__ import annotations

import argparse
import mimetypes
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
VIEWERS = ROOT / "viewers"
#: Content types the platform's mimetypes table gets wrong or lacks.
CONTENT_TYPES = {".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript"}


def example_kinds() -> list[str]:
    """Every kind that has examples on disk, sorted."""
    base = VIEWERS / "_examples"
    if not base.is_dir():
        return []
    return sorted(entry.name for entry in base.iterdir() if entry.is_dir())


def route_roots(kind: str) -> dict[str, Path]:
    """The directory each of the three route prefixes serves from."""
    return {
        "/viewer/": VIEWERS / kind,
        "/kit/": VIEWERS / "_kit",
        "/asset/": VIEWERS / "_examples" / kind,
    }


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
            target = resolve_route(roots, urlsplit(self.path).path)
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
    if kind not in example_kinds():
        raise SystemExit(f"serve-example: no examples for kind {kind!r}")
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(kind))


def main(argv: Sequence[str] | None = None) -> int:
    kinds = example_kinds()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=kinds, help="the example kind to serve")
    parser.add_argument("--port", type=int, default=0, help="port (0 picks a free one)")
    args = parser.parse_args(argv)

    server = make_server(args.kind, args.port)
    host, port = server.server_address[:2]
    print(f"http://{host}:{port}/viewer/index.html?asset={example_asset(args.kind)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
