"""The blender cycle through a stub host: the launcher, doctor and assets.

No real Blender runs here. A stub ``blender`` stands where the host binary
does: it answers ``--version``, records each launch, and executes the package
entry with a stub ``bpy`` on its path, so the entry takes its in-Blender
branch. The stub scene is camera-only — the entry runs a piece's own script,
and that script is what builds the scene.

The launcher process deliberately does *not* see the stub ``bpy``: it must
resolve ``BLENDER_EXE`` and drive the host, which is the route the spec names
(convert paths, one retry only on a WSL interop failure).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"
RUNNER = PACKAGE / "runner.py"
GENERIC_SCHEMA = json.loads(
    (ROOT / "schemas" / "preview" / "generic.schema.json").read_text(encoding="utf-8")
)
#: The scripted piece the launcher drives: small, fast and all facet owns.
WIDTH = 320
HEIGHT = 200
#: The attempts a WSL interop failure may take: the first launch and one retry.
RETRIES = 2

STUB_BPY = r'''
"""A stub bpy: enough of Blender to run a camera-only script and write a PNG."""

import os


class Camera:
    def __init__(self):
        self.type = "PERSP"
        self.lens = 50.0
        self.ortho_scale = 1.0
        self.clip_start = 0.1
        self.clip_end = 100.0


class Cameras:
    def new(self, name):
        return Camera()


class Object:
    def __init__(self, name, data=None):
        self.name = name
        self.data = data
        self.type = "CAMERA"
        self.location = (0.0, 0.0, 0.0)
        self.rotation_euler = (0.0, 0.0, 0.0)
        self.rotation_mode = "XYZ"

    def keyframe_insert(self, path, frame=1):
        return None


class LinkedObjects(list):
    def link(self, obj):
        self.append(obj)


class Collection:
    def __init__(self):
        self.objects = LinkedObjects()


class Objects:
    def new(self, name, data=None):
        return Object(name, data)


class FakeImage:
    def __init__(self, width, height):
        self.size = (width, height)
        self.pixels = [(index % 11) / 11 for index in range(width * height * 4)]


class Images:
    def load(self, path):
        from PIL import Image as PILImage

        with PILImage.open(path) as image:
            return FakeImage(image.width, image.height)

    def remove(self, image):
        return None


class DataBlocks:
    def __init__(self):
        self.cameras = Cameras()
        self.objects = Objects()
        self.images = Images()


class Render:
    def __init__(self):
        self.resolution_x = 1920
        self.resolution_y = 1080
        self.resolution_percentage = 100
        self.engine = "BLENDER_EEVEE"
        self.filepath = ""


class Eevee:
    def __init__(self):
        self.taa_render_samples = 64


class View:
    def __init__(self):
        self.exposure = 0.0
        self.look = "None"


class Scene:
    def __init__(self):
        self.render = Render()
        self.eevee = Eevee()
        self.view_settings = View()
        self.frame_start = 1
        self.frame_end = 120
        self.camera = None
        self.collection = Collection()


class WmOps:
    def read_factory_settings(self, use_empty=False):
        context.scene = Scene()


class RenderOps:
    def render(self, write_still=False):
        target = os.environ.get("STUB_PNG_OUT", "") or context.scene.render.filepath
        if not target:
            return
        from PIL import Image as PILImage

        size = (context.scene.render.resolution_x, context.scene.render.resolution_y)
        PILImage.new("RGB", size, (20, 40, 60)).save(target)


class Ops:
    def __init__(self):
        self.wm = WmOps()
        self.render = RenderOps()


class App:
    version_string = "5.2.2 LTS"


class Context:
    def __init__(self):
        self.scene = Scene()


context = Context()
app = App()
data = DataBlocks()
ops = Ops()
'''

STUB_BLENDER = '''#!{python}
"""A stub Blender: answers --version, records attempts, runs the package entry."""

import os
import runpy
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if "--version" in args:
        print("Blender 5.2.2 LTS")
        return 0
    counter = os.environ.get("STUB_ATTEMPTS", "")
    attempt = 1
    if counter:
        path = Path(counter)
        attempt = int(path.read_text()) + 1 if path.exists() else 1
        path.write_text(str(attempt))
    mode = os.environ.get("STUB_BLENDER_MODE", "run")
    if mode == "fail-plain":
        print("scene blew up", file=sys.stderr)
        return 3
    if mode == "fail-interop-always" or (mode == "fail-interop-once" and attempt == 1):
        print("UtilAcceptVsock: AcceptVsock failed 110", file=sys.stderr)
        return 1
    entry = args[args.index("--python") + 1]
    rest = args[args.index("--python") + 2 :]
    sys.path.insert(0, os.environ["STUB_BPY"])
    sys.argv = [entry, *rest]
    runpy.run_path(entry, run_name="__main__")
    return 0


raise SystemExit(main())
'''


def _load_runner():
    spec = importlib.util.spec_from_file_location("blender_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def _stub_bpy(tmp_path: Path) -> Path:
    folder = tmp_path / "stub-bpy"
    folder.mkdir(exist_ok=True)
    (folder / "bpy.py").write_text(STUB_BPY, encoding="utf-8")
    return folder


def _stub_blender(tmp_path: Path) -> Path:
    path = tmp_path / "bin" / "blender"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(STUB_BLENDER.replace("{python}", sys.executable), encoding="utf-8")
    path.chmod(0o755)
    return path


def _script(tmp_path: Path) -> Path:
    """A camera-only script: the least a scene needs to render."""
    path = tmp_path / "camara.py"
    path.write_text(
        "import bpy\n"
        'data = bpy.data.cameras.new("camara")\n'
        'obj = bpy.data.objects.new("camara", data)\n'
        "bpy.context.scene.collection.objects.link(obj)\n"
        "bpy.context.scene.camera = obj\n",
        encoding="utf-8",
    )
    return path


def _request(
    tmp_path: Path, verb: str, capability: str = "blender.scene", **inputs
) -> dict[str, object]:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    assets = [str(item) for item in inputs.pop("assets", ())]
    return {
        "protocol": 1,
        "verb": verb,
        "capability": capability,
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(tmp_path),
        "models": {},
        "assets": assets,
    }


def _scene_request(tmp_path: Path, **inputs) -> dict[str, object]:
    given = {
        "script": "camara.py",
        "name": "prueba",
        "width": WIDTH,
        "height": HEIGHT,
        "engine": "eevee",
    }
    given.update(inputs)
    return _request(tmp_path, "run", **given)


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        **os.environ,
        "BLENDER_EXE": str(_stub_blender(tmp_path)),
        "STUB_BPY": str(_stub_bpy(tmp_path)),
        "FACET_MODELS": str(tmp_path / "models" / "direct"),
    }
    env.pop("PYTHONPATH", None)
    env.update(extra)
    return env


def _call(verb: str, request: dict[str, object], tmp_path: Path, env: dict[str, str]):
    input_path = tmp_path / f"{verb}-request.json"
    result_path = tmp_path / f"{verb}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
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
    return done, result_path


def test_the_cycle_drives_the_host_and_the_script_sets_the_scene(tmp_path: Path) -> None:
    """run launches Blender once, the script builds the scene, facet writes it."""
    _script(tmp_path)
    env = _env(tmp_path, STUB_PNG_OUT=str(tmp_path / "out" / "prueba.png"))

    done, result_path = _call("run", _scene_request(tmp_path), tmp_path, env)

    assert done.returncode == 0, done.stdout + done.stderr
    asset = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert asset["file"] == "prueba.png"
    assert asset["kind"] == "image"
    assert asset["properties"]["width"] == WIDTH
    assert asset["properties"]["height"] == HEIGHT
    assert asset["properties"]["engine"] == "eevee"
    assert asset["inputs"] == ["camara.py"]
    assert (tmp_path / "out" / "prueba.png").is_file()


def test_a_run_without_a_camera_fails_before_the_host_writes(
    tmp_path: Path,
) -> None:
    """The script contract is the runner's: no camera is a loud failure."""
    (tmp_path / "vacia.py").write_text("import bpy\n", encoding="utf-8")
    env = _env(tmp_path)

    done, result_path = _call("run", _scene_request(tmp_path, script="vacia.py"), tmp_path, env)

    assert done.returncode != 0
    assert not result_path.exists()


def _failures(tmp_path: Path, mode: str) -> tuple[subprocess.CompletedProcess[str], int]:
    _script(tmp_path)
    counter = tmp_path / "attempts.txt"
    env = _env(
        tmp_path,
        STUB_BLENDER_MODE=mode,
        STUB_ATTEMPTS=str(counter),
    )
    done, _result = _call("run", _scene_request(tmp_path), tmp_path, env)
    attempts = int(counter.read_text()) if counter.exists() else 0
    return done, attempts


def test_a_plain_failure_reaches_the_caller_with_its_tail(tmp_path: Path) -> None:
    """The host's non-zero exit is the runner's error, with its stderr tail."""
    done, attempts = _failures(tmp_path, "fail-plain")

    assert done.returncode != 0
    assert "blender exited 3" in done.stderr
    assert "scene blew up" in done.stderr
    assert attempts == 1


def test_a_wsl_interop_failure_is_retried_exactly_once(tmp_path: Path) -> None:
    """The first vsock accept can fail under WSL; the next launch proceeds."""
    done, attempts = _failures(tmp_path, "fail-interop-once")

    assert done.returncode == 0, done.stdout + done.stderr
    assert attempts == RETRIES


def test_an_enduring_interop_failure_is_not_retried_forever(tmp_path: Path) -> None:
    """A second interop failure is a real failure: two launches, then error."""
    done, attempts = _failures(tmp_path, "fail-interop-always")

    assert done.returncode != 0
    assert attempts == RETRIES
    assert "utilacceptvsock" in done.stderr.lower()


def test_a_missing_host_names_the_variable_facet_resolves(tmp_path: Path) -> None:
    """No binary is a loud error that points at the config key's env."""
    _script(tmp_path)
    env = {**os.environ, "PATH": str(tmp_path / "empty")}
    env.pop("BLENDER_EXE", None)

    done, _result = _call("run", _scene_request(tmp_path), tmp_path, env)

    assert done.returncode != 0
    assert "blender not found" in done.stderr
    assert "BLENDER_EXE" in done.stderr
    assert "blender.path" in done.stderr


def test_a_windows_exe_gets_windows_paths_for_the_host() -> None:
    """The conversion the lab's tools/blender.sh does, per path form."""
    assert runner._host_path("/mnt/c/lab/estudio.glb", True) == "C:\\lab\\estudio.glb"
    assert runner._host_path("/home/lab/estudio.glb", False) == "/home/lab/estudio.glb"
    # A path outside /mnt asks wslpath, exactly as the lab's script does.
    assert runner._drive_path("/mnt/c/x") == "C:\\x"
    assert runner._drive_path("/home/x") is None


def test_a_posix_path_becomes_a_unc_path_under_the_discovered_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blender reads ``/mnt/c`` natively; anything else goes under WSL's UNC root.

    The launcher converts ``--input`` with ``wslpath -w`` before the host
    launches, so the entry learns the root from the argument it was handed.
    """
    monkeypatch.setattr(runner, "_UNC_ROOT", [""])
    runner._remember_root("\\\\wsl.localhost\\Ubuntu\\tmp\\req.json")
    assert runner._UNC_ROOT[0] == "\\\\wsl.localhost\\Ubuntu"
    assert runner._host_path("/tmp/out/estudio.png", True) == (
        "\\\\wsl.localhost\\Ubuntu\\tmp\\out\\estudio.png"
    )
    # A drive path is the Windows build's own and is left alone.
    assert runner._host_path("/mnt/c/lab/estudio.glb", True) == "C:\\lab\\estudio.glb"
    assert runner._host_path("C:/lab/x.png", True) == "C:/lab/x.png"
    assert runner._host_path("\\\\server\\share\\x.png", True) == ("\\\\server\\share\\x.png")
    # Outside Windows nothing is touched, and an unknown root leaves it as it is.
    assert runner._host_path("/tmp/x.png", False) == "/tmp/x.png"
    runner._remember_root("/tmp/req.json")
    assert runner._UNC_ROOT[0] == "\\\\wsl.localhost\\Ubuntu"


def test_a_path_without_a_known_root_is_left_as_it_was(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never invent a UNC root: a missing one is a visible error, not a wrong file."""
    monkeypatch.setattr(runner, "_UNC_ROOT", [""])
    assert runner._host_path("/tmp/x.png", True) == "/tmp/x.png"


def test_doctor_reports_bpy_through_the_host(tmp_path: Path) -> None:
    """doctor runs inside the host and names the one module a script needs."""
    _script(tmp_path)
    request = _request(tmp_path, "doctor", depth="quick")

    done, result_path = _call("doctor", request, tmp_path, _env(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    checks = {check["name"]: check for check in json.loads(result_path.read_text())["checks"]}
    assert set(checks) == {"bpy"}
    assert checks["bpy"]["ok"] is True
    assert "5.2.2 LTS" in checks["bpy"]["detail"]


def test_doctor_answers_for_the_assets_capability_too(tmp_path: Path) -> None:
    """``facet describe`` asks per capability; assets still reports bpy."""
    _script(tmp_path)
    request = _request(tmp_path, "doctor", capability="blender.assets", depth="quick")

    done, result_path = _call("doctor", request, tmp_path, _env(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    checks = json.loads(result_path.read_text())["checks"]
    assert [check["name"] for check in checks] == ["bpy"]


# --- blender.assets: the Poly Haven fetch, against a local HTTP stub.


class _PolyhavenStub:
    """A local Poly Haven: info/files records plus the bytes they point at."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.info: dict[str, dict[str, object]] = {}
        self.files: dict[str, dict[str, object]] = {}
        self.blobs: dict[str, bytes] = {}
        self.agents: list[str] = []
        self.downloads = 0

    def _blob(self, data: bytes) -> str:
        key = f"dl/{len(self.blobs)}"
        self.blobs[key] = data
        return f"{self.base}/{key}"

    def _record(self, data: bytes) -> dict[str, object]:
        return {
            "url": self._blob(data),
            "size": len(data),
            "md5": hashlib.md5(data).hexdigest(),
        }

    def add(self, asset_id: str, kind: str, **info_extra: object) -> None:
        """Register one asset with lab-shaped records for its type.

        Every map is listed under all three resolutions, as the real API
        does; the fetch's default (2k skies and textures, 1k models) then
        finds its level.
        """
        kind_id = {"sky": 0, "texture": 1, "model": 2}[kind]
        self.info[f"info/{asset_id}"] = {"type": kind_id, **info_extra}
        record: dict[str, object] = {}
        self.files[f"files/{asset_id}"] = record
        levels = ("1k", "2k", "4k")
        if kind == "sky":
            hdr = self._record(b"sky-" + asset_id.encode())
            record["hdri"] = {res: {"hdr": hdr} for res in levels}
        elif kind == "texture":
            maps = {
                "col_1": b"diffuse-one",
                "col_2": b"diffuse-two",
                "nor_gl": b"normal-map",
                "Rough": b"roughness",
            }
            for key, data in maps.items():
                jpg = self._record(data + asset_id.encode())
                record[key] = {res: {"jpg": jpg} for res in levels}
        else:
            gltf = self._record(b"gltf-" + asset_id.encode())
            gltf["include"] = {
                "textures/wood.jpg": self._record(b"wood-" + asset_id.encode()),
                "model.bin": self._record(b"bin-" + asset_id.encode()),
            }
            record["gltf"] = {res: {"gltf": gltf} for res in levels}


class _PolyhavenHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        stub = self.server.stub  # type: ignore[attr-defined]
        stub.agents.append(str(self.headers.get("User-Agent")))
        path = self.path.split("?", 1)[0].lstrip("/")
        if path.startswith("dl/"):
            stub.downloads += 1
            self._send(stub.blobs[path], "application/octet-stream")
            return
        body = stub.info.get(path) or stub.files.get(path)
        if body is None:
            self.send_error(404)
            return
        self._send(json.dumps(body).encode(), "application/json")

    def _send(self, data: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture
def polyhaven() -> Iterator[_PolyhavenStub]:
    """A ThreadingHTTPServer posing as api.polyhaven.com for one test."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PolyhavenHandler)
    stub = _PolyhavenStub(f"http://127.0.0.1:{server.server_address[1]}")
    server.stub = stub  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield stub
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)


def _assets_env(tmp_path: Path, stub: _PolyhavenStub) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["POLYHAVEN_API"] = stub.base
    env["FACET_MODELS"] = str(tmp_path / "models" / "direct")
    return env


def _assets_request(tmp_path: Path, name: str, entries: list[dict[str, str]]) -> dict:
    request = _request(tmp_path, "run", capability="blender.assets", name=name)
    request["inputs"]["assets"] = entries
    return request


def _polyhaven_root(tmp_path: Path) -> Path:
    return tmp_path / "models" / "blender" / "polyhaven"


def test_assets_fetches_the_three_types_with_fixed_names(
    tmp_path: Path, polyhaven: _PolyhavenStub
) -> None:
    """One fetch list lands sky.hdr, the texture maps and the glTF set."""
    polyhaven.add("test-sky", "sky")
    polyhaven.add("test-tex", "texture")
    polyhaven.add("test-model", "model")
    entries = [{"id": "test-sky"}, {"id": "test-tex", "res": "2k"}, {"id": "test-model"}]
    request = _assets_request(tmp_path, "escenario", entries)

    done, result_path = _call("run", request, tmp_path, _assets_env(tmp_path, polyhaven))

    assert done.returncode == 0, done.stdout + done.stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    asset = result["assets"][0]
    assert asset["file"] == "escenario.assets.json"
    assert (asset["kind"], asset["mime"]) == ("text", "application/json")
    assert asset["seed"] is None and asset["inputs"] == []
    assert asset["properties"]["assets"] == len(entries)
    root = _polyhaven_root(tmp_path)
    assert (root / "test-sky" / "sky.hdr").is_file()
    for name in ("diff.jpg", "nor_gl.jpg", "rough.jpg"):
        assert (root / "test-tex" / name).is_file(), name
    assert (root / "test-model" / "test-model.gltf").is_file()
    assert (root / "test-model" / "textures" / "wood.jpg").is_file()
    assert (root / "test-model" / "model.bin").is_file()
    receipt = json.loads((tmp_path / "out" / "escenario.assets.json").read_text())
    assert receipt["receipt"] == 1 and receipt["name"] == "escenario"
    by_id = {item["id"]: item for item in receipt["assets"]}
    assert by_id["test-sky"]["type"] == "sky" and by_id["test-sky"]["res"] == "2k"
    assert by_id["test-model"]["res"] == "1k"
    for item in receipt["assets"]:
        for entry in item["files"]:
            assert set(entry) == {"path", "bytes", "md5"}
    # The texture took the first colour variant, and every call identified itself.
    diff = next(e for e in by_id["test-tex"]["files"] if e["path"] == "diff.jpg")
    assert diff["bytes"] == len(b"diffuse-one" + b"test-tex")
    assert polyhaven.agents and set(polyhaven.agents) == {"grafics-lab/1.0"}


def test_assets_skips_files_already_present_with_the_right_size(
    tmp_path: Path, polyhaven: _PolyhavenStub
) -> None:
    """The lab's size skip: a second run downloads nothing."""
    polyhaven.add("test-sky", "sky")
    request = _assets_request(tmp_path, "sky", [{"id": "test-sky"}])
    env = _assets_env(tmp_path, polyhaven)

    first, _ = _call("run", request, tmp_path, env)
    downloads = polyhaven.downloads
    second, _ = _call("run", request, tmp_path, env)

    assert first.returncode == 0 and second.returncode == 0
    assert downloads == 1 and polyhaven.downloads == downloads


def test_assets_md5_mismatch_fails_the_run(tmp_path: Path, polyhaven: _PolyhavenStub) -> None:
    """Corrupt bytes against the record's md5 is a loud fetch failure."""
    polyhaven.add("test-sky", "sky")
    record = polyhaven.files["files/test-sky"]["hdri"]["2k"]["hdr"]
    record["md5"] = "0" * 32
    request = _assets_request(tmp_path, "sky", [{"id": "test-sky"}])

    done, result_path = _call("run", request, tmp_path, _assets_env(tmp_path, polyhaven))

    assert done.returncode != 0
    assert "md5 mismatch" in done.stderr
    assert not result_path.exists()


def test_assets_refuses_a_model_over_four_million_polygons(
    tmp_path: Path, polyhaven: _PolyhavenStub
) -> None:
    """The lab's polygon gate names the id and the count before downloading."""
    polyhaven.add("huge-model", "model", polycount=5_000_000)
    request = _assets_request(tmp_path, "grande", [{"id": "huge-model"}])

    done, _ = _call("run", request, tmp_path, _assets_env(tmp_path, polyhaven))

    assert done.returncode != 0
    assert "huge-model" in done.stderr
    assert "5000000" in done.stderr
    assert polyhaven.downloads == 0


def test_assets_verify_passes_on_the_run_receipt(tmp_path: Path, polyhaven: _PolyhavenStub) -> None:
    """verify re-measures every file the receipt lists, one verdict per asset."""
    polyhaven.add("test-sky", "sky")
    request = _assets_request(tmp_path, "sky", [{"id": "test-sky"}])
    env = _assets_env(tmp_path, polyhaven)
    done, _ = _call("run", request, tmp_path, env)
    assert done.returncode == 0, done.stdout + done.stderr
    receipt = tmp_path / "out" / "sky.assets.json"

    verify = _request(tmp_path, "verify", capability="blender.assets")
    verify["assets"] = [str(receipt)]
    done, result_path = _call("verify", verify, tmp_path, env)

    assert done.returncode == 0, done.stdout + done.stderr
    verdict = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert verdict["file"] == "sky.assets.json"
    assert verdict["passed"] is True
    assert verdict["verifier"] == "polyhaven-receipt"
    assert verdict["metrics"] == {"files": 1, "present": 1}

    (_polyhaven_root(tmp_path) / "test-sky" / "sky.hdr").unlink()
    done, result_path = _call("verify", verify, tmp_path, env)
    verdict = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert done.returncode == 0
    assert verdict["passed"] is False
    assert verdict["metrics"]["present"] == 0


def test_assets_preview_writes_the_generic_preview_beside_the_receipt(
    tmp_path: Path, polyhaven: _PolyhavenStub
) -> None:
    """The preview is <name>.assets.json.preview.json, the core's mandated path."""
    polyhaven.add("test-sky", "sky")
    polyhaven.add("test-model", "model")
    request = _assets_request(tmp_path, "escena", [{"id": "test-sky"}, {"id": "test-model"}])
    env = _assets_env(tmp_path, polyhaven)
    done, _ = _call("run", request, tmp_path, env)
    assert done.returncode == 0, done.stdout + done.stderr
    receipt = tmp_path / "out" / "escena.assets.json"

    preview = _request(tmp_path, "preview", capability="blender.assets")
    preview["assets"] = [str(receipt)]
    done, result_path = _call("preview", preview, tmp_path, env)

    assert done.returncode == 0, done.stdout + done.stderr
    entry = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert entry["file"] == "escena.assets.json"
    assert entry["preview"] == "escena.assets.json.preview.json"
    data = json.loads((receipt.parent / entry["preview"]).read_text(encoding="utf-8"))
    assert set(data) == set(GENERIC_SCHEMA["required"])
    assert data["preview"] == 1 and data["kind"] == "text"
    assert len(data["summary"]) <= GENERIC_SCHEMA["properties"]["summary"]["maxLength"]
    assert all(
        isinstance(value, (str, int, float, bool)) or value is None
        for value in data["fields"].values()
    )
