"""The hyperframes runner against fixture npm trees and a stub HyperFrames CLI.

The runner is a subprocess of the host ``node``. Its ``FACET_NODE_PATH`` points
at fixture package directories carrying only ``package.json``; the first one
holds a stub ``bin/hyperframes.mjs`` that records every call and copies an MP4
fixture for ``render``. That proves the link plan (dependencies, non-optional
peers, linux-x64 optional deps, two ``string-width`` versions), check first,
the workers cap and the lab environment variables, without downloading a
tarball or rendering a real composition. ``preview`` and ``verify`` probe the
checked-in MP4 fixture with the pinned ``ffprobe`` and skip when it is absent.
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
FFMPEG = shutil.which("ffmpeg")
#: The runner's default loudness target (LUFS) and verify ceiling (dBTP).
DEFAULT_TARGET_LUFS = -14.0
TRUE_PEAK_CEILING = -0.5
LOUDNESS_TOLERANCE_LU = 1.0
BROWSER = shutil.which("sh") or "/bin/sh"
FFMPEG_MISSING = "ffmpeg and ffprobe are required to encode video; run facet pull hyperframes"
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


#: The retired Spanish names; the runner keeps no alias for them. They are
#: assembled at runtime because the acceptance greps scan the tests too.
def _retired(prefix: str, *fragments: str) -> str:
    return prefix + "".join(fragments)


OLD_SOURCES = ("runner.js", "giro.js", "personaje.js", "narrado.js")
OLD_TOKENS = (
    _retired("hyperframes.", "dia", "grama"),
    _retired("hyperframes.", "giro"),
    _retired("hyperframes.", "personaje"),
    _retired("hyperframes.", "narrado"),
    '"diagrama-svg"',
    '"animacion"',
    '"modelo-glb"',
    _retired('"', "dura", 'cion"'),
    '"personaje-svg"',
    '"bocas"',
    '"audio-inicio"',
    '"musica"',
    '"volumen-musica"',
    '"subtitulos"',
    _retired("/* ", "GIRO", " */"),
    _retired("/* ", "BOCAS", " */"),
    _retired('"', "orbi", 'ta"'),
    _retired('"', "cen", 'tro"'),
)

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
      browser: process.env.HYPERFRAMES_BROWSER_PATH,
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
    (comp / "index.html").write_text("<!doctype html><html><body></body></html>", encoding="utf-8")
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
        "FACET_BROWSER": BROWSER if browser else "",
        "FACET_FFMPEG": FFMPEG or "",
        "FACET_FFPROBE": FFPROBE or "",
        "HYPERFRAMES_BROWSER_PATH": "/nonexistent/host-chrome",
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
        "composition": "comp",
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
    assert calls[0]["browser"] == BROWSER
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
        _request("run", out, piece, composition="comp", prompt="brief"),
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
        _request("run", out, piece, composition="comp", prompt="brief"),
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
    (comp / "index.html").write_text(
        '<script src="https://cdn.example.com/app.js"></script>', encoding="utf-8"
    )
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, composition="comp", prompt="brief"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode != 0
    assert result is None
    assert "index.tmpl" in done.stderr or "index.html" in done.stderr
    assert "https://cdn.example.com/app.js" in done.stderr
    assert _calls(tmp_path) == []


def test_a_composition_without_index_html_fails_before_the_cli_runs(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, comp, _clip = _composition(tmp_path)
    (comp / "index.html").unlink()
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, composition="comp", prompt="brief"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode != 0
    assert result is None
    assert "has no index.html" in done.stderr
    assert "build.mjs" in done.stderr
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
            composition="comp",
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
        composition="comp",
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
        composition="comp",
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
    env["FACET_FFMPEG"] = ""
    env["FACET_FFPROBE"] = ""
    done, result = _invoke(tmp_path, "doctor", _request("doctor", tmp_path, tmp_path), env)
    assert done.returncode == 0, done.stderr
    checks = {check["name"]: check for check in result["checks"]}
    chromium = checks["chromium"]
    assert chromium["ok"] is False
    assert "FACET_BROWSER" in chromium["detail"]
    assert chromium["fix"] == "facet pull hyperframes"
    ffmpeg = checks["ffmpeg"]
    assert ffmpeg["ok"] is False
    assert ffmpeg["detail"] == FFMPEG_MISSING
    assert ffmpeg["fix"] == "facet pull hyperframes"


def test_run_without_a_browser_fails_and_never_calls_the_cli(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp, _clip = _composition(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _request("run", out, piece, composition="comp", prompt="brief"),
        _environment(tmp_path, _dirs(packages), browser=False),
    )
    assert done.returncode != 0
    assert result is None
    assert "FACET_BROWSER" in done.stderr
    assert "facet pull hyperframes" in done.stderr
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
    if has_ffmpeg:
        assert FFMPEG in checks["ffmpeg"]["detail"]
        assert FFPROBE in checks["ffmpeg"]["detail"]


@pytest.mark.skipif(FFPROBE is None, reason="ffprobe is not available")
def test_preview_writes_the_ten_video_fields(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    asset = out / "comp.mp4"
    shutil.copyfile(CLIP, asset)
    request = _request("preview", out, tmp_path, composition="comp", prompt="a brief", seed=7)
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
    request = _request("verify", out, tmp_path, composition="comp", prompt="a brief")
    request["assets"] = [str(good), str(bad)]
    done, result = _invoke(tmp_path, "verify", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    passed, failed = result["assets"]
    assert passed["file"] == "good.mp4" and passed["passed"] is True
    assert passed["verifier"] == "ffprobe"
    assert (passed["metrics"]["width"], passed["metrics"]["height"]) == (WIDTH, HEIGHT)
    assert passed["metrics"]["frames"] == FRAMES and passed["metrics"]["fps"] == FPS
    assert failed["file"] == "notes.txt" and failed["passed"] is False


def test_verify_without_the_pinned_ffmpeg_fails_with_the_pull_fix(tmp_path: Path) -> None:
    """Without FACET_FFMPEG the run fails naming facet pull, never apt."""
    packages = _fixture(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    good = out / "good.mp4"
    shutil.copyfile(CLIP, good)
    request = _request("verify", out, tmp_path, composition="comp", prompt="a brief")
    request["assets"] = [str(good)]
    env = _environment(tmp_path, _dirs(packages))
    env["FACET_FFMPEG"] = ""
    done, result = _invoke(tmp_path, "verify", request, env)
    assert done.returncode != 0
    assert result is None
    assert "facet pull hyperframes" in done.stderr


DIAGRAM_SVG = ROOT / "tests" / "fixtures" / "diagram.svg"
#: One step per selector form the proofs use: flow node, edge, label, service, group, singleton.
PROOF_STEPS = [
    {"selector": '[id^="my-svg-flowchart-datos-"]', "at": 0.8, "kind": "show"},
    {"selector": "#my-svg-L_datos_pieza_0", "at": 1.2, "kind": "draw", "dur": 0.5},
    {"selector": '.edgeLabels [data-id="L_datos_pieza_0"]', "at": 1.5, "kind": "fade", "dur": 0.3},
    {"selector": "#my-svg-service-agente", "at": 1.9, "kind": "show"},
    {"selector": "#my-svg-group-lab", "at": 2.2, "kind": "fade"},
    {"selector": "#my-svg-gpu", "at": 2.6, "kind": "fade"},
]
BUILD_MJS = """
import { readFileSync, writeFileSync } from "node:fs";
const SVG = "../diagram.svg";
const svg = readFileSync(new URL(SVG, import.meta.url), "utf8")
  .replace(/<style>[\\s\\S]*?<\\/style>/g, (style) => style.replaceAll("&gt;", ">"));
const template = readFileSync(new URL("index.tmpl", import.meta.url), "utf8");
writeFileSync(new URL("index.html", import.meta.url), template.replace("<!-- DIAGRAM -->", svg));
"""


def _diagram_request(out: Path, piece: Path, animation: list[dict[str, Any]]) -> dict[str, Any]:
    return _request(
        "run",
        out,
        piece,
        capability="hyperframes.diagram",
        composition="comp",
        prompt="brief",
        **{"diagram-svg": str(DIAGRAM_SVG), "animation": animation},
    )


def test_diagram_rejects_an_unknown_selector_before_the_cli_runs(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp, _clip = _composition(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    animation = [{"selector": "#my-svg-L_nope_x_0", "at": 0.5, "kind": "draw"}]
    done, result = _invoke(
        tmp_path,
        "run",
        _diagram_request(out, piece, animation),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode != 0
    assert result is None
    assert "unknown" in done.stderr
    assert _calls(tmp_path) == []


def test_diagram_renders_the_proof_selectors_and_injects_the_timeline(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp, _clip = _composition(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _diagram_request(out, piece, PROOF_STEPS),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    assert [call["args"][0] for call in _calls(tmp_path)] == ["check", "render"]
    assert (out / "comp.mp4").is_file()
    assert (out / "diagram.svg").is_file()
    template = (out / "composition" / "index.html").read_text(encoding="utf-8")
    assert "strokeDashoffset" in template
    assert "__timelines" in template
    # HyperFrames 0.8.143's check (gsap_timeline_not_registered) only accepts
    # `window.__timelines[<string or identifier>] = <identifier>`.
    assert TIMELINE_REGISTRATION.search(template), "check would not see the timeline"
    assert result is not None
    assert result["assets"][0]["file"] == "comp.mp4"


#: HyperFrames 0.8.143 `WINDOW_TIMELINE_ASSIGN_PATTERN`, verbatim.
TIMELINE_REGISTRATION = re.compile(
    r"window\.__timelines(?:\[\s*(?:[\"']([^\"']+)[\"']|[A-Za-z_$][\w$.]*)\s*\]"
    r"|\.\s*([A-Za-z_$][\w$]*))\s*=\s*([A-Za-z_$][\w$]*)",
    re.IGNORECASE,
)


def test_build_mjs_decodes_gt_only_inside_style(tmp_path: Path) -> None:
    comp = tmp_path / "comp"
    comp.mkdir()
    (tmp_path / "diagram.svg").write_text(
        '<svg><style>#my-svg .node &gt; rect { fill: #fff; }</style><g id="my-svg-gpu"></g></svg>',
        encoding="utf-8",
    )
    (comp / "index.tmpl").write_text(
        "<!doctype html><html><body><!-- DIAGRAM --></body></html>", encoding="utf-8"
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


TURNTABLE_TEMPLATE = """<!doctype html>
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
        /* TURNTABLE */
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
TURNTABLE_MODEL = b"glTF\x02\x00\x00\x00"


def _turntable_comp(root: Path, template: str = TURNTABLE_TEMPLATE) -> tuple[Path, Path]:
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
    (comp / "index.html").write_text(template, encoding="utf-8")
    (comp / "build.mjs").write_text("export {};\n", encoding="utf-8")
    (comp / "vendor" / "gsap.min.js").write_text("// gsap 3.14.2\n", encoding="utf-8")
    (comp / "vendor" / "three.module.js").write_text(VENDOR_THREE, encoding="utf-8")
    (addons / "GLTFLoader.js").write_text("// GLTFLoader 0.170.0\n", encoding="utf-8")
    (comp / "assets" / "keep.txt").write_text("vendored\n", encoding="utf-8")
    model = piece / "modelo.glb"
    model.write_bytes(TURNTABLE_MODEL)
    return piece, comp


def _turntable_request(out: Path, piece: Path, **inputs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"composition": "comp", "model-glb": "modelo.glb", "prompt": "brief"}
    base.update(inputs)
    return _request("run", out, piece, capability="hyperframes.turntable", **base)


def test_turntable_rejects_request_animation_frame_before_the_cli_runs(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    template = TURNTABLE_TEMPLATE.replace(
        "function renderAt(t) {",
        "requestAnimationFrame(function () { renderAt(0); });\nfunction renderAt(t) {",
    )
    piece, _comp = _turntable_comp(tmp_path, template)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _turntable_request(out, piece),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode != 0
    assert result is None
    assert "requestAnimationFrame" in done.stderr
    assert _calls(tmp_path) == []


def test_turntable_rejects_a_remote_url_outside_vendor(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    template = TURNTABLE_TEMPLATE.replace(
        "</head>",
        '<link rel="preload" href="https://cdn.example.com/model.bin">\n  </head>',
    )
    piece, _comp = _turntable_comp(tmp_path, template)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _turntable_request(out, piece),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode != 0
    assert result is None
    assert "index.tmpl" in done.stderr or "index.html" in done.stderr
    assert "https://cdn.example.com/model.bin" in done.stderr
    assert _calls(tmp_path) == []


def test_turntable_does_not_scan_urls_inside_vendor(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp = _turntable_comp(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _turntable_request(out, piece),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    assert [call["args"][0] for call in _calls(tmp_path)] == ["check", "render"]
    assert result is not None
    copied = (out / "composition" / "vendor" / "three.module.js").read_text(encoding="utf-8")
    assert "https://threejs.org/license" in copied


def test_turntable_embeds_the_model_and_injects_the_orbit_scalars(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp = _turntable_comp(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    inputs = {
        "orbit-radius": 7,
        "orbit-height": 5,
        "orbit-start": 0.2,
        "orbit-fraction": 1.5,
        "center-x": 1.5,
        "center-y": 2.5,
        "center-z": -3.5,
        "duration": 6,
    }
    done, result = _invoke(
        tmp_path,
        "run",
        _turntable_request(out, piece, **inputs),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 0, done.stderr
    assert result is not None
    written = (out / "composition" / "index.html").read_text(encoding="utf-8")
    assert "/* GLB */" not in written
    assert "/* TURNTABLE */" not in written
    assert base64.b64encode(TURNTABLE_MODEL).decode("ascii") in written
    assert '"orbit":{"radius":7,"height":5,"start":0.2,"fraction":1.5}' in written
    assert '"center":[1.5,2.5,-3.5]' in written
    assert '"duration":6' in written


PERSONAJE_TEMPLATE = """<!doctype html>
<html lang="es">
  <head>
    <style>
      .mouth { opacity: 0; } #mouth-X { opacity: 1; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="11.5">
      <svg id="zorro" viewBox="-400 -400 800 800"></svg>
      <audio id="voice" src="voz.wav" data-start="0.5" data-duration="10.32"></audio>
    </div>
    <script>
      const AUDIO_START = 0.5;
      const CUES = /* MOUTHS */[];
      const tl = gsap.timeline({ paused: true });
      CUES.forEach(function (cue) {
        tl.set('.mouth', { opacity: 0 }, AUDIO_START + cue.start)
          .set('#mouth-' + cue.value, { opacity: 1 }, AUDIO_START + cue.start);
      });
      window.__timelines['main'] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
"""
#: One shape per Rhubarb letter: X rest, A closed, B teeth, C open, D wide open,
#: E round, F pursed, G teeth on lip, H tongue.
PERSONAJE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="-400 -400 800 800">
  <g id="mouth">
    <path class="mouth" id="mouth-X" d="M-60,-6 Q0,26 60,-6" fill="none" />
    <path class="mouth" id="mouth-A" d="M-52,0 L52,0" />
    <g class="mouth" id="mouth-B"><ellipse rx="54" ry="12" /></g>
    <g class="mouth" id="mouth-C"><ellipse rx="56" ry="24" /></g>
    <g class="mouth" id="mouth-D"><ellipse rx="60" ry="42" /></g>
    <g class="mouth" id="mouth-E"><ellipse rx="34" ry="32" /></g>
    <g class="mouth" id="mouth-F"><ellipse rx="20" ry="20" /></g>
    <g class="mouth" id="mouth-G"><ellipse rx="50" ry="14" /></g>
    <g class="mouth" id="mouth-H"><ellipse rx="54" ry="28" /></g>
  </g>
</svg>
"""
PROOF_CUES = [
    {"start": round(index / 10, 1), "end": round((index + 1) / 10, 1), "value": letter}
    for index, letter in enumerate("XABCDEFGH")
]
PROOF_MOUTHS = {"metadata": {"duration": 0.9}, "mouthCues": PROOF_CUES}
VOZ_BYTES = b"RIFF0000WAVE"


def _character_comp(root: Path) -> tuple[Path, Path]:
    piece = root / "piece"
    comp = piece / "comp"
    (comp / "assets").mkdir(parents=True)
    metadata = {
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
    }
    (comp / "hyperframes.json").write_text(json.dumps(metadata), encoding="utf-8")
    (comp / "index.tmpl").write_text(PERSONAJE_TEMPLATE, encoding="utf-8")
    (comp / "index.html").write_text(PERSONAJE_TEMPLATE, encoding="utf-8")
    (comp / "build.mjs").write_text("export {};\n", encoding="utf-8")
    (comp / "assets" / "keep.txt").write_text("vendored\n", encoding="utf-8")
    (piece / "zorro.svg").write_text(PERSONAJE_SVG, encoding="utf-8")
    (piece / "mouths.json").write_text(json.dumps(PROOF_MOUTHS), encoding="utf-8")
    (piece / "voz.wav").write_bytes(VOZ_BYTES)
    return piece, comp


def _character_request(out: Path, piece: Path, **inputs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "composition": "comp",
        "character-svg": "zorro.svg",
        "voice": "voz.wav",
        "mouths": "mouths.json",
        "audio-start": 0.75,
        "prompt": "brief",
    }
    base.update(inputs)
    return _request("run", out, piece, capability="hyperframes.character", **base)


def test_character_rejects_a_missing_mouth_shape_before_the_cli_runs(tmp_path: Path) -> None:
    """Exit 1 is what facet reports as runner_failed; the letter is named."""
    packages = _fixture(tmp_path)
    piece, _comp = _character_comp(tmp_path)
    svg = (piece / "zorro.svg").read_text(encoding="utf-8").replace('id="mouth-D"', 'id="mouth-Q"')
    (piece / "zorro.svg").write_text(svg, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _character_request(out, piece),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 1
    assert result is None
    assert "mouth-D" in done.stderr
    assert "Rhubarb mouth D" in done.stderr
    assert _calls(tmp_path) == []


def test_character_refuses_parent_traversal_src_before_check(tmp_path: Path) -> None:
    """A ../ audio src never reaches check: HyperFrames rejects parent traversal."""
    packages = _fixture(tmp_path)
    piece, _comp = _character_comp(tmp_path)
    for name in ("index.tmpl", "index.html"):
        template = piece / "comp" / name
        template.write_text(
            template.read_text(encoding="utf-8").replace('src="voz.wav"', 'src="../voz.wav"'),
            encoding="utf-8",
        )
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _character_request(out, piece),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 1
    assert result is None
    assert "../voz.wav" in done.stderr
    assert "climbs above the composition root" in done.stderr
    assert _calls(tmp_path) == []


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not available")
def test_character_injects_the_cues_and_the_audio_start(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp = _character_comp(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, _dirs(packages))
    env["HF_STUB_MP4"] = str(_audio_mp4(tmp_path))
    done, result = _invoke(
        tmp_path,
        "run",
        _character_request(out, piece),
        env,
    )
    assert done.returncode == 0, done.stderr
    assert [call["args"][0] for call in _calls(tmp_path)] == ["check", "render"]
    assert result is not None and result["assets"][0]["file"] == "comp.mp4"
    written = (out / "composition" / "index.html").read_text(encoding="utf-8")
    assert "/* MOUTHS */" not in written
    injected = re.search(r"const CUES = (\[.*?\]);", written, re.DOTALL)
    assert injected is not None
    assert json.loads(injected.group(1)) == PROOF_CUES
    assert "const AUDIO_START = 0.75;" in written
    assert (out / "composition" / "voz.wav").read_bytes() == VOZ_BYTES


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


NARRATED_TEMPLATE = """<!doctype html>
<html lang="es">
  <head>
    <style>.sub { position: absolute; opacity: 0; }</style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="10">
      <!-- SUBS -->
      <!-- AUDIOS -->
    </div>
    <script>
      const tl = gsap.timeline({ paused: true });
      window.__timelines['main'] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
"""
NARRATED_SRT = """1
00:00:00,000 --> 00:00:02,500
Hola <mundo> & adiós

2
00:00:03,000 --> 00:00:05,000
Segunda línea
"""
NARRATED_SRT_OVERFLOW = """1
00:00:00,000 --> 00:00:02,500
Hola <mundo> & adiós

2
00:00:03,000 --> 00:00:12,500
Segunda línea
"""


def _narrated_comp(root: Path) -> tuple[Path, Path]:
    piece = root / "piece"
    comp = piece / "comp"
    (comp / "assets").mkdir(parents=True)
    metadata = {
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
    }
    (comp / "hyperframes.json").write_text(json.dumps(metadata), encoding="utf-8")
    (comp / "index.tmpl").write_text(NARRATED_TEMPLATE, encoding="utf-8")
    (comp / "index.html").write_text(NARRATED_TEMPLATE, encoding="utf-8")
    (comp / "build.mjs").write_text("export {};\n", encoding="utf-8")
    (comp / "assets" / "keep.txt").write_text("vendored\n", encoding="utf-8")
    (piece / "voz-a.wav").write_bytes(VOZ_BYTES)
    (piece / "voz-b.wav").write_bytes(VOZ_BYTES)
    (piece / "musica.wav").write_bytes(VOZ_BYTES)
    (piece / "subtitulos.srt").write_text(NARRATED_SRT, encoding="utf-8")
    return piece, comp


def _audio_mp4(root: Path, name: str = "audio.mp4") -> Path:
    """An MP4 with the clip's video and a full-scale sine bed, for loudness tests."""
    assert FFMPEG is not None
    out = root / name
    done = subprocess.run(
        [
            str(FFMPEG),
            "-nostdin",
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-i",
            str(CLIP),
            "-map",
            "1:v",
            "-map",
            "0:a",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-shortest",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return out


def _narrated_request(out: Path, piece: Path, **inputs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "composition": "comp",
        "voice": [{"clip": "voz-a.wav"}, {"clip": "voz-b.wav"}],
        "music": "musica.wav",
        "subtitles": "subtitulos.srt",
        "prompt": "brief",
    }
    base.update(inputs)
    return _request("run", out, piece, capability="hyperframes.narrated", **base)


def test_narrated_rejects_a_missing_music_bed_before_the_cli_runs(tmp_path: Path) -> None:
    """Exit 1 is what facet reports as runner_failed; the file is named."""
    packages = _fixture(tmp_path)
    piece, _comp = _narrated_comp(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _narrated_request(out, piece, music="falta-musica.wav"),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 1
    assert result is None
    assert "music" in done.stderr
    assert "falta-musica.wav" in done.stderr
    assert _calls(tmp_path) == []


def test_narrated_rejects_a_cue_past_the_duration_before_the_cli_runs(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp = _narrated_comp(tmp_path)
    (piece / "subtitulos.srt").write_text(NARRATED_SRT_OVERFLOW, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _narrated_request(out, piece),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 1
    assert result is None
    assert "cue 2" in done.stderr
    assert "12.5" in done.stderr
    assert "10" in done.stderr
    assert _calls(tmp_path) == []


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not available")
def test_narrated_injects_audio_subtitles_and_the_opacity_timeline(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp = _narrated_comp(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, _dirs(packages))
    env["HF_STUB_MP4"] = str(_audio_mp4(tmp_path))
    done, result = _invoke(
        tmp_path,
        "run",
        _narrated_request(out, piece),
        env,
    )
    assert done.returncode == 0, done.stderr
    assert [call["args"][0] for call in _calls(tmp_path)] == ["check", "render"]
    assert result is not None and result["assets"][0]["file"] == "comp.mp4"
    written = (out / "composition" / "index.html").read_text(encoding="utf-8")
    assert (
        '<audio id="voice-1" src="voz-a.wav" data-start="0" '
        'data-duration="10" data-track-index="1" data-volume="1"></audio>'
    ) in written
    assert (
        '<audio id="voice-2" src="voz-b.wav" data-start="0" '
        'data-duration="10" data-track-index="2" data-volume="1"></audio>'
    ) in written
    assert (
        '<audio id="music" src="musica.wav" data-start="0" '
        'data-duration="10" data-track-index="3" data-volume="0.25"></audio>'
    ) in written
    assert '<div class="sub" id="s0">Hola &lt;mundo&gt; &amp; adiós</div>' in written
    assert '<div class="sub" id="s1">Segunda línea</div>' in written
    cues = re.search(r"var cues = (\[.*?\]);", written, re.DOTALL)
    assert cues is not None
    assert json.loads(cues.group(1)) == [
        {"start": 0.0, "end": 2.5, "text": "Hola <mundo> & adiós"},
        {"start": 3.0, "end": 5.0, "text": "Segunda línea"},
    ]
    assert "{ opacity: 1 }, cue.start" in written
    assert "{ opacity: 0 }, cue.end" in written
    assert "<!-- SUBS -->" not in written
    assert "<!-- AUDIOS -->" not in written
    for name in ("voz-a.wav", "voz-b.wav", "musica.wav"):
        assert (out / "composition" / name).read_bytes() == VOZ_BYTES
    assert not (out / "subtitulos.srt").exists()
    assert not (out / "composition" / "subtitulos.srt").exists()


def test_narrated_refuses_a_start_past_the_duration_before_the_cli_runs(
    tmp_path: Path,
) -> None:
    packages = _fixture(tmp_path)
    piece, _comp = _narrated_comp(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result = _invoke(
        tmp_path,
        "run",
        _narrated_request(
            out,
            piece,
            voice=[{"clip": "voz-a.wav"}, {"clip": "voz-b.wav", "start": 12}],
        ),
        _environment(tmp_path, _dirs(packages)),
    )
    assert done.returncode == 1
    assert result is None
    assert "start 12" in done.stderr
    assert "composition duration 10" in done.stderr
    assert _calls(tmp_path) == []


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not available")
def test_narrated_music_volume_reaches_the_bed_data_volume(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp = _narrated_comp(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    request = _narrated_request(out, piece)
    request["inputs"]["music-volume"] = 0.4
    env = _environment(tmp_path, _dirs(packages))
    env["HF_STUB_MP4"] = str(_audio_mp4(tmp_path))
    done, result = _invoke(tmp_path, "run", request, env)
    assert done.returncode == 0, done.stderr
    written = (out / "composition" / "index.html").read_text(encoding="utf-8")
    assert 'data-volume="0.4"' in written


def test_narrated_refuses_a_music_volume_outside_zero_to_one(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    piece, _comp = _narrated_comp(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    request = _narrated_request(out, piece)
    request["inputs"]["music-volume"] = 1.5
    done, result = _invoke(tmp_path, "run", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 1
    assert result is None
    assert "music-volume" in done.stderr
    assert _calls(tmp_path) == []


@pytest.mark.skipif(FFPROBE is None, reason="ffprobe is not available")
def test_verify_fails_a_narrated_video_without_an_audio_stream(
    tmp_path: Path,
) -> None:
    packages = _fixture(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    asset = out / "comp.mp4"
    shutil.copyfile(CLIP, asset)
    narrated = _request(
        "verify",
        out,
        tmp_path,
        capability="hyperframes.narrated",
        composition="comp",
        prompt="a brief",
    )
    narrated["assets"] = [str(asset)]
    done, result = _invoke(tmp_path, "verify", narrated, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    assert result["assets"][0]["passed"] is False
    assert result["assets"][0]["metrics"]["audio_streams"] == 0
    plain = _request("verify", out, tmp_path, composition="comp", prompt="a brief")
    plain["assets"] = [str(asset)]
    done, result = _invoke(tmp_path, "verify", plain, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    assert result["assets"][0]["passed"] is True


def _verify_loudness(
    root: Path, asset: Path, capability: str, measured: dict[str, float], **inputs: Any
) -> dict[str, Any]:
    packages = _fixture(root)
    out = root / "out"
    request = _request(
        "verify",
        out,
        root,
        capability=capability,
        composition="comp",
        prompt="a brief",
        **inputs,
    )
    request["assets"] = [str(asset)]
    env = _environment(root, _dirs(packages))
    env["FACET_TEST_LOUDNESS_JSON"] = json.dumps(measured)
    done, result = _invoke(root, "verify", request, env)
    assert done.returncode == 0, done.stderr
    assert result is not None
    return result["assets"][0]


@pytest.mark.skipif(
    FFPROBE is None or FFMPEG is None, reason="ffprobe and ffmpeg are not available"
)
def test_verify_passes_a_narrated_video_at_the_default_loudness_target(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    asset = _audio_mp4(out)
    integrated, peak = -13.6, -1.2
    verdict = _verify_loudness(
        tmp_path, asset, "hyperframes.narrated", {"input_i": integrated, "input_tp": peak}
    )
    assert verdict["passed"] is True
    assert verdict["metrics"]["integrated_lufs"] == integrated
    assert verdict["metrics"]["true_peak_dbtp"] == peak
    assert verdict["thresholds"] == {
        "loudness_lu": LOUDNESS_TOLERANCE_LU,
        "true_peak_dbtp": TRUE_PEAK_CEILING,
        "target_lufs": DEFAULT_TARGET_LUFS,
    }


@pytest.mark.skipif(
    FFPROBE is None or FFMPEG is None, reason="ffprobe and ffmpeg are not available"
)
def test_verify_fails_a_narrated_video_beyond_one_lu(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    asset = _audio_mp4(out)
    integrated = -12.5
    verdict = _verify_loudness(
        tmp_path, asset, "hyperframes.narrated", {"input_i": integrated, "input_tp": -1.2}
    )
    assert verdict["passed"] is False
    assert verdict["metrics"]["integrated_lufs"] == integrated
    assert verdict["thresholds"]["target_lufs"] == DEFAULT_TARGET_LUFS


@pytest.mark.skipif(
    FFPROBE is None or FFMPEG is None, reason="ffprobe and ffmpeg are not available"
)
def test_verify_fails_a_character_video_over_the_true_peak_ceiling(
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    asset = _audio_mp4(out)
    peak = -0.4
    verdict = _verify_loudness(
        tmp_path,
        asset,
        "hyperframes.character",
        {"input_i": DEFAULT_TARGET_LUFS, "input_tp": peak},
    )
    assert verdict["passed"] is False
    assert verdict["metrics"]["true_peak_dbtp"] == peak


@pytest.mark.skipif(
    FFPROBE is None or FFMPEG is None, reason="ffprobe and ffmpeg are not available"
)
def test_verify_accepts_the_loudness_tolerance_boundaries(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    asset = _audio_mp4(out)
    verdict = _verify_loudness(
        tmp_path, asset, "hyperframes.narrated", {"input_i": -15.0, "input_tp": -0.5}
    )
    assert verdict["passed"] is True


@pytest.mark.skipif(
    FFPROBE is None or FFMPEG is None, reason="ffprobe and ffmpeg are not available"
)
def test_verify_measures_against_the_record_loudness_target(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    asset = _audio_mp4(out)
    target = -16.0
    verdict = _verify_loudness(
        tmp_path,
        asset,
        "hyperframes.narrated",
        {"input_i": target, "input_tp": -1.5},
        **{"target-lufs": target},
    )
    assert verdict["passed"] is True
    assert verdict["thresholds"]["target_lufs"] == target


@pytest.mark.skipif(
    FFPROBE is None or FFMPEG is None, reason="ffprobe and ffmpeg are not available"
)
def test_verify_measures_real_loudness_without_a_shim(tmp_path: Path) -> None:
    packages = _fixture(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    asset = _audio_mp4(out)
    request = _request(
        "verify",
        out,
        tmp_path,
        capability="hyperframes.narrated",
        composition="comp",
        prompt="a brief",
    )
    request["assets"] = [str(asset)]
    done, result = _invoke(tmp_path, "verify", request, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    assert result is not None
    verdict = result["assets"][0]
    integrated = verdict["metrics"]["integrated_lufs"]
    peak = verdict["metrics"]["true_peak_dbtp"]
    assert isinstance(integrated, float) and isinstance(peak, float)
    assert verdict["thresholds"]["target_lufs"] == DEFAULT_TARGET_LUFS


@pytest.mark.skipif(
    FFPROBE is None or FFMPEG is None, reason="ffprobe and ffmpeg are not available"
)
def test_narrated_run_normalises_the_render_to_the_loudness_target(
    tmp_path: Path,
) -> None:
    packages = _fixture(tmp_path)
    piece, _comp = _narrated_comp(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(tmp_path, _dirs(packages))
    env["HF_STUB_MP4"] = str(_audio_mp4(tmp_path))
    done, result = _invoke(tmp_path, "run", _narrated_request(out, piece), env)
    assert done.returncode == 0, done.stderr
    assert result is not None
    asset = out / "comp.mp4"
    assert asset.is_file()
    verify = _request(
        "verify",
        out,
        piece,
        capability="hyperframes.narrated",
        composition="comp",
        prompt="a brief",
    )
    verify["assets"] = [str(asset)]
    done, result = _invoke(tmp_path, "verify", verify, _environment(tmp_path, _dirs(packages)))
    assert done.returncode == 0, done.stderr
    assert result is not None
    verdict = result["assets"][0]
    assert verdict["passed"] is True
    assert abs(verdict["metrics"]["integrated_lufs"] - DEFAULT_TARGET_LUFS) <= 1.0
    assert verdict["metrics"]["true_peak_dbtp"] <= TRUE_PEAK_CEILING


def test_old_spanish_names_are_absent_from_the_runner_sources() -> None:
    """The rename keeps no alias: the old ids and keys appear nowhere staged."""
    for name in OLD_SOURCES:
        text = (PACKAGE / name).read_text(encoding="utf-8")
        for old in OLD_TOKENS:
            assert old not in text, (name, old)
