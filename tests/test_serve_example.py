"""The example server serves facet's three routes over the viewers.

Stdlib unittest (no extra dependency): every viewer file, kit module and
example file answers 200 over its own route with its bytes intact, an asset
answers byte ranges (a browser cannot seek an ``<audio>`` element over a
server that always sends the whole file), unknown and escaping paths are 404,
no directory is ever listed, and the viewers reference nothing outside the
local routes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import threading
import unittest
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "serve-example.py"
VIEWERS = ROOT / "viewers"
KINDS = ("generic", "audio", "cad")
#: Content types a browser needs exactly right for ES modules and tokens.
CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}
EXTERNAL = re.compile(r"https?://")


def load_serve_module() -> Any:
    spec = importlib.util.spec_from_file_location("serve_example", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


serve = load_serve_module()


@contextmanager
def running(kind: str) -> Iterator[str]:
    """A server for `kind` on a free port, stopped when the block ends."""
    server = serve.make_server(kind, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def fetch(
    base: str, path: str, headers: dict[str, str] | None = None
) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


def routes_of(kind: str) -> list[tuple[str, Path]]:
    """Every (request path, file) pair the example server exposes for `kind`."""
    pairs: list[tuple[str, Path]] = []
    for prefix, root in serve.route_roots(kind).items():
        for path in sorted(root.rglob("*")):
            if path.is_file():
                pairs.append((prefix + path.relative_to(root).as_posix(), path))
    return pairs


class ServingTests(unittest.TestCase):
    def test_every_file_answers_200_with_its_bytes(self) -> None:
        for kind in KINDS:
            with running(kind) as base:
                pairs = routes_of(kind)
                names = {path.name for _, path in pairs}
                self.assertIn("index.html", names)
                self.assertIn("main.js", names)
                for route, path in pairs:
                    with self.subTest(kind=kind, route=route):
                        status, body, headers = fetch(base, route)
                        self.assertEqual(status, 200, route)
                        self.assertEqual(body, path.read_bytes(), route)
                        expected = CONTENT_TYPES.get(path.suffix)
                        if expected is not None:
                            self.assertEqual(headers["Content-Type"], expected, route)

    def test_kit_modules_are_served_for_every_kind(self) -> None:
        kit = sorted(path.name for path in (VIEWERS / "_kit").iterdir() if path.is_file())
        self.assertTrue(kit)
        for kind in KINDS:
            with running(kind) as base:
                for name in kit:
                    with self.subTest(kind=kind, name=name):
                        status, _, _ = fetch(base, f"/kit/{name}")
                        self.assertEqual(status, 200, name)

    def test_asset_record_and_preview_answer(self) -> None:
        for kind in KINDS:
            with running(kind) as base:
                asset = serve.example_asset(kind)
                status, body, _ = fetch(base, f"/asset/{asset}")
                self.assertEqual(status, 200)
                self.assertTrue(body)
                for suffix in (".facet.json", ".preview.json"):
                    with self.subTest(kind=kind, suffix=suffix):
                        status, body, headers = fetch(base, f"/asset/{asset}{suffix}")
                        self.assertEqual(status, 200)
                        self.assertEqual(headers["Content-Type"], "application/json")
                        self.assertIn("kind", json.loads(body))

    def test_preview_image_answers_200(self) -> None:
        with running("cad") as base:
            status, body, headers = fetch(base, "/asset/escuadra-iso.png")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))


class RangeTests(unittest.TestCase):
    """Byte ranges: without them the audio player cannot seek."""

    def test_plain_response_advertises_ranges(self) -> None:
        with running("audio") as base:
            _, body, headers = fetch(base, "/asset/tone.wav")
        self.assertEqual(headers.get("Accept-Ranges"), "bytes")
        self.assertEqual(int(headers["Content-Length"]), len(body))

    def test_byte_range_answers_206_with_that_slice(self) -> None:
        with running("audio") as base:
            _, whole, _ = fetch(base, "/asset/tone.wav")
            status, part, headers = fetch(base, "/asset/tone.wav", {"Range": "bytes=10-19"})
        self.assertEqual(status, 206)
        self.assertEqual(part, whole[10:20])
        self.assertEqual(headers["Content-Range"], f"bytes 10-19/{len(whole)}")
        self.assertEqual(headers["Content-Length"], "10")

    def test_open_ended_range_runs_to_the_end(self) -> None:
        with running("audio") as base:
            _, whole, _ = fetch(base, "/asset/tone.wav")
            status, part, headers = fetch(base, "/asset/tone.wav", {"Range": "bytes=1000-"})
        self.assertEqual(status, 206)
        self.assertEqual(part, whole[1000:])
        self.assertEqual(headers["Content-Range"], f"bytes 1000-{len(whole) - 1}/{len(whole)}")

    def test_suffix_range_answers_the_last_bytes(self) -> None:
        with running("audio") as base:
            _, whole, _ = fetch(base, "/asset/tone.wav")
            status, part, _ = fetch(base, "/asset/tone.wav", {"Range": "bytes=-64"})
        self.assertEqual(status, 206)
        self.assertEqual(part, whole[-64:])

    def test_range_past_the_end_is_416(self) -> None:
        with running("audio") as base:
            status, _, _ = fetch(base, "/asset/tone.wav", {"Range": "bytes=99999999-"})
        self.assertEqual(status, 416)


class NotFoundTests(unittest.TestCase):
    def test_unknown_paths_are_404(self) -> None:
        for kind in KINDS:
            with running(kind) as base:
                for path in ("/", "/nope", "/viewer/nope.html", "/kit/nope.js", "/asset/nope"):
                    with self.subTest(kind=kind, path=path):
                        status, _, _ = fetch(base, path)
                        self.assertEqual(status, 404, path)

    def test_traversal_is_404(self) -> None:
        with running("cad") as base:
            for path in ("/asset/../../ruff.toml", "/asset/..%2f..%2fruff.toml", "/kit/../scripts"):
                with self.subTest(path=path):
                    status, _, _ = fetch(base, path)
                    self.assertEqual(status, 404, path)

    def test_no_directory_is_listed(self) -> None:
        for kind in KINDS:
            with running(kind) as base:
                asset = serve.example_asset(kind)
                for path in ("/asset/", "/viewer/", "/kit/"):
                    with self.subTest(kind=kind, path=path):
                        status, body, _ = fetch(base, path)
                        self.assertEqual(status, 404, path)
                        self.assertNotIn(asset.encode(), body, path)

    def test_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            serve.make_server("video", 0)


class ViewerSourceTests(unittest.TestCase):
    """The viewers stay local: no CDN, and every reference resolves."""

    def test_every_viewer_references_local_files_that_exist(self) -> None:
        for kind in KINDS:
            for name in ("index.html", "main.js"):
                source = (VIEWERS / kind / name).read_text(encoding="utf-8")
                with self.subTest(kind=kind, file=name):
                    self.assertIsNone(EXTERNAL.search(source), f"{kind}/{name} loads a remote URL")
            html = (VIEWERS / kind / "index.html").read_text(encoding="utf-8")
            for reference in re.findall(r'(?:src|href)="([^"]+)"', html):
                if reference.startswith("data:") or reference.startswith("#"):
                    continue
                with self.subTest(kind=kind, reference=reference):
                    target = (
                        VIEWERS / "_kit" / reference.removeprefix("/kit/")
                        if reference.startswith("/kit/")
                        else VIEWERS / kind / reference.removeprefix("./")
                    )
                    self.assertTrue(target.is_file(), f"{kind}/index.html -> {reference}")

    def test_every_viewer_imports_only_the_kit(self) -> None:
        for kind in KINDS:
            source = (VIEWERS / kind / "main.js").read_text(encoding="utf-8")
            for target in re.findall(r'from\s+"([^"]+)"', source):
                with self.subTest(kind=kind, target=target):
                    if target.startswith("/kit/"):
                        imported = VIEWERS / "_kit" / target.removeprefix("/kit/")
                    else:
                        self.assertTrue(target.startswith("./"), target)
                        imported = VIEWERS / kind / target.removeprefix("./")
                    self.assertTrue(imported.is_file(), f"{kind} imports missing {target}")


class ExampleDataTests(unittest.TestCase):
    """The example record and preview agree with the asset beside them."""

    def test_asset_name_comes_from_the_example_dir(self) -> None:
        self.assertEqual(serve.example_asset("generic"), "hello.txt")
        self.assertEqual(serve.example_asset("audio"), "tone.wav")
        self.assertEqual(serve.example_asset("cad"), "escuadra.step")

    def test_every_record_matches_its_asset(self) -> None:
        for kind in KINDS:
            with self.subTest(kind=kind):
                folder = VIEWERS / "_examples" / kind
                asset = folder / serve.example_asset(kind)
                record = json.loads(Path(f"{asset}.facet.json").read_text(encoding="utf-8"))
                digest = hashlib.sha256(asset.read_bytes()).hexdigest()
                self.assertEqual(record["id"], f"sha256:{digest}")
                self.assertEqual(record["bytes"], asset.stat().st_size)
                self.assertEqual(record["path"], asset.name)

    def test_preview_kind_matches_the_record(self) -> None:
        for kind in KINDS:
            with self.subTest(kind=kind):
                folder = VIEWERS / "_examples" / kind
                asset = folder / serve.example_asset(kind)
                record = json.loads(Path(f"{asset}.facet.json").read_text(encoding="utf-8"))
                preview = json.loads(Path(f"{asset}.preview.json").read_text(encoding="utf-8"))
                self.assertEqual(preview["preview"], 1)
                self.assertEqual(preview["kind"], record["kind"])


if __name__ == "__main__":
    unittest.main()
