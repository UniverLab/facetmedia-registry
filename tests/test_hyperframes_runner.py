"""The hyperframes runner against fixture npm trees and a stub HyperFrames CLI.

The runner is a subprocess of the host ``node``. Its ``FACET_NODE_PATH`` points
at fixture package directories carrying only ``package.json``; the first one
holds a stub ``bin/hyperframes.mjs`` that records every call and copies an MP4
fixture for ``render``. That proves the link plan (dependencies, non-optional
peers, linux-x64 optional deps, two ``string-width`` versions), check first,
the workers cap and the lab environment variables, without downloading a
tarball or rendering a real composition. ``preview`` and ``verify`` probe the
checked-in MP4 fixture with the host ``ffprobe`` and skip when it is absent.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "hyperframes"
RUNNER = PACKAGE / "runner.js"
CLIP = ROOT / "tests" / "fixtures" / "clip.mp4"
ALPHA_MOV = ROOT / "tests" / "fixtures" / "clip-alpha.mov"
LOOP_GIF = ROOT / "tests" / "fixtures" / "loop.gif"
NOLOOP_GIF = ROOT / "tests" / "fixtures" / "noloop.gif"
NODE = shutil.which("node")
FFPROBE = shutil.which("ffprobe")
BROWSER = shutil.which("sh") or "/bin/sh"
FFMPEG_MISSING = "ffmpeg and ffprobe are required to encode video (sudo apt-get install -y ffmpeg)"
FIELDS = {
    "preview",
    "kind",
    "summary",
    "name",
    "prompt",
    "seed",
    "width",
    "height",
    "length",
    "fps",
}
#: What tests/fixtures/clip.mp4 measures: 64x48, 49 frames at 24 fps.
WIDTH = 64
HEIGHT = 48
FRAMES = 49
FPS = 24
RUN_SEED = 5
PREVIEW_SEED = 7
BARE_IMPORT_RE = re.compile(r"""(?:require\s*\(\s*|from\s+|import\s*\(\s*)["']([^"']+)["']""")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not available")

STUB = """
import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
const log = process.env.HF_STUB_LOG;
if (log) {
  fs.appendFileSync(
    log,
    `${JSON.stringify({
      args,
      telemetry: process.env.HYPERFRAMES_NO_TELEMETRY,
      skills: process.env.HYPERFRAMES_SKIP_SKILLS,
      hasPath: Boolean(process.env.PATH),
      cwd: process.cwd(),
    })}\\n`,
  );
}
if (args[0] === "check" && process.env.HF_STUB_CHECK_FAIL === "1") {
  process.stderr.write("check exploded\\n");
  process.exit(2);
}
if (args[0] === "render") {
  const output = args[args.indexOf("-o") + 1];
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.copyFileSync(process.env.HF_STUB_MP4, output);
}
"""


def _package(root: Path, name: str, version: str, **extra: Any) -> Path:
    directory = root / "pkgs" / name.replace("@", "").replace("/", "__") / version
    directory.mkdir(parents=True)
    manifest = {"name": name, "version": version, **extra}
    (directory / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def _fixture(root: Path) -> dict[str, Path]:
    """A small tree exercising dependencies, peers, optional deps and two widths."""
    packages = {
        "hyperframes": _package(
            root,
            "hyperframes",
            "0.8.143",
            dependencies={"@hono/node-server": "2.1.6", "giget": "^3.2.0"},
        ),
        "hono_server": _package(
            root, "@hono/node-server", "2.1.6", peerDependencies={"hono": "^4 || ^5.0.0-0"}
        ),
        "giget": _package(root, "giget", "3.3.1"),
        "hono": _package(root, "hono", "4.13.17"),
        "yargs": _package(root, "yargs", "18.2.0", dependencies={"string-width": "^8.2.1"}),
        "wrap": _package(root, "wrap-ansi", "9.0.2", dependencies={"string-width": "^7.0.0"}),
        "width7": _package(root, "string-width", "7.2.0"),
        "width8": _package(root, "string-width", "8.3.0"),
        "sharp": _package(
            root,
            "sharp",
            "0.35.5",
            optionalDependencies={
                "@img/sharp-linux-x64": "0.35.5",
                "@img/sharp-linuxmusl-x64": "0.35.5",
                "@img/sharp-darwin-arm64": "0.35.5",
            },
        ),
        "img": _package(root, "@img/sharp-linux-x64", "0.35.5"),
        "ws": _package(
            root,
            "ws",
            "8.22.1",
            peerDependencies={"bufferutil": "^4.0.0", "utf-8-validate": ">=5.0.0"},
            peerDependenciesMeta={
                "bufferutil": {"optional": True},
                "utf-8-validate": {"optional": True},
            },
        ),
    }
    stub = packages["hyperframes"] / "bin" / "hyperframes.mjs"
    stub.parent.mkdir()
    stub.write_text(STUB, encoding="utf-8")
    return packages


def _dirs(packages: dict[str, Path]) -> list[Path]:
    return [
        packages[name]
        for name in (
            "hyperframes",
            "hono_server",
            "giget",
            "hono",
            "yargs",
            "wrap",
            "width7",
            "width8",
            "sharp",
            "img",
            "ws",
        )
    ]


def _composition(root: Path) -> tuple[Path, Path, Path]:
    piece = root / "piece"
    comp = piece / "comp"
    (comp / "assets").mkdir(parents=True)
    metadata = {
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
        "paths": {"blocks": "compositions", "assets": "assets"},
    }
    (comp / "hyperframes.json").write_text(json.dumps(metadata), encoding="utf-8")
    (comp / "index.tmpl").write_text("<!doctype html><html><body></body></html>", encoding="utf-8")
    (comp / "build.mjs").write_text("export {};\n", encoding="utf-8")
    (comp / "assets" / "keep.txt").write_text("vendored\n", encoding="utf-8")
    clip = root / "voz.wav"
    clip.write_bytes(b"RIFF0000WAVE")
    return piece, comp, clip


def _environment(
    root: Path, dirs: list[Path], *, browser: bool = True, path: str | None = None
) -> dict[str, str]:
    return {
        "FACET_NODE": str(NODE),
        "FACET_NODE_PATH": os.pathsep.join(str(directory) for directory in dirs),
        "HYPERFRAMES_BROWSER_PATH": BROWSER if browser else "",
        "HF_STUB_LOG": str(root / "calls.log"),
        "HF_STUB_MP4": str(CLIP),
        "PATH": path if path is not None else os.environ.get("PATH", ""),
    }


def _request(
    verb: str, out: Path, piece: Path, capability: str = "hyperframes.render", **inputs: Any
) -> dict[str, Any]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": capability,
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


def test_run_links_the_tree_and_checks_before_render(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, comp, clip = _composition(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    inputs = {
        "composicion": "comp",
        "prompt": "brief",
        "seed": 5,
        "fps": 24,
        "audio": [{"clip": str(clip)}],
    }
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, **inputs),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    assert result is not None
    calls = _calls(tmp_path)
    assert [call["args"][0] for call in calls] == ["check", "render"]
    assert calls[0]["telemetry"] == "1" and calls[0]["skills"] == "1"
    assert calls[0]["hasPath"] is True
    assert calls[0]["cwd"] == str(out / "composition")
    render = calls[1]["args"]
    assert render[1:3] == ["--workers", "2"]
    assert render[render.index("--fps") + 1] == "24"
    assert render[render.index("-o") + 1] == str(out / "comp.mp4")
    assert (out / "comp.mp4").is_file()
    asset = result["assets"][0]
    assert (asset["file"], asset["name"], asset["kind"], asset["mime"]) == (
        "comp.mp4",
        "comp",
        "video",
        "video/mp4",
    )
    assert asset["seed"] == RUN_SEED
    assert asset["params"]["prompt"] == "brief"
    assert str(comp) in asset["inputs"] and str(clip) in asset["inputs"]
    assert result["tool"] == {"name": "hyperframes", "version": "0.8.143"}


def test_run_links_dependencies_peers_and_linux_x64_optionals(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp, _clip = _composition(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, _result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, composicion="comp", prompt="brief"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    hf, server = packages["hyperframes"], packages["hono_server"]
    assert _link(hf, "@hono/node-server") == server
    assert _link(hf, "giget") == packages["giget"]
    assert _link(server, "hono") == packages["hono"]
    assert _link(packages["yargs"], "string-width") == packages["width8"]
    assert _link(packages["wrap"], "string-width") == packages["width7"]
    assert _link(packages["sharp"], "@img/sharp-linux-x64") == packages["img"]
    assert not (packages["sharp"] / "node_modules" / "@img" / "sharp-linuxmusl-x64").exists()
    assert not (packages["sharp"] / "node_modules" / "@img" / "sharp-darwin-arm64").exists()
    assert not (packages["ws"] / "node_modules").exists()


def test_a_failing_check_aborts_before_render(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp, _clip = _composition(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, _dirs(packages))
    env["HF_STUB_CHECK_FAIL"] = "1"
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, composicion="comp", prompt="brief"),
        env,
    )
    assert done.returncode != 0
    assert result is None
    assert "check exploded" in done.stderr
    assert [call["args"][0] for call in _calls(tmp_path)] == ["check"]


def test_a_remote_url_is_refused_before_the_cli_runs(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, comp, _clip = _composition(tmp_path)
    (comp / "index.tmpl").write_text(
        '<script src="https://cdn.example.com/app.js"></script>', encoding="utf-8"
    )
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, composicion="comp", prompt="brief"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode != 0
    assert result is None
    assert "index.tmpl" in done.stderr
    assert "https://cdn.example.com/app.js" in done.stderr
    assert _calls(tmp_path) == []


def _run_loop(
    tmp_path: Path, packages: dict[str, Path], fmt: str
) -> tuple[subprocess.CompletedProcess[str], Any]:
    piece, _comp, _clip = _composition(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request(
            "run",
            out,
            piece,
            capability="hyperframes.loop",
            composicion="comp",
            prompt="brief",
            format=fmt,
        ),
        _environment(tmp_path, _dirs(packages)),
    )
    return done, result


def test_run_loop_gif_passes_the_format_flag(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    done, result = _run_loop(tmp_path, packages, "gif")
    assert done.returncode == 0, done.stderr
    calls = _calls(tmp_path)
    assert [call["args"][0] for call in calls] == ["check", "render"]
    render = calls[1]["args"]
    assert render[render.index("--format") + 1] == "gif"
    assert render[render.index("-o") + 1].endswith("comp.gif")
    asset = result["assets"][0]
    assert (asset["file"], asset["kind"], asset["mime"]) == (
        "comp.gif",
        "video",
        "image/gif",
    )


def test_run_loop_mov_alpha_passes_the_format_flag(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    done, result = _run_loop(tmp_path, packages, "mov-alpha")
    assert done.returncode == 0, done.stderr
    calls = _calls(tmp_path)
    assert [call["args"][0] for call in calls] == ["check", "render"]
    render = calls[1]["args"]
    assert render[render.index("--format") + 1] == "mov"
    assert render[render.index("-o") + 1].endswith("comp.mov")
    asset = result["assets"][0]
    assert (asset["file"], asset["kind"], asset["mime"]) == (
        "comp.mov",
        "video",
        "video/quicktime",
    )


@pytest.mark.skipif(FFPROBE is None, reason="ffprobe is not available")
def test_verify_mov_alpha_requires_an_alpha_channel(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    alpha = out / "overlay.mov"
    shutil.copyfile(ALPHA_MOV, alpha)
    opaque = out / "plain.mov"
    shutil.copyfile(CLIP, opaque)
    request = _request(
        "verify",
        out,
        tmp_path,
        capability="hyperframes.loop",
        composicion="comp",
        prompt="brief",
        format="mov-alpha",
    )
    request["assets"] = [str(alpha), str(opaque)]
    done, result = _invoke(tmp_path, "verify", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    passed, failed = result["assets"]
    assert passed["file"] == "overlay.mov" and passed["passed"] is True
    assert passed["metrics"]["pix_fmt"] == "argb"
    assert failed["file"] == "plain.mov" and failed["passed"] is False


@pytest.mark.skipif(FFPROBE is None, reason="ffprobe is not available")
def test_verify_gif_requires_the_netscape_loop_block(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    looping = out / "loop.gif"
    shutil.copyfile(LOOP_GIF, looping)
    still = out / "noloop.gif"
    shutil.copyfile(NOLOOP_GIF, still)
    request = _request(
        "verify",
        out,
        tmp_path,
        capability="hyperframes.loop",
        composicion="comp",
        prompt="brief",
        format="gif",
    )
    request["assets"] = [str(looping), str(still)]
    done, result = _invoke(tmp_path, "verify", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    passed, failed = result["assets"]
    assert passed["file"] == "loop.gif" and passed["passed"] is True
    assert failed["file"] == "noloop.gif" and failed["passed"] is False


def test_a_missing_browser_is_reported_by_doctor(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    env = _environment(tmp_path, _dirs(packages), browser=False, path=str(empty))
    done, result = _invoke(tmp_path, "doctor", _request("doctor", tmp_path, tmp_path), env)
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    chromium = checks["chromium"]
    assert chromium["ok"] is False
    assert "HYPERFRAMES_BROWSER_PATH" in chromium["detail"]
    assert "/usr/bin/google-chrome" in chromium["detail"]
    assert chromium["fix"]
    ffmpeg = checks["ffmpeg"]
    assert ffmpeg["ok"] is False
    assert ffmpeg["detail"] == FFMPEG_MISSING
    assert ffmpeg["fix"] == ""


def test_run_without_a_browser_fails_and_never_calls_the_cli(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp, _clip = _composition(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, composicion="comp", prompt="brief"),
        _environment(tmp_path, _dirs(packages), browser=False),
    )
    assert done.returncode != 0
    assert result is None
    assert "HYPERFRAMES_BROWSER_PATH" in done.stderr
    assert _calls(tmp_path) == []


def test_doctor_reports_the_host_tools_when_present(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    done, result = _invoke(
        tmp_path,
        "doctor",
        _request("doctor", tmp_path, tmp_path),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["chromium"]["ok"] is True
    has_ffmpeg = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    assert checks["ffmpeg"]["ok"] is has_ffmpeg


@pytest.mark.skipif(FFPROBE is None, reason="ffprobe is not available")
def test_preview_writes_the_ten_video_fields(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    asset = out / "comp.mp4"
    shutil.copyfile(CLIP, asset)
    request = _request("preview", out, tmp_path, composicion="comp", prompt="a brief", seed=7)
    request["assets"] = [str(asset)]
    done, result = _invoke(tmp_path, "preview", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    assert result["assets"] == [
        {"file": "comp.mp4", "preview": "comp.mp4.preview.json", "images": []}
    ]
    data = json.loads((out / "comp.mp4.preview.json").read_text(encoding="utf-8"))
    assert set(data) == FIELDS
    assert data["preview"] == 1
    assert data["kind"] == "video"
    assert data["summary"] == "comp · 64x48 · 49f @ 24fps · seed 7"
    assert data["name"] == "comp"
    assert data["prompt"] == "a brief"
    assert data["seed"] == PREVIEW_SEED
    assert (data["width"], data["height"], data["length"], data["fps"]) == (
        WIDTH,
        HEIGHT,
        FRAMES,
        FPS,
    )


@pytest.mark.skipif(FFPROBE is None, reason="ffprobe is not available")
def test_verify_probes_the_mp4_and_rejects_a_non_video(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    good = out / "good.mp4"
    shutil.copyfile(CLIP, good)
    bad = out / "notes.txt"
    bad.write_text("not a video\n", encoding="utf-8")
    request = _request("verify", out, tmp_path, composicion="comp", prompt="a brief")
    request["assets"] = [str(good), str(bad)]
    done, result = _invoke(tmp_path, "verify", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    passed, failed = result["assets"]
    assert passed["file"] == "good.mp4" and passed["passed"] is True
    assert passed["verifier"] == "ffprobe"
    assert (passed["metrics"]["width"], passed["metrics"]["height"]) == (WIDTH, HEIGHT)
    assert passed["metrics"]["frames"] == FRAMES and passed["metrics"]["fps"] == FPS
    assert failed["file"] == "notes.txt" and failed["passed"] is False


DIAGRAMA_SVG = ROOT / "tests" / "fixtures" / "diagrama.svg"
#: One paso per selector form the proofs use: flow node, edge, label, service, group, singleton.
PROOF_PASOS = [
    {"selector": '[id^="my-svg-flowchart-datos-"]', "at": 0.8, "kind": "show"},
    {"selector": "#my-svg-L_datos_pieza_0", "at": 1.2, "kind": "draw", "dur": 0.5},
    {"selector": '.edgeLabels [data-id="L_datos_pieza_0"]', "at": 1.5, "kind": "fade", "dur": 0.3},
    {"selector": "#my-svg-service-agente", "at": 1.9, "kind": "show"},
    {"selector": "#my-svg-group-lab", "at": 2.2, "kind": "fade"},
    {"selector": "#my-svg-gpu", "at": 2.6, "kind": "fade"},
]
BUILD_MJS = """
import { readFileSync, writeFileSync } from "node:fs";
const SVG = "../diagrama.svg";
const svg = readFileSync(new URL(SVG, import.meta.url), "utf8")
  .replace(/<style>[\\s\\S]*?<\\/style>/g, (style) => style.replaceAll("&gt;", ">"));
const template = readFileSync(new URL("index.tmpl", import.meta.url), "utf8");
writeFileSync(new URL("index.html", import.meta.url), template.replace("<!-- DIAGRAMA -->", svg));
"""


def _diagrama_request(out: Path, piece: Path, animacion: list[dict[str, Any]]) -> dict[str, Any]:
    return _request(
        "run",
        out,
        piece,
        capability="hyperframes.diagrama",
        composicion="comp",
        prompt="brief",
        **{"diagrama-svg": str(DIAGRAMA_SVG), "animacion": animacion},
    )


def test_diagrama_rejects_an_unknown_selector_before_the_cli_runs(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp, _clip = _composition(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    animacion = [{"selector": "#my-svg-L_nope_x_0", "at": 0.5, "kind": "draw"}]
    done, result = _invoke(
        tmp_path,
        "run",
        _diagrama_request(out, piece, animacion),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode != 0
    assert result is None
    assert "unknown" in done.stderr
    assert _calls(tmp_path) == []


def test_diagrama_renders_the_proof_selectors_and_injects_the_timeline(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp, _clip = _composition(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _diagrama_request(out, piece, PROOF_PASOS),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    assert [call["args"][0] for call in _calls(tmp_path)] == ["check", "render"]
    assert (out / "comp.mp4").is_file()
    assert (out / "diagrama.svg").is_file()
    template = (out / "composition" / "index.tmpl").read_text(encoding="utf-8")
    assert "strokeDashoffset" in template
    assert "__timelines" in template
    assert result is not None
    assert result["assets"][0]["file"] == "comp.mp4"


def test_build_mjs_decodes_gt_only_inside_style(tmp_path: Path) -> None:
    comp = tmp_path / "comp"
    comp.mkdir()
    (tmp_path / "diagrama.svg").write_text(
        '<svg><style>#my-svg .node &gt; rect { fill: #fff; }</style><g id="my-svg-gpu"></g></svg>',
        encoding="utf-8",
    )
    (comp / "index.tmpl").write_text(
        "<!doctype html><html><body><!-- DIAGRAMA --></body></html>", encoding="utf-8"
    )
    (comp / "build.mjs").write_text(BUILD_MJS, encoding="utf-8")
    done = subprocess.run(
        [str(NODE), "build.mjs"],
        cwd=comp,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    html = (comp / "index.html").read_text(encoding="utf-8")
    style = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert style is not None
    assert "&gt;" not in style.group(1)
    assert ">" in style.group(1)
    assert 'id="my-svg-gpu"' in html


GIRO_TEMPLATE = """<!doctype html>
<html lang="es">
  <head>
    <script src="./vendor/gsap.min.js"></script>
    <script type="importmap">
      { "imports": { "three": "./vendor/three.module.js",
                     "three/addons/": "./vendor/three/addons/" } }
    </script>
  </head>
  <body>
    <canvas id="escena"></canvas>
    <script type="module">
      import * as THREE from 'three';
      import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

      const GLB = /* GLB */"";
      const DATA = {
        /* GIRO */
        colores: { muros: 0xecebe6 },
      };

      const renderer = new THREE.WebGLRenderer();
      const listo = new GLTFLoader().parseAsync(new ArrayBuffer(0), '');

      // The approved lab proof carries this exact comment; naming the
      // forbidden API is not using it, so the recipe scan must let it pass.
      // Pure function of time: HyperFrames seeks every frame (no requestAnimationFrame).
      function renderAt(t) {
        renderer.render(new THREE.Scene(), new THREE.PerspectiveCamera());
      }
      window.addEventListener('hf-seek', (event) => {
        event.detail.waitUntil(listo.then(() => renderAt(event.detail.time)));
      });
    </script>
  </body>
</html>
"""
#: A vendored third-party file carrying a license URL in a comment the runner
#: never fetches; the vendor/ subtree is exempt from the remote-URL scan.
VENDOR_THREE = "// three.module.js 0.170.0 — https://threejs.org/license\n"
GIRO_MODEL = b"glTF\x02\x00\x00\x00"


def _giro_comp(root: Path, template: str = GIRO_TEMPLATE) -> tuple[Path, Path]:
    piece = root / "piece"
    comp = piece / "comp"
    addons = comp / "vendor" / "three" / "addons" / "loaders"
    addons.mkdir(parents=True)
    (comp / "assets").mkdir()
    metadata = {
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
    }
    (comp / "hyperframes.json").write_text(json.dumps(metadata), encoding="utf-8")
    (comp / "index.tmpl").write_text(template, encoding="utf-8")
    (comp / "build.mjs").write_text("export {};\n", encoding="utf-8")
    (comp / "vendor" / "gsap.min.js").write_text("// gsap 3.14.2\n", encoding="utf-8")
    (comp / "vendor" / "three.module.js").write_text(VENDOR_THREE, encoding="utf-8")
    (addons / "GLTFLoader.js").write_text("// GLTFLoader 0.170.0\n", encoding="utf-8")
    (comp / "assets" / "keep.txt").write_text("vendored\n", encoding="utf-8")
    model = piece / "modelo.glb"
    model.write_bytes(GIRO_MODEL)
    return piece, comp


def _giro_request(out: Path, piece: Path, **inputs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"composicion": "comp", "modelo-glb": "modelo.glb", "prompt": "brief"}
    base.update(inputs)
    return _request("run", out, piece, capability="hyperframes.giro", **base)


def test_giro_rejects_request_animation_frame_before_the_cli_runs(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    template = GIRO_TEMPLATE.replace(
        "function renderAt(t) {",
        "requestAnimationFrame(function () { renderAt(0); });\nfunction renderAt(t) {",
    )
    piece, _comp = _giro_comp(tmp_path, template)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _giro_request(out, piece),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode != 0
    assert result is None
    assert "requestAnimationFrame" in done.stderr
    assert _calls(tmp_path) == []


def test_giro_rejects_a_remote_url_outside_vendor(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    template = GIRO_TEMPLATE.replace(
        "</head>",
        '<link rel="preload" href="https://cdn.example.com/model.bin">\n  </head>',
    )
    piece, _comp = _giro_comp(tmp_path, template)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _giro_request(out, piece),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode != 0
    assert result is None
    assert "index.tmpl" in done.stderr
    assert "https://cdn.example.com/model.bin" in done.stderr
    assert _calls(tmp_path) == []


def test_giro_does_not_scan_urls_inside_vendor(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp = _giro_comp(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _giro_request(out, piece),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    assert [call["args"][0] for call in _calls(tmp_path)] == ["check", "render"]
    assert result is not None
    copied = (out / "composition" / "vendor" / "three.module.js").read_text(encoding="utf-8")
    assert "https://threejs.org/license" in copied


def test_giro_embeds_the_model_and_injects_the_orbit_scalars(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp = _giro_comp(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    inputs = {
        "orbita-radio": 7,
        "orbita-altura": 5,
        "orbita-desde": 0.2,
        "orbita-vuelta": 1.5,
        "centro-x": 1.5,
        "centro-y": 2.5,
        "centro-z": -3.5,
        "duracion": 6,
    }
    done, result = _invoke(
        tmp_path,
        "run",
        _giro_request(out, piece, **inputs),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    assert result is not None
    written = (out / "composition" / "index.tmpl").read_text(encoding="utf-8")
    assert "/* GLB */" not in written
    assert "/* GIRO */" not in written
    assert base64.b64encode(GIRO_MODEL).decode("ascii") in written
    assert '"orbita":{"radio":7,"altura":5,"desde":0.2,"vuelta":1.5}' in written
    assert '"centro":[1.5,2.5,-3.5]' in written
    assert '"duracion":6' in written


def test_the_runner_has_no_check_verb(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    done, result = _invoke(
        tmp_path,
        "check",
        _request("check", tmp_path, tmp_path),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode != 0
    assert result is None
    assert "unknown verb" in done.stderr
    assert _calls(tmp_path) == []
