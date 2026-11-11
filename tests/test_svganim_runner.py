"""The svganim runner against a fixture npm tree and a stub sharp.

The runner is a subprocess of the host ``node``. Its ``FACET_NODE_PATH``
points at fixture package directories carrying only ``package.json`` and an
``index.js``: a fake ``opentype.js`` the script requires, and a stub ``sharp``
that records the arguments and writes a 1280x720 PNG. That proves the script
runs with the data path, the SVG guards fail before anything is written, the
PNG comes from sharp at 2x, and the image preview carries the script basename —
without downloading a tarball or a browser.
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
PACKAGE = ROOT / "packages" / "svganim"
RUNNER = PACKAGE / "runner.js"
NODE = shutil.which("node")
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
DENSITY = 144
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
GOOD_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"'
    ' viewBox="0 0 640 480">'
    "<style>@keyframes subir{from{opacity:0}to{opacity:1}}</style>"
    '<path d="M0 0h10v10z"/></svg>\n'
)

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not available")

SHARP_STUB = """
const fs = require("node:fs");

module.exports = function sharp(input, options) {
  const log = process.env.SHARP_STUB_LOG;
  if (log) {
    fs.appendFileSync(
      log,
      `${JSON.stringify({ text: String(input), density: options && options.density })}\\n`,
    );
  }
  return {
    png() {
      return {
        async toFile(file) {
          const png = Buffer.alloc(33);
          Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(png);
          png.writeUInt32BE(13, 8);
          png.write("IHDR", 12, "ascii");
          png.writeUInt32BE(1280, 16);
          png.writeUInt32BE(720, 20);
          fs.writeFileSync(file, png);
        },
      };
    },
  };
};
"""

SCRIPT = """
const fs = require("node:fs");
const opentype = require("opentype.js");

const data = fs.readFileSync(process.argv[2], "utf8").trim();
process.stdout.write(
  '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"' +
    ' viewBox="0 0 1280 720">' +
    '<style>@keyframes subir{from{opacity:0}to{opacity:1}}</style>' +
    `<path d="M0 0h10v10z" data-opentype="${opentype.version}"/>` +
    `<desc>${data}</desc>` +
    "</svg>",
);
"""

TEXT_SCRIPT = """
const fs = require("node:fs");
require("opentype.js");

fs.readFileSync(process.argv[2], "utf8");
process.stdout.write(
  '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="120">' +
    '<style>@keyframes subir{from{opacity:0}to{opacity:1}}</style>' +
    '<text x="8" y="60">Hola</text>' +
    "</svg>",
);
"""

NO_KEYFRAMES_SCRIPT = """
const fs = require("node:fs");

fs.readFileSync(process.argv[2], "utf8");
process.stdout.write(
  '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="120">' +
    '<path d="M0 0h10v10z"/></svg>',
);
"""

SCRIPT_WITH_TAG = """
const fs = require("node:fs");

fs.readFileSync(process.argv[2], "utf8");
process.stdout.write(
  '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="120">' +
    '<script>alert(1)</script>' +
    '<style>@keyframes subir{from{opacity:0}to{opacity:1}}</style>' +
    '<path d="M0 0h10v10z"/></svg>',
);
"""


def _png_bytes(width: int = 640, height: int = 480) -> bytes:
    png = bytearray(33)
    png[:8] = PNG_MAGIC
    struct.pack_into(">I", png, 8, 13)
    png[12:16] = b"IHDR"
    struct.pack_into(">II", png, 16, width, height)
    return bytes(png)


def _package(root: Path, name: str, version: str, index_js: str) -> Path:
    directory = root / "pkgs" / name.replace("@", "").replace("/", "__") / version
    directory.mkdir(parents=True)
    manifest = {"name": name, "version": version, "main": "index.js"}
    (directory / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "index.js").write_text(index_js, encoding="utf-8")
    return directory


def _fixture(root: Path) -> dict[str, Path]:
    return {
        "opentype.js": _package(
            root, "opentype.js", "2.0.0", 'module.exports = { version: "2.0.0" };\n'
        ),
        "sharp": _package(root, "sharp", "0.35.5", SHARP_STUB),
    }


def _dirs(packages: dict[str, Path]) -> list[Path]:
    return [packages["opentype.js"], packages["sharp"]]


def _piece(
    root: Path, script_body: str = SCRIPT, name: str = "banner-navidad.cjs"
) -> tuple[Path, Path, Path]:
    piece = root / "piece"
    piece.mkdir(exist_ok=True)
    script = piece / name
    script.write_text(script_body, encoding="utf-8")
    data = piece / "banner-navidad.json"
    data.write_text('{"titulo": "Feliz Navidad"}', encoding="utf-8")
    return piece, script, data


def _environment(root: Path, dirs: list[Path]) -> dict[str, str]:
    return {
        "FACET_NODE": str(NODE),
        "FACET_NODE_PATH": os.pathsep.join(str(directory) for directory in dirs),
        "SHARP_STUB_LOG": str(root / "sharp.log"),
        "PATH": os.environ.get("PATH", ""),
    }


def _request(verb: str, out: Path, piece: Path, **inputs: Any) -> dict[str, Any]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "svganim.bake",
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


def _sharp_calls(root: Path) -> list[dict[str, Any]]:
    log = root / "sharp.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def test_the_runner_imports_only_node_builtins() -> None:
    """The staged script must run before any npm dependency exists."""
    specs = BARE_IMPORT_RE.findall(RUNNER.read_text(encoding="utf-8"))
    assert "sharp" not in specs
    for spec in specs:
        assert spec.startswith("node:") or spec.startswith("."), spec


def test_run_bakes_the_svg_injects_the_data_and_renders_the_png(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, script, data = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, script="banner-navidad.cjs", data="banner-navidad.json"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    svg = out / "banner-navidad.svg"
    png = out / "banner-navidad.png"
    assert svg.is_file()
    assert png.is_file()
    text = svg.read_text(encoding="utf-8")
    assert "Feliz Navidad" in text
    assert 'data-opentype="2.0.0"' in text
    assert "@keyframes" in text
    calls = _sharp_calls(tmp_path)
    assert len(calls) == 1
    assert calls[0]["density"] == DENSITY
    assert "@keyframes" in calls[0]["text"]
    assert png.read_bytes()[:8] == PNG_MAGIC
    assert result is not None
    assert result["tool"] == {"name": "opentype.js", "version": "2.0.0"}
    assets = result["assets"]
    assert [asset["file"] for asset in assets] == ["banner-navidad.svg", "banner-navidad.png"]
    assert [asset["mime"] for asset in assets] == ["image/svg+xml", "image/png"]
    assert all(asset["kind"] == "image" for asset in assets)
    assert all(asset["inputs"] == [str(script), str(data)] for asset in assets)


def test_a_text_element_fails_naming_the_opentype_rule(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _script, _data = _piece(tmp_path, TEXT_SCRIPT, "texto-crudo.cjs")
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, script="texto-crudo.cjs", data="banner-navidad.json"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 1
    assert result is None
    assert "svganim runner:" in done.stderr
    assert "opentype.js" in done.stderr
    assert "<path>" in done.stderr
    assert not (out / "texto-crudo.svg").exists()
    assert _sharp_calls(tmp_path) == []


@pytest.mark.parametrize(
    ("script_body", "name", "trap"),
    [
        (NO_KEYFRAMES_SCRIPT, "sin-keyframes.cjs", "@keyframes"),
        (SCRIPT_WITH_TAG, "con-script.cjs", "<script>"),
    ],
)
def test_an_unsafe_svg_fails_before_anything_is_written(
    tmp_path: Path, script_body: str, name: str, trap: str
) -> None:
    packages = _fixture(tmp_path)
    piece, _script, _data = _piece(tmp_path, script_body, name)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, script=name, data="banner-navidad.json"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 1
    assert result is None
    assert trap in done.stderr
    assert not (out / f"{name.removesuffix('.cjs')}.svg").exists()
    assert _sharp_calls(tmp_path) == []


def test_a_missing_data_file_fails_before_the_script_runs(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _script, _data = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, script="banner-navidad.cjs", data="falta.json"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 1
    assert result is None
    assert "data" in done.stderr
    assert "not found" in done.stderr
    assert _sharp_calls(tmp_path) == []


def test_verify_accepts_svg_and_png_and_rejects_a_bad_file(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _script, _data = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    svg = out / "banner-navidad.svg"
    svg.write_text(GOOD_SVG, encoding="utf-8")
    png = out / "banner-navidad.png"
    png.write_bytes(_png_bytes())
    bad = out / "notes.txt"
    bad.write_text("not an image\n", encoding="utf-8")
    request = _request(
        "verify", out, piece, script="banner-navidad.cjs", data="banner-navidad.json"
    )
    request["assets"] = [str(svg), str(png), str(bad)]
    done, result = _invoke(tmp_path, "verify", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    passed, png_verdict, failed = result["assets"]
    assert passed["file"] == "banner-navidad.svg" and passed["passed"] is True
    assert passed["verifier"] == "svganim"
    assert png_verdict["file"] == "banner-navidad.png" and png_verdict["passed"] is True
    assert failed["file"] == "notes.txt" and failed["passed"] is False


def test_verify_rejects_an_svg_that_carries_text(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _script, _data = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    svg = out / "texto.svg"
    svg.write_text(GOOD_SVG.replace('<path d="M0 0h10v10z"/>', '<text x="1">x</text>'), "utf-8")
    request = _request(
        "verify", out, piece, script="banner-navidad.cjs", data="banner-navidad.json"
    )
    request["assets"] = [str(svg)]
    done, result = _invoke(tmp_path, "verify", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    verdict = result["assets"][0]
    assert verdict["passed"] is False
    assert "<text>" in verdict["metrics"]["error"]


def test_preview_writes_the_image_fields_from_the_script_basename(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _script, _data = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    png = out / "banner-navidad.png"
    png.write_bytes(_png_bytes(1280, 720))
    svg = out / "banner-navidad.svg"
    svg.write_text(GOOD_SVG, encoding="utf-8")
    request = _request(
        "preview", out, piece, script="banner-navidad.cjs", data="banner-navidad.json"
    )
    request["assets"] = [str(png), str(svg)]
    done, result = _invoke(tmp_path, "preview", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    assert [entry["file"] for entry in result["assets"]] == [
        "banner-navidad.png",
        "banner-navidad.svg",
    ]
    data = json.loads((out / "banner-navidad.png.preview.json").read_text(encoding="utf-8"))
    assert set(data) == PREVIEW_FIELDS
    assert data["preview"] == 1
    assert data["kind"] == "image"
    assert data["summary"] == "banner-navidad · 1280x720 · svganim"
    assert data["name"] == "banner-navidad"
    assert data["prompt"] == "banner-navidad"
    assert data["seed"] == 0
    assert (data["width"], data["height"]) == (1280, 720)
    svg_data = json.loads((out / "banner-navidad.svg.preview.json").read_text(encoding="utf-8"))
    assert (svg_data["width"], svg_data["height"]) == (640, 480)


def test_doctor_reports_opentype_and_sharp_when_present(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _script, _data = _piece(tmp_path)
    done, result = _invoke(
        tmp_path,
        "doctor",
        _request("doctor", tmp_path, piece),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["opentype.js"]["ok"] is True
    assert "2.0.0" in checks["opentype.js"]["detail"]
    assert checks["sharp"]["ok"] is True
    assert "0.35.5" in checks["sharp"]["detail"]
    assert checks["sharp"]["fix"] == ""


def test_doctor_names_the_fix_when_a_package_is_missing(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _script, _data = _piece(tmp_path)
    done, result = _invoke(
        tmp_path,
        "doctor",
        _request("doctor", tmp_path, piece),
        _environment(tmp_path, [packages["opentype.js"]]),
    )
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["opentype.js"]["ok"] is True
    assert checks["sharp"]["ok"] is False
    assert "not extracted" in checks["sharp"]["detail"]
    assert "facet" in checks["sharp"]["fix"]
