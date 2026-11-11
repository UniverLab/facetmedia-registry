"""The deck runner against a stub playwright, a stub pdf.js and a stub Chromium.

The runner is a subprocess of the host ``node``. Its ``FACET_NODE_PATH`` points
at a fixture ``playwright-core`` package whose entry records every browser call
and writes a stub PDF, plus a fixture ``pdfjs-dist`` whose ``build/pdf.js``
answers the page count and the text check from ``DECK_STUB_PAGES`` and
``DECK_STUB_TEXT``. ``PATH`` carries only a stub Chromium: no ``pdftoppm``,
``pdfinfo`` or ``pdftotext`` exists anywhere in the environment, which proves
the print-media render with ``preferCSSPageSize``, the per-page screenshots,
the pdf.js page count and text, the preview shape and the doctor checks
without a browser, poppler or a downloaded tarball. The ``deck.page`` tests
prove the screen-media measured-height render and the three source/text checks
the same way.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "deck"
RUNNER = PACKAGE / "runner.js"
NODE = shutil.which("node")
PLAYWRIGHT_VERSION = "1.64.0"
PDFJS_VERSION = "3.11.174"
PAGE_COUNT = 2
SCALE = 2
VIEWPORT = {"width": 1060, "height": 800}
RUN_SEED = 3
PREVIEW_SEED = 7
PREVIEW_KEYS = {"preview", "kind", "summary", "page_count", "pages"}
PAGE_NAMES = ["page-01.png", "page-02.png"]

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not available")

PLAYWRIGHT_STUB = """
const fs = require("node:fs");

function log(entry) {
  const file = process.env.DECK_STUB_LOG;
  if (file) fs.appendFileSync(file, JSON.stringify(entry) + "\\n");
}

function stubPages() {
  return Number(process.env.DECK_STUB_PAGES || "2");
}

module.exports = {
  chromium: {
    async launch(options) {
      log({ launch: options });
      return {
        async newPage(options) {
          log({ newPage: options });
          return {
            async goto(url, options) {
              log({ goto: url, waitUntil: options && options.waitUntil });
            },
            async evaluate(fn, arg) {
              const source = String(fn);
              log({ evaluate: source });
              if (source.includes("__pdfReady")) return stubPages();
              if (source.includes("cssRules")) return { width: 1280, height: 720 };
              if (source.includes("scrollTo")) {
                log({ scrollTo: arg });
                return true;
              }
              if (source.includes("scrollHeight")) return 900;
              return true;
            },
            async setViewportSize(options) {
              log({ setViewportSize: options });
            },
            async emulateMedia(options) {
              log({ emulateMedia: options && options.media });
            },
            async pdf(options) {
              log({ pdf: options });
              fs.writeFileSync(options.path, "%PDF-1.4\\n");
            },
            async screenshot(options) {
              log({ screenshot: options });
              fs.writeFileSync(options.path, "PNG");
            },
            locator(selector) {
              return {
                async screenshot(options) {
                  log({
                    elementScreenshot: { selector, path: options && options.path },
                  });
                  fs.writeFileSync(options.path, "PNG");
                },
              };
            },
          };
        },
        async close() {
          log({ close: true });
        },
      };
    },
  },
};
"""

PDFJS_STUB = """
module.exports = {
  getDocument() {
    return {
      promise: Promise.resolve({
        numPages: Number(process.env.DECK_STUB_PAGES || "2"),
        async getPage() {
          return {
            async getTextContent() {
              return { items: [{ str: process.env.DECK_STUB_TEXT || "" }] };
            },
          };
        },
      }),
    };
  },
};
"""

CHROME_STUB = "#!/bin/sh\nexit 0\n"

SLIDE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
@page { size: 1280px 720px; margin: 0; }
html, body { margin: 0; }
.slide { width: 1280px; height: 720px; break-after: page; }
</style></head><body>
<section class="slide">one</section><section class="slide">two</section>
</body></html>
"""

PAGE_IMG = (
    '<figure><img src="chart.png" alt="chart">\n'
    "<figcaption>Ventas por trimestre</figcaption></figure>"
)
PAGE_IMG_BARE = '<img src="chart.png" alt="chart">'
PAGE_FOOTER = '<footer class="sources">Fuentes: 1.200 casos, 0,9 %, 6,00 EUR</footer>'

PAGE_HTML = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
html, body {{ margin: 0; }}
footer {{ padding: 8px; }}
</style></head><body>
<h1>Infographic</h1>
{PAGE_IMG}
{PAGE_FOOTER}
</body></html>
"""

PAGE_NO_FOOTER_HTML = PAGE_HTML.replace(f"{PAGE_FOOTER}\n", "")
PAGE_BARE_IMG_HTML = PAGE_HTML.replace(PAGE_IMG, PAGE_IMG_BARE)
PAGE_TEXT = "1.200 casos · 0,9 % · 6,00 EUR"


def _package(root: Path) -> str:
    """The FACET_NODE_PATH value: stub playwright-core and pdfjs-dist packages."""
    playwright = root / "pkgs" / "playwright-core" / PLAYWRIGHT_VERSION
    playwright.mkdir(parents=True)
    manifest = {"name": "playwright-core", "version": PLAYWRIGHT_VERSION}
    (playwright / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    (playwright / "index.js").write_text(PLAYWRIGHT_STUB, encoding="utf-8")
    pdfjs = root / "pkgs" / "pdfjs-dist" / PDFJS_VERSION / "build"
    pdfjs.mkdir(parents=True)
    (pdfjs.parent / "package.json").write_text(
        json.dumps({"name": "pdfjs-dist", "version": PDFJS_VERSION}), encoding="utf-8"
    )
    (pdfjs / "pdf.js").write_text(PDFJS_STUB, encoding="utf-8")
    return os.pathsep.join([str(playwright), str(pdfjs.parent)])


def _tools(root: Path) -> tuple[Path, Path]:
    """A bin directory with a stub Chromium and no poppler tools at all."""
    bin_dir = root / "bin"
    bin_dir.mkdir()
    chrome = bin_dir / "chrome"
    chrome.write_text(CHROME_STUB, encoding="utf-8")
    chrome.chmod(0o755)
    return bin_dir, chrome


def _slide(root: Path) -> tuple[Path, Path]:
    piece = root / "piece"
    piece.mkdir()
    html = piece / "slides.html"
    html.write_text(SLIDE_HTML, encoding="utf-8")
    return piece, html


def _page_piece(root: Path, html: str = PAGE_HTML) -> tuple[Path, Path]:
    piece = root / "piece"
    piece.mkdir()
    file = piece / "page.html"
    file.write_text(html, encoding="utf-8")
    return piece, file


def _environment(
    root: Path,
    node_path: str,
    bin_dir: Path,
    *,
    pages: int = PAGE_COUNT,
    chrome: Path | None = None,
    path: str | None = None,
    text: str = PAGE_TEXT,
) -> dict[str, str]:
    environment = {
        "FACET_NODE": str(NODE),
        "FACET_NODE_PATH": node_path,
        "DECK_STUB_LOG": str(root / "calls.log"),
        "DECK_STUB_PAGES": str(pages),
        "DECK_STUB_TEXT": text,
        "PATH": path if path is not None else f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    environment["FACET_BROWSER"] = str(chrome) if chrome is not None else ""
    return environment


def _request(
    verb: str,
    out: Path,
    piece: Path,
    *,
    capability: str = "deck.slides",
    **fields: Any,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "protocol": 1,
        "verb": verb,
        "capability": capability,
        "inputs": fields.pop("inputs", {}),
        "out_dir": str(out),
        "piece_dir": str(piece),
        "models": {},
        "assets": fields.pop("assets", []),
    }
    request.update(fields)
    return request


def _invoke(
    root: Path, verb: str, request: dict[str, Any], env: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], Any]:
    request_file = root / "request.json"
    result_file = root / "result.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    result_file.unlink(missing_ok=True)
    done = subprocess.run(
        [str(NODE), str(RUNNER), verb, "--input", str(request_file), "--result", str(result_file)],
        cwd=root,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else None
    return done, result


def _calls(root: Path) -> list[dict[str, Any]]:
    log = root / "calls.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def _call(calls: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next(call for call in calls if key in call)


def _calls_with(calls: list[dict[str, Any]], key: str) -> list[Any]:
    return [call[key] for call in calls if key in call]


def _inputs(seed: int = RUN_SEED) -> dict[str, Any]:
    return {"source": "slides.html", "prompt": "brief", "seed": seed}


def _run(
    root: Path, out: Path, piece: Path, env: dict[str, str], *, seed: int = RUN_SEED
) -> tuple[subprocess.CompletedProcess[str], Any]:
    return _invoke(root, "run", _request("run", out, piece, inputs=_inputs(seed)), env)


def test_run_renders_a_paged_pdf_and_screenshots_one_png_per_page(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome)
    done, result = _run(tmp_path, out, piece, env)
    assert done.returncode == 0, done.stderr
    assert result is not None
    asset = result["assets"][0]
    assert (asset["file"], asset["name"], asset["kind"], asset["mime"]) == (
        "slides.pdf",
        "slides",
        "document",
        "application/pdf",
    )
    assert asset["properties"] == {"page_count": PAGE_COUNT}
    assert asset["seed"] == RUN_SEED
    assert asset["params"]["prompt"] == "brief"
    assert asset["inputs"] == [str(html)]
    assert result["tool"] == {"name": "deck", "version": PLAYWRIGHT_VERSION}
    assert (out / "slides.pdf").is_file()
    names = sorted(path.name for path in out.glob("page-*.png"))
    assert names == PAGE_NAMES
    assert not (out / "page-1.png").exists()
    calls = _calls(tmp_path)
    assert _call(calls, "launch")["launch"]["executablePath"] == str(chrome)
    new_page = _call(calls, "newPage")["newPage"]
    assert new_page["deviceScaleFactor"] == SCALE
    assert new_page["viewport"] == VIEWPORT
    goto = _call(calls, "goto")
    assert goto["goto"].startswith("file://")
    assert goto["goto"].endswith("/slides.html")
    assert goto["waitUntil"] == "networkidle"
    evaluations = _calls_with(calls, "evaluate")
    assert any("document.fonts.ready" in source for source in evaluations)
    assert any("cssRules" in source for source in evaluations)
    assert _calls_with(calls, "emulateMedia") == ["print", "screen"]
    assert _calls_with(calls, "setViewportSize") == [{"width": 1280, "height": 720}]
    pdf = _call(calls, "pdf")["pdf"]
    assert pdf["preferCSSPageSize"] is True
    assert pdf["printBackground"] is True
    assert pdf["path"] == str(out / "slides.pdf")
    shots = _calls_with(calls, "screenshot")
    assert [shot["path"] for shot in shots] == [
        str(out / "page-1.png"),
        str(out / "page-2.png"),
    ]
    assert all(shot.get("clip") is None for shot in shots)
    assert _calls_with(calls, "scrollTo") == [0, 720]
    assert _call(calls, "close")["close"] is True


def test_run_writes_one_png_per_pdf_page(tmp_path: Path) -> None:
    """The screenshot count follows the PDF's own page count, not a fixed two."""
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, pages=3, chrome=chrome)
    done, result = _run(tmp_path, out, piece, env)
    assert done.returncode == 0, done.stderr
    assert result["assets"][0]["properties"] == {"page_count": 3}
    assert sorted(path.name for path in out.glob("page-*.png")) == [
        "page-01.png",
        "page-02.png",
        "page-03.png",
    ]
    calls = _calls(tmp_path)
    assert _calls_with(calls, "scrollTo") == [0, 720, 1440]
    assert [shot["path"] for shot in _calls_with(calls, "screenshot")] == [
        str(out / "page-1.png"),
        str(out / "page-2.png"),
        str(out / "page-3.png"),
    ]


def test_run_needs_no_host_poppler(tmp_path: Path) -> None:
    """An empty PATH still runs: Chromium comes from FACET_BROWSER, pages from pdf.js."""
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome, path=str(empty))
    done, result = _run(tmp_path, out, piece, env)
    assert done.returncode == 0, done.stderr
    assert result is not None
    assert sorted(path.name for path in out.glob("page-*.png")) == PAGE_NAMES


def test_run_refuses_a_missing_slide_html(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome)
    inputs = {"source": "missing.html", "prompt": "brief", "seed": RUN_SEED}
    done, result = _invoke(tmp_path, "run", _request("run", out, piece, inputs=inputs), env)
    assert done.returncode != 0
    assert result is None
    assert "source" in done.stderr


def test_verify_passes_when_the_page_count_matches(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome)
    _done, _result = _run(tmp_path, out, piece, env)
    asset = out / "slides.pdf"
    request = _request("verify", out, piece, inputs=_inputs(), assets=[str(asset)])
    done, result = _invoke(tmp_path, "verify", request, env)
    assert done.returncode == 0, done.stderr
    assert result["assets"][0] == {
        "file": "slides.pdf",
        "passed": True,
        "metrics": {"page_count": PAGE_COUNT},
        "thresholds": {},
        "verifier": "chromium-pdfjs",
    }


def test_verify_falls_back_to_pdfjs_when_no_pages_are_rendered(tmp_path: Path) -> None:
    """A placed asset keeps no page PNGs; pdf.js still counts the PDF's pages."""
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome)
    _done, _result = _run(tmp_path, out, piece, env)
    asset = out / "slides.pdf"
    record = out / "slides.pdf.facet.json"
    record.write_text(
        json.dumps({"verification": {"metrics": {"page_count": PAGE_COUNT}}}), encoding="utf-8"
    )
    for page in out.glob("page-*.png"):
        page.unlink()
    request = _request("verify", out, piece, inputs=_inputs(), assets=[str(asset)])
    done, result = _invoke(tmp_path, "verify", request, env)
    assert done.returncode == 0, done.stderr
    assert result["assets"][0]["metrics"] == {"page_count": PAGE_COUNT}
    assert result["assets"][0]["verifier"] == "chromium-pdfjs"


def test_verify_fails_runner_failed_when_a_page_is_missing(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome)
    _done, _result = _run(tmp_path, out, piece, env)
    asset = out / "slides.pdf"
    record = out / "slides.pdf.facet.json"
    record.write_text(
        json.dumps({"verification": {"metrics": {"page_count": PAGE_COUNT}}}), encoding="utf-8"
    )
    (out / "page-02.png").unlink()
    request = _request("verify", out, piece, inputs=_inputs(), assets=[str(asset)])
    done, result = _invoke(tmp_path, "verify", request, env)
    assert done.returncode != 0
    assert result is None
    assert "page_count" in done.stderr


def test_preview_writes_the_core_document_fixture_keys(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome)
    _done, _result = _run(tmp_path, out, piece, env)
    asset = out / "slides.pdf"
    request = _request("preview", out, piece, inputs=_inputs(PREVIEW_SEED), assets=[str(asset)])
    done, result = _invoke(tmp_path, "preview", request, env)
    assert done.returncode == 0, done.stderr
    assert result["assets"][0] == {
        "file": "slides.pdf",
        "preview": "slides.pdf.preview.json",
        "images": [],
    }
    data = json.loads((out / "slides.pdf.preview.json").read_text(encoding="utf-8"))
    assert set(data) == PREVIEW_KEYS
    assert data["preview"] == 1
    assert data["kind"] == "document"
    assert data["page_count"] == PAGE_COUNT
    assert data["pages"] == PAGE_NAMES
    assert f"seed {PREVIEW_SEED}" in data["summary"]
    assert all((out / name).is_file() for name in data["pages"])


def test_preview_rasterizes_a_placed_pdf_with_no_source_html(tmp_path: Path) -> None:
    """A bare PDF asset previews through pdfgrab.html: pdf.js pages, canvas shots."""
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    placed = out / "placed.pdf"
    placed.write_text("%PDF-1.4\n", encoding="utf-8")
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome)
    inputs = {"prompt": "brief", "seed": PREVIEW_SEED}
    request = _request("preview", out, piece, inputs=inputs, assets=[str(placed)])
    done, result = _invoke(tmp_path, "preview", request, env)
    assert done.returncode == 0, done.stderr
    assert result["assets"][0]["file"] == "placed.pdf"
    gotos = _calls_with(_calls(tmp_path), "goto")
    assert any("pdfgrab.html" in url and "placed.pdf" in url for url in gotos)
    elements = _calls_with(_calls(tmp_path), "elementScreenshot")
    assert [element["selector"] for element in elements] == [
        'canvas[data-page="1"]',
        'canvas[data-page="2"]',
    ]
    data = json.loads((out / "placed.pdf.preview.json").read_text(encoding="utf-8"))
    assert data["page_count"] == PAGE_COUNT
    assert data["pages"] == PAGE_NAMES
    assert all((out / name).is_file() for name in data["pages"])


def test_doctor_quick_reports_node_and_chromium_and_no_poppler(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome)
    done, result = _invoke(tmp_path, "doctor", _request("doctor", out, piece), env)
    assert done.returncode == 0, done.stderr
    checks = result["checks"]
    assert [check["name"] for check in checks] == ["node", "chromium"]
    assert all(check["ok"] for check in checks)


def test_doctor_and_run_fail_without_the_facet_browser(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, _chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=None)
    done, result = _invoke(tmp_path, "doctor", _request("doctor", out, piece), env)
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["chromium"]["ok"] is False
    assert checks["chromium"]["fix"] == "facet pull deck"
    done, result = _run(tmp_path, out, piece, env)
    assert done.returncode != 0
    assert result is None
    assert "FACET_BROWSER is not set or not executable; run facet pull deck" in done.stderr


def test_doctor_full_renders_a_one_slide_throwaway(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, pages=1, chrome=chrome)
    request = _request("doctor", out, piece, depth="full")
    done, result = _invoke(tmp_path, "doctor", request, env)
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["render"]["ok"] is True
    assert (out / "doctor-deck.pdf").is_file()
    assert (out / "page-01.png").is_file()


def test_an_unknown_verb_is_refused(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome)
    done, result = _invoke(tmp_path, "bogus", _request("bogus", out, piece), env)
    assert done.returncode != 0
    assert result is None
    assert "unknown verb" in done.stderr


def _page_run(
    root: Path, out: Path, piece: Path, env: dict[str, str], *, seed: int = RUN_SEED
) -> tuple[subprocess.CompletedProcess[str], Any]:
    inputs = {"source": "page.html", "prompt": "brief", "seed": seed}
    request = _request("run", out, piece, capability="deck.page", inputs=inputs)
    return _invoke(root, "run", request, env)


def test_page_run_renders_a_one_page_pdf_through_the_screen_path(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, html = _page_piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, pages=1, chrome=chrome)
    done, result = _page_run(tmp_path, out, piece, env)
    assert done.returncode == 0, done.stderr
    assert result is not None
    asset = result["assets"][0]
    assert (asset["file"], asset["name"], asset["kind"], asset["mime"]) == (
        "page.pdf",
        "page",
        "document",
        "application/pdf",
    )
    assert asset["properties"] == {"page_count": 1}
    assert asset["seed"] == RUN_SEED
    assert asset["params"]["prompt"] == "brief"
    assert asset["inputs"] == [str(html)]
    assert result["tool"] == {"name": "deck", "version": PLAYWRIGHT_VERSION}
    assert (out / "page.pdf").is_file()
    assert [path.name for path in out.glob("page-*.png")] == ["page-01.png"]
    calls = _calls(tmp_path)
    new_page = _call(calls, "newPage")["newPage"]
    assert new_page["deviceScaleFactor"] == SCALE
    assert new_page["viewport"] == VIEWPORT
    goto = _call(calls, "goto")
    assert goto["waitUntil"] == "networkidle"
    evaluations = _calls_with(calls, "evaluate")
    assert any("document.fonts.ready" in source for source in evaluations)
    assert any("scrollHeight" in source for source in evaluations)
    assert _calls_with(calls, "emulateMedia") == ["screen"]
    pdf = _call(calls, "pdf")["pdf"]
    assert pdf["printBackground"] is True
    assert pdf["width"] == "1060px"
    assert pdf["height"] == "902px"
    assert pdf["pageRanges"] == "1"
    assert "preferCSSPageSize" not in pdf
    assert pdf["path"] == str(out / "page.pdf")
    assert _calls_with(calls, "setViewportSize") == [{"width": 1060, "height": 902}]
    shot = _call(calls, "screenshot")["screenshot"]
    assert shot["path"] == str(out / "page-1.png")
    assert shot.get("clip") is None
    assert _call(calls, "close")["close"] is True


def test_page_run_fails_runner_failed_without_a_sources_footer(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _page_piece(tmp_path, PAGE_NO_FOOTER_HTML)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome)
    done, result = _page_run(tmp_path, out, piece, env)
    assert done.returncode != 0
    assert result is None
    assert "footer-sources" in done.stderr
    assert not (tmp_path / "calls.log").exists()


def test_page_run_fails_runner_failed_on_a_bare_image(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _page_piece(tmp_path, PAGE_BARE_IMG_HTML)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome)
    done, result = _page_run(tmp_path, out, piece, env)
    assert done.returncode != 0
    assert result is None
    assert "captioned-images" in done.stderr
    assert not (tmp_path / "calls.log").exists()


def test_page_run_fails_runner_failed_on_an_english_number(tmp_path: Path) -> None:
    node_path = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _page_piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, node_path, bin_dir, chrome=chrome, text="8.04 por ciento")
    done, result = _page_run(tmp_path, out, piece, env)
    assert done.returncode != 0
    assert result is None
    assert "spanish-numbers" in done.stderr
    assert "8.04" in done.stderr
    assert not list(out.glob("page-*.png"))
