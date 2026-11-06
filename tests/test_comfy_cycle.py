"""The comfy pull/start/run/stop cycle, with no facetmedia import.

The test stands in for the core where it can: it clones the manifest's repo
through a scratch git remote (``git url.<base>.insteadOf``), builds the
checkout at ``<home>/servers/comfy/<version>/<rev[:12]>``, substitutes the
free port into the manifest's own launch argv and starts that argv, then runs
the package's runner as a subprocess against a stub ``facet_runner_sdk`` on
``PYTHONPATH``. The stub ComfyUI answers ``/system_stats``, ``/prompt``,
``/history`` and ``/view`` with a 64x48 Pillow PNG, and records the graph it
was posted, so the test can prove the fill order, the model names and the
port the runner reached.
"""

from __future__ import annotations

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
PACKAGE = ROOT / "packages" / "comfy"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
SERVER = MANIFEST["engine"]["server"]
MODEL_PATHS = {model["id"]: model["path"] for model in MANIFEST["models"]}
MODEL_DIRS = {
    "z-image-turbo-unet": "models/diffusion_models",
    "z-image-qwen-clip": "models/text_encoders",
    "z-image-vae": "models/vae",
    "flux2-klein-unet": "models/diffusion_models",
    "flux2-qwen-clip": "models/text_encoders",
    "flux2-klein-vae": "models/vae",
}
PROMPT = "A handmade matte ceramic cup on a raw concrete surface, soft window light"
SEED = 7
STEPS = 8
KLEIN_STEPS = 4
SHIFT = 3
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

#: A stub ComfyUI: the four endpoints the runner uses, one 64x48 PNG.
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

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/system_stats":
            self.send_body(b'{"system": {"comfyui_version": "stub"}}', "application/json")
        elif path.startswith("/history/"):
            prompt_id = path.rsplit("/", 1)[-1]
            status = {"completed": True, "status_str": "success"}
            outputs = {
                "save": {"images": [{"filename": "still.png", "subfolder": "", "type": "output"}]}
            }
            body = json.dumps({prompt_id: {"status": status, "outputs": outputs}})
            self.send_body(body.encode(), "application/json")
        elif path == "/view":
            buffer = BytesIO()
            PIL.Image.new("RGB", SIZE, (40, 90, 140)).save(buffer, format="PNG")
            self.send_body(buffer.getvalue(), "image/png")
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        GRAPH.write_text(self.rfile.read(length).decode())
        self.send_body(b'{"prompt_id": "stub-prompt"}', "application/json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8188)
    args = parser.parse_args()
    ThreadingHTTPServer((args.listen, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
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
    checkout = tmp_path / "home" / "servers" / "comfy" / MANIFEST["version"] / SERVER["rev"][:12]
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
    return folder


def _launch(checkout: Path, graph_file: Path, port: int) -> subprocess.Popen[str]:
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
    workflow: str | None = None,
) -> dict[str, object]:
    inputs: dict[str, object] = {"image": [ENTRY]}
    if workflow is not None:
        inputs["workflow"] = workflow
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "comfy.still",
        "inputs": inputs,
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
) -> dict[str, object]:
    """The request ``facet check`` and ``facet preview`` make: the record's params."""
    return {**_request(verb, out_dir, piece_dir, models, assets), "inputs": dict(ENTRY)}


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


def test_the_cycle_links_the_models_returns_bare_names_and_verifies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    models = _model_files(home)
    graph_file = tmp_path / "graph.json"
    stub_dir = _stub_sdk(tmp_path)
    checkout = _clone(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    process = _launch(checkout, graph_file, port)
    try:
        assert _wait_healthy(f"{url}/system_stats"), "the stub ComfyUI never became healthy"
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


def test_the_klein_flow_renders_through_the_same_runner(tmp_path: Path) -> None:
    home = tmp_path / "home"
    models = _model_files(home)
    graph_file = tmp_path / "graph.json"
    stub_dir = _stub_sdk(tmp_path)
    checkout = _clone(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    process = _launch(checkout, graph_file, port)
    try:
        assert _wait_healthy(f"{url}/system_stats"), "the stub ComfyUI never became healthy"
        env = _environment(stub_dir, home, url)
        request = _request("run", out, tmp_path, models, workflow="flux2-klein-4b")
        result, printed = _call(stub_dir, "run", request, tmp_path, env)
        assert "foto-producto.png ok" in printed
        asset = result["assets"][0]
        assert asset["file"] == "foto-producto.png"
        assert (out / "foto-producto.png").is_file()
        _assert_links(checkout, models)
        _assert_klein_graph(graph_file)
    finally:
        process.terminate()
        process.wait(timeout=10)


def _assert_klein_graph(graph_file: Path) -> None:
    graph = json.loads(graph_file.read_text(encoding="utf-8"))["prompt"]
    assert graph["positive"]["inputs"]["text"] == PROMPT
    assert graph["noise"]["inputs"]["noise_seed"] == SEED
    assert graph["sigmas"]["inputs"]["steps"] == KLEIN_STEPS
    assert graph["latent"]["class_type"] == "EmptyFlux2LatentImage"
    assert graph["latent"]["inputs"]["width"] == WIDTH
    assert graph["latent"]["inputs"]["height"] == HEIGHT
    assert "shift" not in json.dumps(graph)
    assert graph["save"]["inputs"]["filename_prefix"] == "foto-producto"
    assert graph["unet"]["inputs"]["unet_name"] == Path(MODEL_PATHS["flux2-klein-unet"]).name
    assert graph["clip"]["inputs"]["clip_name"] == Path(MODEL_PATHS["flux2-qwen-clip"]).name
    assert graph["vae"]["inputs"]["vae_name"] == Path(MODEL_PATHS["flux2-klein-vae"]).name


def test_an_unknown_workflow_fails_before_anything_runs(tmp_path: Path) -> None:
    stub_dir = _stub_sdk(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    request = _request("run", out, tmp_path, {}, workflow="flux2-klain-4b")
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
    assert graph["model"]["inputs"]["shift"] == SHIFT
    assert graph["latent"]["inputs"]["width"] == WIDTH
    assert graph["latent"]["inputs"]["height"] == HEIGHT
    assert graph["save"]["inputs"]["filename_prefix"] == "foto-producto"
    assert graph["unet"]["inputs"]["unet_name"] == Path(MODEL_PATHS["z-image-turbo-unet"]).name
    assert graph["clip"]["inputs"]["clip_name"] == Path(MODEL_PATHS["z-image-qwen-clip"]).name
    assert graph["vae"]["inputs"]["vae_name"] == Path(MODEL_PATHS["z-image-vae"]).name


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
    link = checkout / MODEL_DIRS["z-image-vae"] / Path(MODEL_PATHS["z-image-vae"]).name
    link.unlink()
    link.write_text("stale", encoding="utf-8")
    env = _environment(stub_dir, home, url)
    _call(stub_dir, "run", _request("run", out, tmp_path, models), tmp_path, env)
    assert link.is_symlink()
    assert link.resolve() == models["z-image-vae"].resolve()


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
