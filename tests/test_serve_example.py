"""The example server serves facet's three routes and nothing else.

Stdlib unittest (no extra dependency): every example file answers 200 over
its own route, unknown and escaping paths are 404, and no directory is ever
listed.
"""

from __future__ import annotations

import importlib.util
import threading
import unittest
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "serve-example.py"


def load_serve_module() -> Any:
    spec = importlib.util.spec_from_file_location("serve_example", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


serve = load_serve_module()


class ServerFixture(unittest.TestCase):
    """Base fixture: one example server on a free port, shared by subclasses."""

    kind = "cad"

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = serve.make_server(cls.kind, 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def fetch(self, path: str) -> tuple[int, bytes, str]:
        request = urllib.request.Request(self.base + path)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read(), response.headers["Content-Type"]
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers.get("Content-Type", "")


class RouteTests(ServerFixture):
    def test_example_files_answer_200(self) -> None:
        asset = serve.example_asset(self.kind)
        cases: Sequence[tuple[str, str]] = (
            ("/viewer/index.html", "text/html"),
            ("/viewer/main.js", "text/javascript"),
            ("/kit/base.css", "text/css"),
            (f"/asset/{asset}", "model/step"),
            (f"/asset/{asset}.facet.json", "application/json"),
            (f"/asset/{asset}.preview.json", "application/json"),
        )
        for path, expected_type in cases:
            with self.subTest(path=path):
                status, body, content_type = self.fetch(path)
                self.assertEqual(status, 200, path)
                self.assertTrue(body, path)
                self.assertEqual(content_type, expected_type, path)

    def test_preview_image_answers_200(self) -> None:
        status, body, content_type = self.fetch("/asset/escuadra-iso.png")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "image/png")
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_unknown_paths_are_404(self) -> None:
        for path in ("/", "/nope", "/viewer/nope.html", "/kit/nope.js", "/asset/nope.step"):
            with self.subTest(path=path):
                status, _, _ = self.fetch(path)
                self.assertEqual(status, 404, path)

    def test_traversal_is_404(self) -> None:
        for path in ("/asset/../../ruff.toml", "/asset/..%2f..%2fruff.toml", "/kit/../scripts"):
            with self.subTest(path=path):
                status, _, _ = self.fetch(path)
                self.assertEqual(status, 404, path)

    def test_no_directory_is_listed(self) -> None:
        for path in ("/asset/", "/viewer/", "/kit/"):
            with self.subTest(path=path):
                status, body, _ = self.fetch(path)
                self.assertEqual(status, 404, path)
                self.assertNotIn(b"tone.wav", body)

    def test_asset_name_comes_from_the_example_dir(self) -> None:
        self.assertEqual(serve.example_asset("cad"), "escuadra.step")
        self.assertEqual(serve.example_asset("audio"), "tone.wav")


class AudioExampleTests(ServerFixture):
    kind = "audio"

    def test_audio_routes_answer_200(self) -> None:
        for path in (
            "/viewer/index.html",
            "/kit/chart.js",
            "/asset/tone.wav",
            "/asset/tone.wav.facet.json",
            "/asset/tone.wav.preview.json",
        ):
            with self.subTest(path=path):
                status, body, _ = self.fetch(path)
                self.assertEqual(status, 200, path)
                self.assertTrue(body, path)

    def test_other_kind_asset_is_404(self) -> None:
        status, _, _ = self.fetch("/asset/escuadra-iso.png")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
