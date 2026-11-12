"""The comfy-xl pull/start/run/stop cycle, with no facetmedia import.

The test stands in for the core where it can: it clones the manifest's repo
through a scratch git remote (``git url.<base>.insteadOf``), builds the
checkout at ``<home>/servers/comfy-xl/<version>/<rev[:12]>``, substitutes the
free port into the manifest's own launch argv and starts that argv, then runs
the package's runner as a subprocess against a stub ``facet_runner_sdk`` on
``PYTHONPATH``. The stub ComfyUI answers ``/system_stats``, ``/prompt``,
``/history`` and ``/view`` with a 64x48 Pillow PNG (or the fixture MP4 when
the posted graph saves a video), and records the graph it was posted, so the
test can prove the fill order, the model names and the port the runner
reached.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

import PIL.Image

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "comfy-xl"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
SERVER = MANIFEST["engine"]["server"]
MODEL_PATHS = {model["id"]: model["path"] for model in MANIFEST["models"]}
MODEL_DIRS = {
    "z-image-unet": "models/diffusion_models",
    "z-image-base-qwen-clip": "models/text_encoders",
    "z-image-base-vae": "models/vae",
    "wan14b-high-unet": "models/diffusion_models",
    "wan14b-low-unet": "models/diffusion_models",
    "wan14b-clip": "models/text_encoders",
    "wan14b-vae": "models/vae",
    "wan14b-lightx2v-high": "models/loras",
    "wan14b-lightx2v-low": "models/loras",
    "qwen-edit-unet": "models/diffusion_models",
    "qwen-edit-clip": "models/text_encoders",
    "qwen-edit-vae": "models/vae",
}
#: The 64x48, 24 fps, 49-frame MP4 the stub serves for a clip.
FLOW_WAN = json.loads((PACKAGE / "flows" / "wan22-i2v-14b.json").read_text(encoding="utf-8"))
#: Wan's official Chinese negative: what a clip submits when the entry omits it.
WAN_DEFAULT_NEGATIVE = FLOW_WAN["params"]["negative"]
CLIP_FIXTURE = ROOT / "tests" / "fixtures" / "clip.mp4"
PROMPT = "A handmade matte ceramic cup on a raw concrete surface, soft window light"
CLIP_PROMPT = "Fog drifting slowly between the pine trees at dawn, very slow camera push in"
SEED = 7
STEPS = 25
SHIFT = 3
CFG = 4
SAMPLER = "res_multistep"
SCHEDULER = "simple"
EDIT_STEPS = 40
EDIT_CFG = 4
EDIT_SHIFT = 3.1
EDIT_SAMPLER = "euler"
CLIP_STEPS = 20
CLIP_CFG = 5
CLIP_SAMPLER = "euler"
CLIP_SHIFT = 8
CLIP_LENGTH = 49
CLIP_FPS = 24
#: The draft clip flow: the lightx2v LoRAs, four steps and no CFG.
RAPIDO_FLOW = "wan22-i2v-14b-fast"
RAPIDO_STEPS = 4
RAPIDO_CFG = 1
RAPIDO_STRENGTH = 1.0
#: The sampling knobs the override tests set, to prove the entry wins.
STILL_OVERRIDE_STEPS = 30
STILL_OVERRIDE_CFG = 3
STILL_OVERRIDE_SHIFT = 4
CLIP_OVERRIDE_STEPS = 12
CLIP_OVERRIDE_CFG = 2
CLIP_OVERRIDE_SHIFT = 5
#: The suffix the runner gives every draft output, so none passes for a final.
DRAFT_SUFFIX = "-borrador"
WIDTH = 64
HEIGHT = 48
OK = 200
ENTRY = {"name": "foto-producto", "prompt": PROMPT, "seed": SEED, "width": WIDTH, "height": HEIGHT}

#: The pull-time SDK surface the runner touches; the real one is copied in.
STUB_SDK = """
import json
import sys
from pathlib import Path


class Request:
    def __init__(self, data):
        self.verb = str(data.get("verb", ""))
        self.capability = str(data.get("capability", ""))
        self.depth = str(data.get("depth", "quick"))
        self.inputs = dict(data.get("inputs") or {})
        self.out_dir = Path(str(data.get("out_dir", "")))
        self.piece_dir = Path(str(data.get("piece_dir", "")))
        self.assets = [Path(str(item)) for item in data.get("assets") or []]
        self._models = {str(k): Path(str(v)) for k, v in (data.get("models") or {}).items()}

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def model_path(self, model_id):
        return self._models[model_id]


class Runner:
    def __init__(self):
        self._verbs = {}

    def verb(self, name):
        def register(function):
            self._verbs[name] = function
            return function

        return register

    def run(self, argv):
        verb, *rest = argv
        values = {rest[index]: rest[index + 1] for index in range(0, len(rest), 2)}
        result = self._verbs[verb](Request.from_file(values["--input"]))
        Path(values["--result"]).write_text(json.dumps(result))
        return 0

    def main(self):
        raise SystemExit(self.run(sys.argv[1:]))
"""

#: A stub ComfyUI: the endpoints the runner uses, one 64x48 PNG.
STUB_MAIN = """
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import PIL.Image

GRAPH = Path(os.environ["STUB_GRAPH"])
UPLOAD = Path(os.environ["STUB_UPLOAD"])
CLIP = Path(os.environ["STUB_CLIP"])
SIZE = (64, 48)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return None

    def send_body(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def video_requested(self):
        return "clip.mp4" in urlsplit(self.path).query

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/system_stats":
            self.send_body(b'{"system": {"comfyui_version": "stub"}}', "application/json")
        elif path.startswith("/history/"):
            prompt_id = path.rsplit("/", 1)[-1]
            status = {"completed": True, "status_str": "success"}
            video = "SaveVideo" in GRAPH.read_text()
            filename = "clip.mp4" if video else "still.png"
            outputs = {
                "save": {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}
            }
            body = json.dumps({prompt_id: {"status": status, "outputs": outputs}})
            self.send_body(body.encode(), "application/json")
        elif path == "/view":
            if self.video_requested():
                self.send_body(CLIP.read_bytes(), "video/mp4")
                return
            buffer = BytesIO()
            PIL.Image.new("RGB", SIZE, (40, 90, 140)).save(buffer, format="PNG")
            self.send_body(buffer.getvalue(), "image/png")
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if urlsplit(self.path).path == "/upload/image":
            UPLOAD.write_bytes(body)
            answer = {"name": "source.png", "subfolder": "", "type": "input"}
            self.send_body(json.dumps(answer).encode(), "application/json")
            return
        GRAPH.write_text(body.decode())
        self.send_body(b'{"prompt_id": "stub-prompt"}', "application/json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8188)
    parser.add_argument("--disable-pinned-memory", action="store_true")
    args = parser.parse_args()
    ThreadingHTTPServer((args.listen, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
"""

#: Import the runner by file path and read one ``_flow_name``: the module runs
#: ``runner.main()`` at import, so argv points at a harmless empty verify and
#: the SystemExit it raises is caught.
PROBE_FLOW_NAME = """
import importlib.util
import sys

runner_path, request_path, result_path = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = [runner_path, "verify", "--input", request_path, "--result", result_path]
spec = importlib.util.spec_from_file_location("comfy_xl_runner", runner_path)
module = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(module)
except SystemExit:
    pass
print(module._flow_name("comfy-xl.clip", {"workflow": "wan22-i2v-14b-fast"}))
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env)


def _clone(tmp_path: Path) -> Path:
    """The checkout at the path the runner derives, fetched through a scratch remote."""
    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / "main.py").write_text(STUB_MAIN, encoding="utf-8")
    (remote / "requirements.txt").write_text("", encoding="utf-8")
    _git(remote, "init", "--quiet")
    _git(remote, "add", ".")
    _git(
        remote,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--quiet",
        "-m",
        "stub",
    )
    checkout = tmp_path / "home" / "servers" / "comfy-xl" / MANIFEST["version"] / SERVER["rev"][:12]
    checkout.mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.file://{remote}.insteadOf",
        "GIT_CONFIG_VALUE_0": SERVER["repo"],
    }
    _git(checkout, "init", "--quiet", env=env)
    _git(checkout, "remote", "add", "origin", SERVER["repo"], env=env)
    _git(checkout, "fetch", "--quiet", "--depth", "1", "origin", "HEAD", env=env)
    _git(checkout, "checkout", "--quiet", "--detach", "FETCH_HEAD", env=env)
    return checkout


def _model_files(home: Path) -> dict[str, Path]:
    """Placeholder model files where facet pulls them, with their real names."""
    paths: dict[str, Path] = {}
    for model_id, relative in MODEL_PATHS.items():
        path = home / "models" / "direct" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{model_id} placeholder".encode())
        paths[model_id] = path
    return paths


def _stub_sdk(tmp_path: Path) -> Path:
    folder = tmp_path / "stub-sdk"
    folder.mkdir()
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    facet_lib = folder / "facet_lib"
    facet_lib.mkdir()
    (facet_lib / "__init__.py").write_text("", encoding="utf-8")
    (facet_lib / "comfyclient.py").write_text(
        (ROOT / "lib" / "comfyclient.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return folder


def _launch(
    checkout: Path, graph_file: Path, upload_file: Path, port: int
) -> subprocess.Popen[str]:
    """Start the manifest's own launch argv with the free port substituted."""
    venv_bin = checkout / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    # A launcher, not a symlink: a symlink to the project venv's python loses
    # the pyvenv.cfg that puts Pillow on the stub server's path.
    python = venv_bin / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    argv = [token.replace("{{port}}", str(port)) for token in SERVER["launch"]]
    env = {
        **os.environ,
        "PATH": str(venv_bin) + os.pathsep + os.environ["PATH"],
        "STUB_GRAPH": str(graph_file),
        "STUB_UPLOAD": str(upload_file),
        "STUB_CLIP": str(CLIP_FIXTURE),
    }
    return subprocess.Popen(
        argv,
        cwd=checkout,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_healthy(url: str, timeout_s: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == OK:
                    return True
        except OSError:
            time.sleep(0.05)
    return False


def _request(
    verb: str,
    out_dir: Path,
    piece_dir: Path,
    models: dict[str, Path],
    assets: tuple[Path, ...] = (),
    inputs: dict[str, object] | None = None,
    capability: str = "comfy-xl.still",
) -> dict[str, object]:
    merged: dict[str, object] = {"image": [ENTRY], **(inputs or {})}
    return {
        "protocol": 1,
        "verb": verb,
        "capability": capability,
        "inputs": merged,
        "out_dir": str(out_dir),
        "piece_dir": str(piece_dir),
        "models": {key: str(value) for key, value in models.items()},
        "assets": [str(path) for path in assets],
    }


def _record_request(
    verb: str,
    out_dir: Path,
    piece_dir: Path,
    models: dict[str, Path],
    assets: tuple[Path, ...] = (),
    entry: dict[str, object] | None = None,
    capability: str = "comfy-xl.still",
) -> dict[str, object]:
    """The request ``facet check`` and ``facet preview`` make: the record's params."""
    request = _request(verb, out_dir, piece_dir, models, assets, capability=capability)
    return {**request, "inputs": dict(entry or ENTRY)}


def _call(
    stub_dir: Path,
    verb: str,
    request: dict[str, object],
    tmp_path: Path,
    env: dict[str, str],
) -> tuple[dict[str, object], str]:
    input_path = tmp_path / f"{verb}-request.json"
    result_path = tmp_path / f"{verb}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            verb,
            "--input",
            str(input_path),
            "--result",
            str(result_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(result_path.read_text(encoding="utf-8")), done.stdout


def _environment(stub_dir: Path, home: Path, url: str) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "FACET_MODELS": str(home / "models" / "direct"),
        "FACET_SERVER_URL": url,
    }


def _server(
    tmp_path: Path, home: Path | None = None, models: dict[str, Path] | None = None
) -> tuple[Path, Path, Path, Path, Path, dict[str, str], str, subprocess.Popen[str]]:
    """The stub checkout, dirs, env and process one run needs; the caller stops it."""
    house = home or tmp_path / "home"
    owned = models or _model_files(house)
    graph_file = tmp_path / "graph.json"
    upload_file = tmp_path / "upload.bin"
    stub_dir = _stub_sdk(tmp_path)
    checkout = _clone(tmp_path)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    process = _launch(checkout, graph_file, upload_file, port)
    assert _wait_healthy(f"{url}/system_stats"), "the stub ComfyUI never became healthy"
    return house, owned, graph_file, stub_dir, checkout, out, url, process


def test_the_cycle_links_the_models_returns_bare_names_and_verifies(tmp_path: Path) -> None:
    home, models, graph_file, stub_dir, checkout, out, url, process = _server(tmp_path)
    try:
        env = _environment(stub_dir, home, url)
        result, printed = _call(
            stub_dir, "run", _request("run", out, tmp_path, models), tmp_path, env
        )
        assert "foto-producto.png ok" in printed
        asset = result["assets"][0]
        assert asset["file"] == "foto-producto.png"
        assert (asset["kind"], asset["mime"]) == ("image", "image/png")
        assert asset["seed"] == SEED
        assert asset["properties"] == {"width": WIDTH, "height": HEIGHT, "seed": SEED}
        assert (out / "foto-producto.png").is_file()
        with PIL.Image.open(out / "foto-producto.png") as image:
            assert image.size == (WIDTH, HEIGHT)
        _assert_links(checkout, models)
        _assert_graph(graph_file)
        _assert_refreshed(stub_dir, home, url, checkout, models, out, tmp_path)
    finally:
        process.terminate()
        process.wait(timeout=10)
    _assert_verify_and_preview(stub_dir, home, url, out, models, tmp_path)


def test_an_entry_sets_every_sampling_knob_and_the_record_shows_them(tmp_path: Path) -> None:
    home, models, graph_file, stub_dir, checkout, out, url, process = _server(tmp_path)
    entry = {
        **ENTRY,
        "steps": STILL_OVERRIDE_STEPS,
        "cfg": STILL_OVERRIDE_CFG,
        "sampler": "euler",
        "scheduler": "beta",
        "shift": STILL_OVERRIDE_SHIFT,
    }
    try:
        env = _environment(stub_dir, home, url)
        request = _request("run", out, tmp_path, models, inputs={"image": [entry]})
        result, _ = _call(stub_dir, "run", request, tmp_path, env)
        graph = json.loads(graph_file.read_text(encoding="utf-8"))["prompt"]
        assert graph["sampler"]["inputs"]["steps"] == STILL_OVERRIDE_STEPS
        assert graph["sampler"]["inputs"]["cfg"] == STILL_OVERRIDE_CFG
        assert graph["sampler"]["inputs"]["sampler_name"] == "euler"
        assert graph["sampler"]["inputs"]["scheduler"] == "beta"
        assert graph["model"]["inputs"]["shift"] == STILL_OVERRIDE_SHIFT
        # The record's params are the flow defaults merged with the entry.
        assert result["assets"][0]["params"] == {
            "name": "foto-producto",
            "prompt": PROMPT,
            "seed": SEED,
            "width": WIDTH,
            "height": HEIGHT,
            "steps": 30,
            "cfg": 3,
            "sampler": "euler",
            "scheduler": "beta",
            "shift": 4,
        }
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_an_edit_uploads_the_reference_and_fills_the_qwen_graph(tmp_path: Path) -> None:
    home, models, graph_file, stub_dir, checkout, out, url, process = _server(tmp_path)
    reference = tmp_path / "referencia.png"
    PIL.Image.new("RGB", (32, 24), (10, 20, 30)).save(reference)
    try:
        env = _environment(stub_dir, home, url)
        request = _request(
            "run",
            out,
            tmp_path,
            models,
            inputs={"source": str(reference)},
            capability="comfy-xl.edit",
        )
        result, printed = _call(stub_dir, "run", request, tmp_path, env)
        assert "referencia.png uploaded as source.png" in printed
        assert "foto-producto.png ok" in printed
        assert result["assets"][0]["file"] == "foto-producto.png"
        _assert_links(checkout, models)
        _assert_edit_graph(graph_file)
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_a_rapido_clip_is_a_borrador_draft(tmp_path: Path) -> None:
    home, models, graph_file, stub_dir, checkout, out, url, process = _server(tmp_path)
    source = tmp_path / "primer-cuadro.png"
    PIL.Image.new("RGB", (WIDTH, HEIGHT), (12, 34, 56)).save(source)
    entry = _clip_entry(source)
    try:
        env = _environment(stub_dir, home, url)
        request = _request(
            "run",
            out,
            tmp_path,
            models,
            inputs={"workflow": RAPIDO_FLOW, "image": [entry]},
            capability="comfy-xl.clip",
        )
        result, printed = _call(stub_dir, "run", request, tmp_path, env)
        assert f"bosque-niebla{DRAFT_SUFFIX}.mp4 ok" in printed
        asset = result["assets"][0]
        assert asset["file"] == f"bosque-niebla{DRAFT_SUFFIX}.mp4"
        assert (asset["kind"], asset["mime"]) == ("video", "video/mp4")
        assert asset["properties"] == {
            "width": WIDTH,
            "height": HEIGHT,
            "seed": SEED,
            "draft": True,
        }
        assert (out / f"bosque-niebla{DRAFT_SUFFIX}.mp4").read_bytes() == CLIP_FIXTURE.read_bytes()
        _assert_links(checkout, models)
        _assert_rapido_graph(graph_file)
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_a_wan14b_entry_override_fills_both_ksamplers(tmp_path: Path) -> None:
    home, models, graph_file, stub_dir, checkout, out, url, process = _server(tmp_path)
    source = tmp_path / "primer-cuadro.png"
    PIL.Image.new("RGB", (WIDTH, HEIGHT), (12, 34, 56)).save(source)
    entry = {
        **_clip_entry(source),
        "steps": CLIP_OVERRIDE_STEPS,
        "cfg": CLIP_OVERRIDE_CFG,
        "sampler": "uni_pc",
        "scheduler": "euler",
        "shift": CLIP_OVERRIDE_SHIFT,
    }
    try:
        env = _environment(stub_dir, home, url)
        request = _request(
            "run",
            out,
            tmp_path,
            models,
            inputs={"workflow": "wan22-i2v-14b", "image": [entry]},
            capability="comfy-xl.clip",
        )
        result, _ = _call(stub_dir, "run", request, tmp_path, env)
        graph = json.loads(graph_file.read_text(encoding="utf-8"))["prompt"]
        for name in ("sampler_high", "sampler_low"):
            assert graph[name]["inputs"]["steps"] == CLIP_OVERRIDE_STEPS
            assert graph[name]["inputs"]["cfg"] == CLIP_OVERRIDE_CFG
            assert graph[name]["inputs"]["sampler_name"] == "uni_pc"
            assert graph[name]["inputs"]["scheduler"] == "euler"
        assert graph["model_high"]["inputs"]["shift"] == CLIP_OVERRIDE_SHIFT
        assert graph["model_low"]["inputs"]["shift"] == CLIP_OVERRIDE_SHIFT
        params = result["assets"][0]["params"]
        assert (params["steps"], params["cfg"], params["sampler"]) == (12, 2, "uni_pc")
        assert (params["scheduler"], params["shift"]) == ("euler", 5)
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_the_runner_resolves_the_rapido_clip_flow(tmp_path: Path) -> None:
    stub_dir = _stub_sdk(tmp_path)
    request_path = tmp_path / "probe-request.json"
    request = _request(
        "verify",
        tmp_path,
        tmp_path,
        {},
        inputs={"workflow": RAPIDO_FLOW},
        capability="comfy-xl.clip",
    )
    request_path.write_text(json.dumps(request), encoding="utf-8")
    result_path = tmp_path / "probe-result.json"
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            PROBE_FLOW_NAME,
            str(PACKAGE / "runner.py"),
            str(request_path),
            str(result_path),
        ],
        env={**os.environ, "PYTHONPATH": str(stub_dir)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.strip() == RAPIDO_FLOW


def test_an_unknown_workflow_fails_before_anything_runs(tmp_path: Path) -> None:
    stub_dir = _stub_sdk(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    request = _request("run", out, tmp_path, {}, inputs={"workflow": "z-image-bad"})
    input_path = tmp_path / "bad-request.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            "run",
            "--input",
            str(input_path),
            "--result",
            str(tmp_path / "bad-result.json"),
        ],
        env={**os.environ, "PYTHONPATH": str(stub_dir)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode != 0
    assert "unknown workflow" in done.stderr


def test_an_unknown_clip_workflow_fails_before_anything_runs(tmp_path: Path) -> None:
    stub_dir = _stub_sdk(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    request = _request(
        "run",
        out,
        tmp_path,
        {},
        inputs={"workflow": "wan22-i2v-14b-bad"},
        capability="comfy-xl.clip",
    )
    input_path = tmp_path / "bad-clip-request.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            "run",
            "--input",
            str(input_path),
            "--result",
            str(tmp_path / "bad-clip-result.json"),
        ],
        env={**os.environ, "PYTHONPATH": str(stub_dir)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode != 0
    assert "unknown workflow" in done.stderr
    assert not (tmp_path / "bad-clip-result.json").exists()


def _clip_entry(source: Path, negative: str | None = None) -> dict[str, object]:
    """One clip: the still is the first frame, the prompt describes the movement."""
    entry: dict[str, object] = {
        "name": "bosque-niebla",
        "image": str(source),
        "prompt": CLIP_PROMPT,
        "seed": SEED,
        "width": WIDTH,
        "height": HEIGHT,
        "length": CLIP_LENGTH,
    }
    if negative is not None:
        entry["negative"] = negative
    return entry


def _assert_links(checkout: Path, models: dict[str, Path]) -> None:
    for model_id, relative in MODEL_DIRS.items():
        link = checkout / relative / Path(MODEL_PATHS[model_id]).name
        assert link.is_symlink(), relative
        assert link.resolve() == models[model_id].resolve(), relative


def _assert_graph(graph_file: Path) -> None:
    graph = json.loads(graph_file.read_text(encoding="utf-8"))["prompt"]
    assert graph["positive"]["inputs"]["text"] == PROMPT
    assert graph["sampler"]["inputs"]["seed"] == SEED
    assert graph["sampler"]["inputs"]["steps"] == STEPS
    assert graph["sampler"]["inputs"]["cfg"] == CFG
    assert graph["sampler"]["inputs"]["sampler_name"] == SAMPLER
    assert graph["sampler"]["inputs"]["scheduler"] == SCHEDULER
    assert graph["model"]["inputs"]["shift"] == SHIFT
    assert graph["latent"]["inputs"]["width"] == WIDTH
    assert graph["latent"]["inputs"]["height"] == HEIGHT
    assert graph["save"]["inputs"]["filename_prefix"] == "foto-producto"
    assert graph["unet"]["inputs"]["unet_name"] == Path(MODEL_PATHS["z-image-unet"]).name
    assert graph["clip"]["inputs"]["clip_name"] == Path(MODEL_PATHS["z-image-base-qwen-clip"]).name
    assert graph["vae"]["inputs"]["vae_name"] == Path(MODEL_PATHS["z-image-base-vae"]).name


def _assert_edit_graph(graph_file: Path) -> None:
    graph = json.loads(graph_file.read_text(encoding="utf-8"))["prompt"]
    assert graph["source"]["class_type"] == "LoadImage"
    assert graph["source"]["inputs"]["image"] == "source.png"
    assert graph["sized"]["inputs"]["width"] == WIDTH
    assert graph["sized"]["inputs"]["height"] == HEIGHT
    assert graph["positive_encode"]["inputs"]["prompt"] == PROMPT
    assert graph["positive_encode"]["inputs"]["image1"] == ["sized", 0]
    assert graph["negative_encode"]["inputs"]["prompt"] == ""
    assert graph["positive_method"]["inputs"]["conditioning"] == ["positive_encode", 0]
    assert graph["negative_method"]["inputs"]["conditioning"] == ["negative_encode", 0]
    assert graph["latent"]["inputs"]["pixels"] == ["sized", 0]
    assert graph["sampler"]["inputs"]["seed"] == SEED
    assert graph["sampler"]["inputs"]["steps"] == EDIT_STEPS
    assert graph["sampler"]["inputs"]["cfg"] == EDIT_CFG
    assert graph["sampler"]["inputs"]["sampler_name"] == EDIT_SAMPLER
    assert graph["sampler"]["inputs"]["scheduler"] == SCHEDULER
    assert graph["sampler"]["inputs"]["denoise"] == 1
    assert graph["model_shift"]["inputs"]["shift"] == EDIT_SHIFT
    assert graph["save"]["inputs"]["filename_prefix"] == "foto-producto"
    assert graph["unet"]["inputs"]["unet_name"] == Path(MODEL_PATHS["qwen-edit-unet"]).name
    assert graph["clip"]["inputs"]["clip_name"] == Path(MODEL_PATHS["qwen-edit-clip"]).name
    assert graph["vae"]["inputs"]["vae_name"] == Path(MODEL_PATHS["qwen-edit-vae"]).name
    assert "$" not in json.dumps(graph)


def _assert_rapido_graph(graph_file: Path) -> None:
    graph = json.loads(graph_file.read_text(encoding="utf-8"))["prompt"]
    assert graph["start"]["class_type"] == "LoadImage"
    assert graph["start"]["inputs"]["image"] == "source.png"
    assert graph["positive"]["inputs"]["text"] == CLIP_PROMPT
    assert graph["i2v"]["class_type"] == "WanImageToVideo"
    assert graph["i2v"]["inputs"]["width"] == WIDTH
    assert graph["i2v"]["inputs"]["height"] == HEIGHT
    assert graph["video"]["inputs"]["fps"] == CLIP_FPS
    assert graph["save"]["inputs"]["filename_prefix"] == "bosque-niebla"
    assert graph["negative"]["inputs"]["text"] == WAN_DEFAULT_NEGATIVE
    assert (
        graph["lora_high"]["inputs"]["lora_name"] == Path(MODEL_PATHS["wan14b-lightx2v-high"]).name
    )
    assert graph["lora_low"]["inputs"]["lora_name"] == Path(MODEL_PATHS["wan14b-lightx2v-low"]).name
    assert graph["lora_high"]["inputs"]["strength_model"] == RAPIDO_STRENGTH
    assert graph["model_high"]["inputs"]["model"] == ["lora_high", 0]
    assert graph["model_low"]["inputs"]["model"] == ["lora_low", 0]
    assert graph["sampler_high"]["inputs"]["steps"] == RAPIDO_STEPS
    assert graph["sampler_low"]["inputs"]["cfg"] == RAPIDO_CFG
    for name in ("sampler_high", "sampler_low"):
        assert graph[name]["inputs"]["sampler_name"] == CLIP_SAMPLER
        assert graph[name]["inputs"]["scheduler"] == SCHEDULER
    assert graph["model_high"]["inputs"]["shift"] == CLIP_SHIFT
    assert graph["model_low"]["inputs"]["shift"] == CLIP_SHIFT
    assert graph["unet_high"]["inputs"]["unet_name"] == Path(MODEL_PATHS["wan14b-high-unet"]).name
    assert graph["unet_low"]["inputs"]["unet_name"] == Path(MODEL_PATHS["wan14b-low-unet"]).name
    assert "$" not in json.dumps(graph)


def _assert_refreshed(
    stub_dir: Path,
    home: Path,
    url: str,
    checkout: Path,
    models: dict[str, Path],
    out: Path,
    tmp_path: Path,
) -> None:
    """A link replaced between runs is a symlink again after the next run."""
    link = checkout / MODEL_DIRS["z-image-base-vae"] / Path(MODEL_PATHS["z-image-base-vae"]).name
    link.unlink()
    link.write_text("stale", encoding="utf-8")
    env = _environment(stub_dir, home, url)
    _call(stub_dir, "run", _request("run", out, tmp_path, models), tmp_path, env)
    assert link.is_symlink()
    assert link.resolve() == models["z-image-base-vae"].resolve()


def _assert_verify_and_preview(
    stub_dir: Path, home: Path, url: str, out: Path, models: dict[str, Path], tmp_path: Path
) -> None:
    env = _environment(stub_dir, home, url)
    good = out / "foto-producto.png"
    # facet run --verify sends the piece's image array...
    verdict, _ = _call(
        stub_dir, "verify", _request("verify", out, tmp_path, models, (good,)), tmp_path, env
    )
    assert verdict["assets"][0]["passed"] is True
    # ...facet check sends the record's params for one asset (the entry itself).
    verdict, _ = _call(
        stub_dir, "verify", _record_request("verify", out, tmp_path, models, (good,)), tmp_path, env
    )
    entry = verdict["assets"][0]
    assert entry["passed"] is True
    assert entry["metrics"] == {"width": WIDTH, "height": HEIGHT}
    wrong = out / "wrong.png"
    PIL.Image.new("RGB", (32, 32), (1, 2, 3)).save(wrong)
    verdict, _ = _call(
        stub_dir,
        "verify",
        _record_request("verify", out, tmp_path, models, (wrong,)),
        tmp_path,
        env,
    )
    assert verdict["assets"][0]["passed"] is False
    _call(
        stub_dir,
        "preview",
        _record_request("preview", out, tmp_path, models, (good,)),
        tmp_path,
        env,
    )
    data = json.loads((out / "foto-producto.png.preview.json").read_text(encoding="utf-8"))
    assert set(data) == {"preview", "kind", "summary", "name", "prompt", "seed", "width", "height"}
    assert data["kind"] == "image"
    assert data["name"] == "foto-producto"
    assert data["prompt"] == PROMPT
    assert (data["seed"], data["width"], data["height"]) == (SEED, WIDTH, HEIGHT)


def _custom_flow(tmp_path: Path, unet_name: str | None = None) -> Path:
    """A copy of the default still flow with one knob changed, beside the piece."""
    data = json.loads((PACKAGE / "flows" / "z-image.json").read_text(encoding="utf-8"))
    data["params"]["steps"] = STILL_OVERRIDE_STEPS
    if unet_name is not None:
        data["graph"]["unet"]["inputs"]["unet_name"] = unet_name
    path = tmp_path / "flujo-propio.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _call_failing(
    stub_dir: Path, request: dict[str, object], tmp_path: Path, name: str
) -> subprocess.CompletedProcess[str]:
    """Run the runner without a server, for the failures that come before it."""
    input_path = tmp_path / f"{name}-request.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            "run",
            "--input",
            str(input_path),
            "--result",
            str(tmp_path / f"{name}-result.json"),
        ],
        env={**os.environ, "PYTHONPATH": str(stub_dir)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_a_flow_and_a_workflow_together_fail_before_anything_runs(tmp_path: Path) -> None:
    stub_dir = _stub_sdk(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    flow = _custom_flow(tmp_path)
    request = _request("run", out, tmp_path, {}, inputs={"flow": flow.name, "workflow": "z-image"})
    done = _call_failing(stub_dir, request, tmp_path, "flow-both")
    assert done.returncode != 0
    assert "give either flow or workflow, not both" in done.stderr
    assert not (tmp_path / "flow-both-result.json").exists()


def test_a_foreign_model_file_fails_before_anything_runs(tmp_path: Path) -> None:
    stub_dir = _stub_sdk(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    flow = _custom_flow(tmp_path, unet_name="ajeno.safetensors")
    request = _request("run", out, tmp_path, {}, inputs={"flow": flow.name})
    done = _call_failing(stub_dir, request, tmp_path, "flow-foreign")
    assert done.returncode != 0
    assert "ajeno.safetensors" in done.stderr
    for relative in MODEL_PATHS.values():
        assert Path(relative).name in done.stderr
    assert not (tmp_path / "flow-foreign-result.json").exists()


def test_a_custom_flow_runs_like_the_package_flow(tmp_path: Path) -> None:
    home = tmp_path / "home"
    models = _model_files(home)
    graph_file = tmp_path / "graph.json"
    upload_file = tmp_path / "upload.bin"
    stub_dir = _stub_sdk(tmp_path)
    checkout = _clone(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    flow = _custom_flow(tmp_path)
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    process = _launch(checkout, graph_file, upload_file, port)
    try:
        assert _wait_healthy(f"{url}/system_stats"), "the stub ComfyUI never became healthy"
        env = _environment(stub_dir, home, url)
        request = _request("run", out, tmp_path, models, inputs={"flow": flow.name})
        result, printed = _call(stub_dir, "run", request, tmp_path, env)
        assert "foto-producto.png ok" in printed
        asset = result["assets"][0]
        assert asset["file"] == "foto-producto.png"
        assert asset["properties"] == {"width": WIDTH, "height": HEIGHT, "seed": SEED}
        assert asset["params"] == {
            "width": WIDTH,
            "height": HEIGHT,
            "seed": SEED,
            "steps": STILL_OVERRIDE_STEPS,
            "shift": SHIFT,
            "cfg": CFG,
            "sampler": SAMPLER,
            "scheduler": SCHEDULER,
            "name": "foto-producto",
            "prompt": PROMPT,
            "flow": str(flow),
            "flow_sha256": hashlib.sha256(flow.read_bytes()).hexdigest(),
        }
        _assert_links(checkout, models)
        graph = json.loads(graph_file.read_text(encoding="utf-8"))["prompt"]
        assert graph["sampler"]["inputs"]["steps"] == STILL_OVERRIDE_STEPS
        assert "$" not in json.dumps(graph)
    finally:
        process.terminate()
        process.wait(timeout=10)
