"""The deck runner against a stub playwright, a stub pdftoppm and a stub Chromium.

The runner is a subprocess of the host ``node``. Its ``FACET_NODE_PATH`` points
at a fixture ``playwright-core`` package whose entry records every browser call
and writes a stub PDF; ``PATH`` carries a stub ``pdftoppm`` that writes one PNG
per page with single-digit names (the real poppler does the same for small
counts). That proves the print-media render with ``preferCSSPageSize``, the
font wait, the page-name normalization to ``page-01.png``, the page-count
contract, the preview shape and the doctor fixes without a browser, poppler or
a downloaded tarball.
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
PAGE_COUNT = 2
SCALE = 2
VIEWPORT = {"width": 1060, "height": 800}
RUN_SEED = 3
PREVIEW_SEED = 7
POPPLER_VERSION = "pdftoppm version 24.02.0"
PREVIEW_KEYS = {"preview", "kind", "summary", "page_count", "pages"}
PAGE_NAMES = ["page-01.png", "page-02.png"]
POPPLER_FIX = "sudo apt-get install -y poppler-utils"

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not available")

PLAYWRIGHT_STUB = """
const fs = require("node:fs");

function log(entry) {
  const file = process.env.DECK_STUB_LOG;
  if (file) fs.appendFileSync(file, JSON.stringify(entry) + "\\n");
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
            async evaluate(fn) {
              log({ evaluate: String(fn) });
              return true;
            },
            async emulateMedia(options) {
              log({ emulateMedia: options && options.media });
            },
            async pdf(options) {
              log({ pdf: options });
              fs.writeFileSync(options.path, "%PDF-1.4\\n");
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

POPPLER_STUB = """#!/bin/sh
if [ "$1" = "-v" ]; then
  echo "pdftoppm version 24.02.0" >&2
  exit 0
fi
pages="${DECK_STUB_PAGES:-2}"
i=1
while [ "$i" -le "$pages" ]; do
  printf '\\211PNG\\r\\n' > "${3}-${i}.png"
  i=$((i + 1))
done
"""

PDFINFO_STUB = """#!/bin/sh
echo "Pages: ${DECK_STUB_PAGES:-2}"
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


def _package(root: Path) -> Path:
    directory = root / "pkgs" / "playwright-core" / PLAYWRIGHT_VERSION
    directory.mkdir(parents=True)
    manifest = {"name": "playwright-core", "version": PLAYWRIGHT_VERSION}
    (directory / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "index.js").write_text(PLAYWRIGHT_STUB, encoding="utf-8")
    return directory


def _tools(root: Path, *, pages: int = PAGE_COUNT, poppler: bool = True) -> tuple[Path, Path]:
    """A bin directory with the stub poppler tools (optionally) and a stub Chromium."""
    bin_dir = root / "bin"
    bin_dir.mkdir()
    if poppler:
        for name, stub in (("pdftoppm", POPPLER_STUB), ("pdfinfo", PDFINFO_STUB)):
            script = bin_dir / name
            script.write_text(stub, encoding="utf-8")
            script.chmod(0o755)
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


def _environment(
    root: Path,
    package_dir: Path,
    bin_dir: Path,
    *,
    pages: int = PAGE_COUNT,
    chrome: Path | None = None,
    path: str | None = None,
) -> dict[str, str]:
    environment = {
        "FACET_NODE": str(NODE),
        "FACET_NODE_PATH": str(package_dir),
        "DECK_STUB_LOG": str(root / "calls.log"),
        "DECK_STUB_PAGES": str(pages),
        "PATH": path if path is not None else f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    if chrome is not None:
        environment["CHROME_PATH"] = str(chrome)
    return environment


def _request(verb: str, out: Path, piece: Path, **fields: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "protocol": 1,
        "verb": verb,
        "capability": "deck.slides",
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


def _inputs(seed: int = RUN_SEED) -> dict[str, Any]:
    return {"fuente": "slides.html", "prompt": "brief", "seed": seed}


def _run(
    root: Path, out: Path, piece: Path, env: dict[str, str], *, seed: int = RUN_SEED
) -> tuple[subprocess.CompletedProcess[str], Any]:
    return _invoke(root, "run", _request("run", out, piece, inputs=_inputs(seed)), env)


def test_run_renders_a_paged_pdf_and_normalizes_the_page_pngs(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, package, bin_dir, chrome=chrome)
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
    assert calls[0]["launch"]["executablePath"] == str(chrome)
    assert calls[1]["newPage"]["deviceScaleFactor"] == SCALE
    assert calls[1]["newPage"]["viewport"] == VIEWPORT
    assert calls[2]["goto"].endswith("/slides.html")
    assert calls[2]["goto"].startswith("file://")
    assert calls[2]["waitUntil"] == "networkidle"
    assert "document.fonts.ready" in calls[3]["evaluate"]
    assert calls[4]["emulateMedia"] == "print"
    assert calls[5]["pdf"]["preferCSSPageSize"] is True
    assert calls[5]["pdf"]["printBackground"] is True
    assert calls[5]["pdf"]["path"] == str(out / "slides.pdf")
    assert calls[6]["close"] is True


def test_run_refuses_a_missing_slide_html(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, package, bin_dir, chrome=chrome)
    inputs = {"fuente": "missing.html", "prompt": "brief", "seed": RUN_SEED}
    done, result = _invoke(tmp_path, "run", _request("run", out, piece, inputs=inputs), env)
    assert done.returncode != 0
    assert result is None
    assert "fuente" in done.stderr


def test_run_requires_a_browser_and_poppler(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path, poppler=False)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()
    env = _environment(tmp_path, package, bin_dir, chrome=chrome, path=str(empty))
    done, result = _run(tmp_path, out, piece, env)
    assert done.returncode != 0
    assert result is None
    assert "poppler-utils" in done.stderr


def test_verify_passes_when_the_page_count_matches(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, package, bin_dir, chrome=chrome)
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
        "verifier": "pdftoppm",
    }


def test_verify_falls_back_to_pdfinfo_when_no_pages_are_rendered(tmp_path: Path) -> None:
    """A placed asset keeps no page PNGs; the PDF's own count still verifies."""
    package = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, package, bin_dir, chrome=chrome)
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


def test_verify_fails_runner_failed_when_a_page_is_missing(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, package, bin_dir, chrome=chrome)
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
    package = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, package, bin_dir, chrome=chrome)
    _done, _result = _run(tmp_path, out, piece, env)
    for page in out.glob("page-*.png"):
        page.unlink()
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


def test_doctor_quick_reports_the_missing_poppler_fix(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path, poppler=False)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()
    env = _environment(tmp_path, package, bin_dir, chrome=chrome, path=str(empty))
    done, result = _invoke(tmp_path, "doctor", _request("doctor", out, piece), env)
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["node"]["ok"] is True
    assert checks["chromium"]["ok"] is True
    assert checks["pdftoppm"]["ok"] is False
    assert checks["pdftoppm"]["fix"] == POPPLER_FIX


def test_doctor_quick_finds_poppler_and_its_version(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, package, bin_dir, chrome=chrome)
    done, result = _invoke(tmp_path, "doctor", _request("doctor", out, piece), env)
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["chromium"]["ok"] is True
    assert checks["pdftoppm"]["ok"] is True
    assert POPPLER_VERSION in checks["pdftoppm"]["detail"]


def test_doctor_full_renders_a_one_slide_throwaway(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path, pages=1)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, package, bin_dir, pages=1, chrome=chrome)
    request = _request("doctor", out, piece, depth="full")
    done, result = _invoke(tmp_path, "doctor", request, env)
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["render"]["ok"] is True
    assert (out / "doctor-deck.pdf").is_file()
    assert (out / "page-01.png").is_file()


def test_an_unknown_verb_is_refused(tmp_path: Path) -> None:
    package = _package(tmp_path)
    bin_dir, chrome = _tools(tmp_path)
    piece, _html = _slide(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, package, bin_dir, chrome=chrome)
    done, result = _invoke(tmp_path, "bogus", _request("bogus", out, piece), env)
    assert done.returncode != 0
    assert result is None
    assert "unknown verb" in done.stderr
