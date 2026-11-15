"""The mermaid runner against fixture npm trees and a stub mermaid-cli.

The runner is a subprocess of the host ``node``. Its ``FACET_NODE_PATH``
points at fixture package directories carrying only ``package.json``; the
first one holds a stub ``src/cli.js`` that records every call and writes SVG
and PNG fixtures for ``-o``. That proves the link plan (dependencies, peers,
linux-x64 optionals, foreign-platform skips, hyphen and bare-partial ranges),
the header traps failing before the CLI runs, the FACET_BROWSER gate and the
image preview — without downloading a tarball or a browser.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "mermaid"
RUNNER = PACKAGE / "runner.js"
NODE = shutil.which("node")
BROWSER = shutil.which("sh") or "/bin/sh"
BARE_IMPORT_RE = re.compile(r"""(?:require\s*\(\s*|from\s+|import\s*\(\s*)["']([^"']+)["']""")
PREVIEW_FIELDS = {
    "preview",
    "kind",
    "summary",
    "name",
    "prompt",
    "seed",
    "width",
    "height",
}
RENDER_CALLS = 2  # one mmdc for the SVG, one for the PNG
SVG_TAG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"'
    ' viewBox="0 0 640 480"></svg>\n'
)

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not available")

STUB = """
const fs = require("node:fs");
const path = require("node:path");

const args = process.argv.slice(2);
const log = process.env.MMDC_STUB_LOG;
if (log) {
  fs.appendFileSync(
    log,
    `${JSON.stringify({
      args,
      skipDownload: process.env.PUPPETEER_SKIP_DOWNLOAD,
      chrome: process.env.FACET_BROWSER,
      cwd: process.cwd(),
    })}\\n`,
  );
}
const out = args[args.indexOf("-o") + 1];
fs.mkdirSync(path.dirname(out), { recursive: true });
if (out.endsWith(".png")) {
  const png = Buffer.alloc(33);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(png);
  png.writeUInt32BE(13, 8);
  png.write("IHDR", 12, "ascii");
  png.writeUInt32BE(640, 16);
  png.writeUInt32BE(480, 20);
  fs.writeFileSync(out, png);
} else {
  fs.writeFileSync(
    out,
    '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"' +
      ' viewBox="0 0 640 480"><text>x</text></svg>\\n',
  );
}
"""

VALID_MMD = """---
config:
  theme: base
  themeVariables:
    fontFamily: "Ubuntu"
    fontSize: "22px"
---
flowchart LR
  a["A"] --> b["B"]
"""


def _png_bytes(width: int = 640, height: int = 480) -> bytes:
    png = bytearray(33)
    png[:8] = b"\x89PNG\r\n\x1a\n"
    struct.pack_into(">I", png, 8, 13)
    png[12:16] = b"IHDR"
    struct.pack_into(">II", png, 16, width, height)
    return bytes(png)


def _package(root: Path, name: str, version: str, **extra: Any) -> Path:
    directory = root / "pkgs" / name.replace("@", "").replace("/", "__") / version
    directory.mkdir(parents=True)
    manifest = {"name": name, "version": version, **extra}
    (directory / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def _fixture(root: Path) -> dict[str, Path]:
    """A small tree exercising deps, peers, optionals and odd ranges."""
    packages = {
        "cli": _package(
            root,
            "@mermaid-js/mermaid-cli",
            "12.0.0",
            dependencies={"commander": "^15.0.0", "d3-array": "1 - 2"},
            peerDependencies={"ws": "^8.0.0"},
            optionalDependencies={"@napi-rs/canvas-win32-x64-msvc": "0.1.100"},
        ),
        "commander": _package(root, "commander", "15.1.0"),
        "d3low": _package(root, "d3-array", "2.12.1"),
        "d3high": _package(root, "d3-array", "3.2.5"),
        "ws": _package(root, "ws", "8.22.1"),
    }
    stub = packages["cli"] / "src" / "cli.js"
    stub.parent.mkdir()
    stub.write_text(STUB, encoding="utf-8")
    return packages


def _dirs(packages: dict[str, Path]) -> list[Path]:
    return [packages[name] for name in ("cli", "commander", "d3low", "d3high", "ws")]


def _piece(root: Path, text: str = VALID_MMD) -> tuple[Path, Path]:
    piece = root / "piece"
    piece.mkdir(exist_ok=True)
    diagram = piece / "ciclo.mmd"
    diagram.write_text(text, encoding="utf-8")
    return piece, diagram


def _environment(
    root: Path, dirs: list[Path], *, browser: bool = True, path: str | None = None
) -> dict[str, str]:
    return {
        "FACET_NODE": str(NODE),
        "FACET_NODE_PATH": os.pathsep.join(str(directory) for directory in dirs),
        "FACET_BROWSER": BROWSER if browser else "",
        "MMDC_STUB_LOG": str(root / "calls.log"),
        "PATH": path if path is not None else os.environ.get("PATH", ""),
    }


def _request(verb: str, out: Path, piece: Path, **inputs: Any) -> dict[str, Any]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "mermaid.diagram",
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(piece),
        "models": {},
        "assets": [],
    }


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


def _link(package_dir: Path, name: str) -> Path | None:
    link = package_dir / "node_modules" / name
    return Path(os.readlink(link)) if link.is_symlink() else None


def test_the_runner_imports_only_node_builtins() -> None:
    """The staged script must run before any npm dependency exists."""
    for spec in BARE_IMPORT_RE.findall(RUNNER.read_text(encoding="utf-8")):
        assert spec.startswith("node:") or spec.startswith("."), spec


def test_run_renders_svg_and_png_through_the_stub_cli(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _diagram = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, diagram="ciclo.mmd"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    assert result is not None
    calls = _calls(tmp_path)
    assert len(calls) == RENDER_CALLS
    svg_call, png_call = calls
    for call in calls:
        args = call["args"]
        assert call["skipDownload"] == "1"
        assert call["chrome"] == BROWSER
        assert args[args.index("-i") + 1].endswith("ciclo.mmd")
        assert args[args.index("-b") + 1] == "white"
        assert "-p" in args
        icon_args = args[args.index("--iconPacksNamesAndUrls") + 1 :]
        assert icon_args[0].startswith("logos#https://unpkg.com/@iconify-json/logos@")
        assert icon_args[1].startswith("mdi#https://unpkg.com/@iconify-json/mdi@")
    assert svg_call["args"][svg_call["args"].index("-o") + 1] == str(out / "ciclo.svg")
    assert "-s" not in svg_call["args"]
    png_args = png_call["args"]
    assert png_args[png_args.index("-o") + 1] == str(out / "ciclo.png")
    assert png_args[png_args.index("-s") + 1] == "2"
    assert (out / "ciclo.svg").is_file()
    assert (out / "ciclo.png").is_file()
    assets = result["assets"]
    assert [asset["file"] for asset in assets] == ["ciclo.svg", "ciclo.png"]
    assert all(asset["kind"] == "image" for asset in assets)
    assert result["tool"] == {"name": "mermaid-cli", "version": "12.0.0"}


def test_run_links_dependencies_peers_and_skips_foreign_optionals(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _diagram = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, _result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, diagram="ciclo.mmd"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    cli = packages["cli"]
    assert _link(cli, "commander") == packages["commander"]
    # The hyphen range "1 - 2" resolves to the satisfying 2.x, not 3.2.5.
    assert _link(cli, "d3-array") == packages["d3low"]
    assert _link(cli, "ws") == packages["ws"]
    assert not (cli / "node_modules" / "@napi-rs").exists()


HEADER_FF_LIST = (
    "---\nconfig:\n  theme: base\n  themeVariables:\n"
    '    fontFamily: ["Ubuntu", "sans-serif"]\n---\nflowchart LR\n'
)
HEADER_FF_BLOCK = (
    "---\nconfig:\n  theme: base\n  themeVariables:\n    fontFamily:\n"
    "      - Ubuntu\n      - sans-serif\n---\nflowchart LR\n"
)
HEADER_FF_SANS = (
    "---\nconfig:\n  theme: base\n  themeVariables:\n"
    '    fontFamily: "Ubuntu Sans"\n---\nflowchart LR\n'
)
HEADER_NO_THEME = '---\nconfig:\n  themeVariables:\n    fontFamily: "Ubuntu"\n---\nflowchart LR\n'


@pytest.mark.parametrize(
    ("text", "trap"),
    [
        ("flowchart LR\n  a --> b\n", "YAML header"),
        (HEADER_NO_THEME, "theme"),
        (HEADER_FF_LIST, "fontFamily"),
        (HEADER_FF_BLOCK, "fontFamily"),
        (HEADER_FF_SANS, "fontFamily"),
    ],
)
def test_a_header_trap_fails_before_the_cli_runs(tmp_path: Path, text: str, trap: str) -> None:
    packages = _fixture(tmp_path)
    piece, _diagram = _piece(tmp_path, text)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, diagram="ciclo.mmd"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode != 0
    assert result is None
    assert "mermaid runner:" in done.stderr
    assert trap in done.stderr
    assert _calls(tmp_path) == []
    assert not (out / "ciclo.svg").exists()


def test_run_without_chrome_fails_and_never_calls_the_cli(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _diagram = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, diagram="ciclo.mmd"),
        _environment(tmp_path, _dirs(packages), browser=False),
    )
    assert done.returncode != 0
    assert result is None
    assert "FACET_BROWSER" in done.stderr
    assert "facet pull mermaid" in done.stderr
    assert _calls(tmp_path) == []


def test_doctor_reports_the_cli_and_the_chrome_fix(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _diagram = _piece(tmp_path)
    env = _environment(tmp_path, _dirs(packages), browser=False)
    done, result = _invoke(tmp_path, "doctor", _request("doctor", tmp_path, piece), env)
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["mermaid-cli"]["ok"] is True
    assert "12.0.0" in checks["mermaid-cli"]["detail"]
    chrome = checks["chrome"]
    assert chrome["ok"] is False
    assert "FACET_BROWSER" in chrome["detail"]
    assert chrome["fix"] == "facet pull mermaid"


def test_doctor_reports_chrome_when_present(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _diagram = _piece(tmp_path)
    done, result = _invoke(
        tmp_path,
        "doctor",
        _request("doctor", tmp_path, piece),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["chrome"]["ok"] is True
    assert checks["chrome"]["fix"] == ""


def test_verify_accepts_svg_and_png_and_rejects_a_bad_file(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _diagram = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    svg = out / "ciclo.svg"
    svg.write_text(SVG_TAG, encoding="utf-8")
    png = out / "ciclo.png"
    png.write_bytes(_png_bytes())
    bad = out / "notes.txt"
    bad.write_text("not an image\n", encoding="utf-8")
    request = _request("verify", out, piece, diagram="ciclo.mmd")
    request["assets"] = [str(svg), str(png), str(bad)]
    done, result = _invoke(tmp_path, "verify", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    passed, png_verdict, failed = result["assets"]
    assert passed["file"] == "ciclo.svg" and passed["passed"] is True
    assert passed["verifier"] == "mermaid"
    assert png_verdict["file"] == "ciclo.png" and png_verdict["passed"] is True
    assert failed["file"] == "notes.txt" and failed["passed"] is False


def test_preview_writes_the_image_fields(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _diagram = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    png = out / "ciclo.png"
    png.write_bytes(_png_bytes())
    svg = out / "ciclo.svg"
    svg.write_text(SVG_TAG, encoding="utf-8")
    request = _request("preview", out, piece, diagram="ciclo.mmd")
    request["assets"] = [str(png), str(svg)]
    done, result = _invoke(tmp_path, "preview", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    assert [entry["file"] for entry in result["assets"]] == ["ciclo.png", "ciclo.svg"]
    data = json.loads((out / "ciclo.png.preview.json").read_text(encoding="utf-8"))
    assert set(data) == PREVIEW_FIELDS
    assert data["preview"] == 1
    assert data["kind"] == "image"
    assert data["summary"] == "ciclo · 640x480 · mermaid"
    assert data["name"] == "ciclo"
    assert data["prompt"] == "flowchart LR diagram · ciclo"
    assert data["seed"] == 0
    assert (data["width"], data["height"]) == (640, 480)
    svg_data = json.loads((out / "ciclo.svg.preview.json").read_text(encoding="utf-8"))
    assert (svg_data["width"], svg_data["height"]) == (640, 480)
