"""The deck presenter runner: notes attach to their slides, no browser involved.

The runner is a subprocess of the host ``node`` started with an empty ``PATH``:
the presenter build spawns nothing, so no browser, server or opener can start.
The stub deck has three slides, a logo and a stylesheet background; the notes
arrive out of order and must land on their slides in ``page`` order.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "deck"
RUNNER = PACKAGE / "runner.js"
NODE = shutil.which("node")
CAPABILITY = "deck.presenter"
TOOL = {"name": "deck", "version": "0.1.0"}
SLIDES = 3
NOTES = 3
DATA_URIS = 2
EMBEDDED_RE = re.compile(r"window\.__PZ_NOTES__=(\[.*?\]);</script>", re.S)
SEPARATOR_RE = re.compile(r"^\s*---\s*$", re.M)

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not available")

DECK_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
.slide { width: 1280px; height: 720px; }
.cover { background: url("bg.png"); }
</style></head><body>
<section class="slide">one<img src="logo.png"></section>
<section class="slide two">two</section>
<section class="slide">three</section>
</body></html>
"""

NOTAS = [
    {"page": 3, "text": "Third note"},
    {"page": 1, "text": "First note"},
    {"page": 2, "text": "Second note"},
]
ORDERED = ["First note", "Second note", "Third note"]


def _piece(root: Path, html: str = DECK_HTML) -> tuple[Path, Path]:
    piece = root / "piece"
    piece.mkdir()
    deck = piece / "slides.html"
    deck.write_text(html, encoding="utf-8")
    for name in ("logo.png", "bg.png"):
        (piece / name).write_bytes(b"\x89PNG\r\n\x1a\nSTUB")
    return piece, deck


def _inputs(notes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"source": "slides.html", "notes": NOTAS if notes is None else notes}


def _request(
    verb: str, out: Path, piece: Path, *, inputs: dict[str, Any], assets: list[str] | None = None
) -> dict[str, Any]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": CAPABILITY,
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(piece),
        "models": {},
        "assets": assets or [],
    }


def _invoke(
    root: Path, verb: str, request: dict[str, Any]
) -> tuple[subprocess.CompletedProcess[str], Any]:
    request_file = root / "request.json"
    result_file = root / "result.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    result_file.unlink(missing_ok=True)
    done = subprocess.run(
        [str(NODE), str(RUNNER), verb, "--input", str(request_file), "--result", str(result_file)],
        cwd=root,
        env={**os.environ, "PATH": ""},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else None
    return done, result


def _run(
    root: Path, out: Path, piece: Path, notes: list[dict[str, Any]] | None = None
) -> tuple[subprocess.CompletedProcess[str], Any]:
    request = _request("run", out, piece, inputs=_inputs(notes))
    return _invoke(root, "run", request)


def _verified(
    root: Path, out: Path, piece: Path, notes: list[dict[str, Any]] | None = None
) -> tuple[subprocess.CompletedProcess[str], Any]:
    assets = [str(out / "slides.present.html"), str(out / "slides.notes.md")]
    request = _request("verify", out, piece, inputs=_inputs(notes), assets=assets)
    return _invoke(root, "verify", request)


def _embedded(html: str) -> list[Any]:
    match = EMBEDDED_RE.search(html)
    assert match is not None
    return json.loads(match.group(1))


def _sections(text: str) -> list[str]:
    return [section.strip() for section in SEPARATOR_RE.split(text)]


def test_run_attaches_notes_to_their_slides_and_writes_both_files(tmp_path: Path) -> None:
    piece, deck = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _run(tmp_path, out, piece)
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    assert result["tool"] == TOOL
    present, notes = result["assets"]
    expected = {"slides": SLIDES, "notes": NOTES}
    assert (present["file"], present["kind"], present["mime"]) == (
        "slides.present.html",
        "document",
        "text/html",
    )
    assert (notes["file"], notes["kind"], notes["mime"]) == (
        "slides.notes.md",
        "text",
        "text/markdown",
    )
    assert present["properties"] == expected
    assert notes["properties"] == expected
    assert present["seed"] == 0
    assert present["inputs"] == [str(deck)]
    assert notes["inputs"] == [str(deck)]
    html = (out / "slides.present.html").read_text(encoding="utf-8")
    assert _embedded(html) == ORDERED
    closing = html.index("</body>")
    assert html.index(".pz-grid") < closing
    assert html.index("window.__PZ_NOTES__") < closing
    assert html.index("BroadcastChannel('pz-sync')") < closing
    assert html.count("data:image/png;base64,") == DATA_URIS
    companion = (out / "slides.notes.md").read_text(encoding="utf-8")
    assert _sections(companion) == ORDERED


def test_run_refuses_a_duplicate_page(tmp_path: Path) -> None:
    piece, _deck = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    notes = [{"page": 1, "text": "A"}, {"page": 1, "text": "B"}]
    done, result = _run(tmp_path, out, piece, notes)
    assert done.returncode != 0
    assert result is None
    assert "page" in done.stderr
    assert not (out / "slides.present.html").exists()


def test_run_refuses_a_page_beyond_the_deck(tmp_path: Path) -> None:
    piece, _deck = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    notes = [{"page": 1, "text": "A"}, {"page": 4, "text": "D"}]
    done, result = _run(tmp_path, out, piece, notes)
    assert done.returncode != 0
    assert result is None
    assert "page" in done.stderr
    assert "slides" in done.stderr


def test_run_refuses_a_missing_image_ref(tmp_path: Path) -> None:
    html = DECK_HTML.replace('src="logo.png"', 'src="missing.png"')
    piece, _deck = _piece(tmp_path, html)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _run(tmp_path, out, piece)
    assert done.returncode != 0
    assert result is None
    assert "missing.png" in done.stderr
    assert not (out / "slides.present.html").exists()


def test_run_warns_about_a_missing_video_and_still_writes(tmp_path: Path) -> None:
    html = DECK_HTML.replace(
        '<section class="slide two">two</section>',
        '<section class="slide two">two<video src="clip.mp4"></video></section>',
    )
    piece, _deck = _piece(tmp_path, html)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _run(tmp_path, out, piece)
    assert done.returncode == 0, done.stderr
    assert result is not None
    assert "aviso" in done.stderr
    assert "clip.mp4" in done.stderr
    assert (out / "slides.present.html").is_file()
    assert (out / "slides.notes.md").is_file()


def test_verify_passes_on_the_written_build(tmp_path: Path) -> None:
    piece, _deck = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    _done, _result = _run(tmp_path, out, piece)
    done, result = _verified(tmp_path, out, piece)
    assert done.returncode == 0, done.stderr
    assert [entry["file"] for entry in result["assets"]] == [
        "slides.present.html",
        "slides.notes.md",
    ]
    assert all(entry["passed"] is True for entry in result["assets"])
    assert all(entry["verifier"] == "presenter" for entry in result["assets"])


def test_verify_fails_when_the_notes_companion_is_tampered(tmp_path: Path) -> None:
    piece, _deck = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    _done, _result = _run(tmp_path, out, piece)
    notes = out / "slides.notes.md"
    notes.write_text(
        notes.read_text(encoding="utf-8").replace("Second note", "Tampered"), encoding="utf-8"
    )
    done, result = _verified(tmp_path, out, piece)
    assert done.returncode != 0
    assert result is None
    assert "notes.md" in done.stderr


def test_verify_fails_when_the_embedded_array_is_tampered(tmp_path: Path) -> None:
    piece, _deck = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    _done, _result = _run(tmp_path, out, piece)
    present = out / "slides.present.html"
    present.write_text(
        EMBEDDED_RE.sub(
            'window.__PZ_NOTES__=["First note"];</script>', present.read_text(encoding="utf-8")
        ),
        encoding="utf-8",
    )
    done, result = _verified(tmp_path, out, piece)
    assert done.returncode != 0
    assert result is None
    assert "__PZ_NOTES__" in done.stderr


def test_verify_fails_on_duplicate_pages(tmp_path: Path) -> None:
    piece, _deck = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    _done, _result = _run(tmp_path, out, piece)
    notes = [{"page": 1, "text": "A"}, {"page": 1, "text": "B"}]
    done, result = _verified(tmp_path, out, piece, notes)
    assert done.returncode != 0
    assert result is None
    assert "page" in done.stderr


def test_preview_writes_the_document_and_the_generic_text_files(tmp_path: Path) -> None:
    piece, _deck = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    _done, _result = _run(tmp_path, out, piece)
    assets = [str(out / "slides.present.html"), str(out / "slides.notes.md")]
    request = _request("preview", out, piece, inputs=_inputs(), assets=assets)
    done, result = _invoke(tmp_path, "preview", request)
    assert done.returncode == 0, done.stderr
    assert result["assets"] == [
        {
            "file": "slides.present.html",
            "preview": "slides.present.html.preview.json",
            "images": [],
        },
        {"file": "slides.notes.md", "preview": "slides.notes.md.preview.json", "images": []},
    ]
    document = json.loads((out / "slides.present.html.preview.json").read_text(encoding="utf-8"))
    assert set(document) == {"preview", "kind", "summary", "page_count", "pages"}
    assert document["preview"] == 1
    assert document["kind"] == "document"
    assert document["page_count"] == 1
    assert document["pages"] == []
    text = json.loads((out / "slides.notes.md.preview.json").read_text(encoding="utf-8"))
    assert set(text) == {"preview", "kind", "summary", "fields"}
    assert text["preview"] == 1
    assert text["kind"] == "text"
    assert text["fields"] == {"notes": NOTES}
