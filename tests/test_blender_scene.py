"""A scripted still and animation through a stub host, and their checks.

No real Blender runs here. The stub ``bpy`` executes the piece's own
``.py`` script (the real ``examples/scene/build.py`` for the main run),
records what the script built and what the runner overrode, and writes a
two-tone PNG (or a stub MP4) where the render would land. ``FACET_MODELS``
points at a scratch tree, so the Poly Haven root the script sees is a test
path too.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import ntpath
import struct
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import PIL.Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"
RUNNER = PACKAGE / "runner.py"
SCENE_EXAMPLE = PACKAGE / "examples" / "scene"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
SCENE_REFERENCE = PACKAGE / "skill" / "references" / "scene.md"
#: The scripted defaults: a 1920x1080 still in Cycles, 120 frames in Eevee.
WIDTH = 1920
HEIGHT = 1080
FRAMES = 120
FPS = 24
#: The two-tone stub frame: black left, white right.
MEAN = 0.5
SPREAD = 0.5
#: The owned output the override test pins: full HD at 100 %, Cycles, 128.
PERCENT = 100
CYCLES_SAMPLES = 128
EEVEE_SAMPLES = 64
BRIGHT_EXPOSURE = 0.5
SHOT_SEED = 3
#: A short animation and a small still the negative tests measure against.
SHORT_FRAMES = 48
SHORT_FPS = 12
SMALL_WIDTH = 800
SMALL_HEIGHT = 600

STUB_BPY = r'''
"""A stub bpy: the scripted scene's objects, and a trail of the run."""

import json
import os
from pathlib import Path

TRAIL = {"keyframes": {}, "render_calls": []}


class Input:
    def __init__(self, value=None):
        self.default_value = value


class Node:
    def __init__(self, name):
        self.name = name
        self.inputs = {"Base Color": Input(), "Strength": Input()}


class Nodes(dict):
    def new(self, kind):
        return Node(kind)


class NodeTree:
    def __init__(self):
        self.nodes = Nodes({
            "Principled BSDF": Node("Principled BSDF"),
            "Background": Node("Background"),
        })


class Material:
    def __init__(self, name):
        self.name = name
        self.use_nodes = False
        self.node_tree = NodeTree()


class MeshData:
    def __init__(self, name):
        self.name = name
        self.materials = []


class Object:
    def __init__(self, name, kind="MESH", size=(1.0, 1.0, 1.0), data=None):
        self.name = name
        self.type = kind
        self.parent = None
        self.scale = [1.0, 1.0, 1.0]
        self.location = [0.0, 0.0, 0.0]
        self.rotation_mode = "XYZ"
        self.rotation_euler = [0.0, 0.0, 0.0]
        self.data = data if data is not None else MeshData(name) if kind == "MESH" else object()

    def keyframe_insert(self, channel, frame=1):
        TRAIL["keyframes"].setdefault(channel, []).append(frame)


class Camera:
    def __init__(self, name):
        self.name = name
        self.type = "PERSP"
        self.ortho_scale = 6.0
        self.lens = 50.0
        self.clip_start = 0.1


class Light:
    def __init__(self, name, type="SUN"):
        self.name = name
        self.type = type
        self.energy = 0.0
        self.shape = "POINT"
        self.size = 0.0


class Image:
    def __init__(self, pixels, size=(0, 0)):
        self.pixels = pixels
        self.size = size


class DataImages:
    def load(self, filepath):
        import PIL.Image

        with PIL.Image.open(filepath) as handle:
            size = handle.size
            raw = handle.convert("RGB").tobytes()
            flat = []
            for offset in range(0, len(raw), 3):
                flat.extend(
                    (
                        raw[offset] / 255.0,
                        raw[offset + 1] / 255.0,
                        raw[offset + 2] / 255.0,
                        1.0,
                    )
                )
        TRAIL["images_loaded"] = TRAIL.get("images_loaded", 0) + 1
        return Image(flat, size)

    def remove(self, image):
        TRAIL["images_removed"] = TRAIL.get("images_removed", 0) + 1


class Materials:
    def new(self, name):
        return Material(name)


class Cameras:
    def new(self, name):
        return Camera(name)


class Lights:
    def new(self, name, type="SUN"):
        return Light(name, type)


class Objects:
    def new(self, name, data):
        if isinstance(data, Camera):
            return Object(name, kind="CAMERA", data=data)
        if isinstance(data, Light):
            return Object(name, kind="LIGHT", data=data)
        return Object(name)


class DataBlocks:
    def __init__(self):
        self.materials = Materials()
        self.cameras = Cameras()
        self.lights = Lights()
        self.images = DataImages()
        self.objects = Objects()


class SceneObjects:
    def __init__(self, scene):
        self.scene = scene

    def link(self, obj):
        self.scene.objects.append(obj)


class Collection:
    def __init__(self, scene):
        self.objects = SceneObjects(scene)


class ImageSettings:
    def __init__(self):
        self.media_type = "IMAGE"
        self.file_format = "PNG"


class FfmpegSettings:
    def __init__(self):
        self.format = ""
        self.codec = ""
        self.constant_rate_factor = ""


class RenderSettings:
    def __init__(self):
        self.resolution_x = 1920
        self.resolution_y = 1080
        self.resolution_percentage = 100
        self.filepath = ""
        self.engine = ""
        self.fps = 24
        self.use_file_extension = True
        self.image_settings = ImageSettings()
        self.ffmpeg = FfmpegSettings()


class ViewSettings:
    def __init__(self):
        self.exposure = 0.0
        self.look = "None"


class CyclesSettings:
    def __init__(self):
        self.device = "CPU"
        self.samples = 1
        self.use_denoising = False
        self.seed = 0


class EeveeSettings:
    def __init__(self):
        self.taa_render_samples = 64


class Scene:
    def __init__(self):
        self.objects = []
        self.collection = Collection(self)
        self.render = RenderSettings()
        self.view_settings = ViewSettings()
        self.cycles = CyclesSettings()
        self.eevee = EeveeSettings()
        self.camera = None
        self.frame_start = 1
        self.frame_end = 250


class Device:
    def __init__(self, name, kind):
        self.name = name
        self.type = kind
        self.use = False


class CyclesPrefs:
    def __init__(self):
        self.compute_device_type = "NONE"
        self.devices = [Device("CPU", "CPU")]

    def get_devices(self):
        self.devices = [Device("NVIDIA GeForce RTX 4060", "OPTIX"), Device("CPU", "CPU")]


class Addon:
    def __init__(self):
        self.preferences = CyclesPrefs()


class Preferences:
    def __init__(self):
        self.addons = {"cycles": Addon()}


class ViewLayer:
    def update(self):
        return None


class Context:
    def __init__(self):
        self.scene = Scene()
        self.preferences = Preferences()
        self.active_object = None
        self.view_layer = ViewLayer()


class App:
    version_string = "5.2.2 LTS"


class WmOps:
    def read_factory_settings(self, use_empty=False):
        context.scene = Scene()


class MeshOps:
    def primitive_plane_add(self, size=2.0, location=(0.0, 0.0, 0.0)):
        self._add("Plane", (size, size, 0.0), location)

    def primitive_cube_add(self, size=2.0, location=(0.0, 0.0, 0.0)):
        self._add("Cube", (size, size, size), location)

    def primitive_uv_sphere_add(self, radius=1.0, location=(0.0, 0.0, 0.0)):
        self._add("Sphere", (2 * radius, 2 * radius, 2 * radius), location)

    def primitive_cone_add(self, radius1=1.0, depth=2.0, location=(0.0, 0.0, 0.0)):
        self._add("Cone", (2 * radius1, 2 * radius1, depth), location)

    def _add(self, name, size, location):
        obj = Object(name, size=size)
        obj.location = list(location)
        context.scene.objects.append(obj)
        context.active_object = obj


class RenderOps:
    def render(self, animation=False, write_still=False):
        scene = context.scene
        TRAIL["render_calls"].append({"animation": animation, "write_still": write_still})
        TRAIL["render"] = {
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "percentage": scene.render.resolution_percentage,
            "filepath": scene.render.filepath,
            "engine": scene.render.engine,
            "cycles": {
                "device": scene.cycles.device,
                "samples": scene.cycles.samples,
                "denoise": scene.cycles.use_denoising,
                "seed": scene.cycles.seed,
            },
            "eevee_samples": scene.eevee.taa_render_samples,
            "exposure": scene.view_settings.exposure,
            "fps": scene.render.fps,
            "frames": [scene.frame_start, scene.frame_end],
            "media_type": scene.render.image_settings.media_type,
            "file_format": scene.render.image_settings.file_format,
            "ffmpeg": {
                "format": scene.render.ffmpeg.format,
                "codec": scene.render.ffmpeg.codec,
                "crf": scene.render.ffmpeg.constant_rate_factor,
            },
            "use_file_extension": scene.render.use_file_extension,
        }
        TRAIL["objects"] = sorted(obj.name for obj in scene.objects)
        TRAIL["camera"] = None if scene.camera is None else scene.camera.name
        if scene.render.filepath:
            if animation:
                Path(scene.render.filepath).write_bytes(b"stub-mp4")
            else:
                _write_png(scene)
        target = os.environ.get("STUB_TRAIL", "")
        if target:
            Path(target).write_text(json.dumps(TRAIL, default=list))


def _write_png(scene):
    import PIL.Image

    width, height = scene.render.resolution_x, scene.render.resolution_y
    if os.environ.get("STUB_FLAT", ""):
        image = PIL.Image.new("RGB", (width, height), (20, 40, 60))
    else:
        image = PIL.Image.new("RGB", (width, height), (0, 0, 0))
        white = PIL.Image.new("RGB", (width - width // 2, height), (255, 255, 255))
        image.paste(white, (width // 2, 0))
    image.save(scene.render.filepath)


class Ops:
    def __init__(self):
        self.wm = WmOps()
        self.mesh = MeshOps()
        self.render = RenderOps()


context = Context()
app = App()
data = DataBlocks()
ops = Ops()
'''


def _load_runner():
    sys.modules.pop("blender_runner", None)
    spec = importlib.util.spec_from_file_location("blender_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runner():
    return _load_runner()


def _stub_bpy() -> None:
    """Load the stub once per test: ``bpy`` is imported by name in the runner."""
    sys.modules.pop("bpy", None)
    module = type(sys)("bpy")
    exec(STUB_BPY, module.__dict__)
    sys.modules["bpy"] = module


def _request(
    tmp_path: Path, capability: str, verb: str, assets: list[str] | None = None, **inputs
) -> dict:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return {
        "protocol": 1,
        "verb": verb,
        "capability": capability,
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(tmp_path),
        "models": {},
        "assets": [str(item) for item in assets or ()],
    }


def _call(runner, tmp_path: Path, verb: str, request: dict, monkeypatch) -> dict:
    monkeypatch.setenv("FACET_MODELS", str(tmp_path / "models" / "direct"))
    monkeypatch.setenv("STUB_TRAIL", str(tmp_path / "trail.json"))
    _stub_bpy()
    input_path = tmp_path / f"{verb}-request.json"
    result_path = tmp_path / f"{verb}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    try:
        runner.main([verb, "--input", str(input_path), "--result", str(result_path)])
    finally:
        sys.modules.pop("bpy", None)
    return json.loads(result_path.read_text(encoding="utf-8"))


def _trail(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "trail.json").read_text(encoding="utf-8"))


def _script(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return name


CAMERA_SCRIPT = """import bpy
data = bpy.data.cameras.new("camara")
camera = bpy.data.objects.new("camara", data)
bpy.context.scene.collection.objects.link(camera)
bpy.context.scene.camera = camera
"""

OVERRIDE_SCRIPT = (
    """import bpy
bpy.context.scene.render.resolution_x = 320
bpy.context.scene.render.resolution_y = 240
bpy.context.scene.render.engine = "BLENDER_EEVEE"
bpy.context.scene.eevee.taa_render_samples = 7
"""
    + CAMERA_SCRIPT
)


def test_the_example_script_builds_the_scene(tmp_path: Path, runner, monkeypatch) -> None:
    """build.py's plane, primitives, lights and camera all reach the scene."""
    request = _request(tmp_path, "blender.scene", "run", script="build.py", name="script-still")
    request["piece_dir"] = str(SCENE_EXAMPLE)
    result = _call(runner, tmp_path, "run", request, monkeypatch)

    trail = _trail(tmp_path)
    for name in ("Plane", "Cube", "Sphere", "Cone", "area", "sol", "camara"):
        assert name in trail["objects"], name
    assert trail["camera"] == "camara"
    assert trail["render_calls"] == [{"animation": False, "write_still": True}]
    keyframes = json.loads((tmp_path / "trail.json").read_text())["keyframes"]
    assert sorted(keyframes) == ["location", "rotation_euler"]
    assert len(keyframes["location"]) == FRAMES
    asset = result["assets"][0]
    assert asset["file"] == "script-still.png"
    assert (asset["kind"], asset["mime"]) == ("image", "image/png")
    assert result["tool"]["name"] == "blender"
    with PIL.Image.open(tmp_path / "out" / "script-still.png") as image:
        assert image.size == (WIDTH, HEIGHT)


def test_the_script_sees_the_facet_globals_and_its_own_directory(
    tmp_path: Path, runner, monkeypatch
) -> None:
    """FACET_ASSETS, FACET_PIECE_DIR and the cwd are the contract's values."""
    expected_root = tmp_path / "models" / "blender" / "polyhaven"
    body = (
        "import os\n"
        f"assert FACET_ASSETS == {str(expected_root)!r}, FACET_ASSETS\n"
        f"assert FACET_PIECE_DIR == {str(tmp_path)!r}, FACET_PIECE_DIR\n"
        f"assert os.getcwd() == {str(tmp_path)!r}, os.getcwd()\n" + CAMERA_SCRIPT
    )
    request = _request(
        tmp_path, "blender.scene", "run", script=_script(tmp_path, "probe.py", body), name="probe"
    )
    result = _call(runner, tmp_path, "run", request, monkeypatch)

    assert result["assets"][0]["inputs"] == ["probe.py"]
    assert (tmp_path / "out" / "probe.png").is_file()


def test_the_runner_overrides_win_over_the_script(tmp_path: Path, runner, monkeypatch) -> None:
    """The script's 320x240 Eevee never reaches the frame facet renders."""
    request = _request(
        tmp_path,
        "blender.scene",
        "run",
        script=_script(tmp_path, "small.py", OVERRIDE_SCRIPT),
        name="big",
        width=1920,
        height=1080,
        engine="cycles",
        samples=CYCLES_SAMPLES,
        exposure=BRIGHT_EXPOSURE,
        seed=SHOT_SEED,
    )
    result = _call(runner, tmp_path, "run", request, monkeypatch)

    render = _trail(tmp_path)["render"]
    assert render["resolution"] == [WIDTH, HEIGHT]
    assert render["percentage"] == PERCENT
    assert render["engine"] == "CYCLES"
    assert render["cycles"] == {
        "device": "GPU",
        "samples": CYCLES_SAMPLES,
        "denoise": True,
        "seed": SHOT_SEED,
    }
    assert render["exposure"] == BRIGHT_EXPOSURE
    assert render["filepath"] == str(tmp_path / "out" / "big.png")
    assert result["assets"][0]["properties"]["seed"] == SHOT_SEED


def test_a_run_without_a_camera_fails(tmp_path: Path, runner, monkeypatch) -> None:
    """A script that leaves scene.camera unset fails loudly."""
    request = _request(
        tmp_path,
        "blender.scene",
        "run",
        script=_script(tmp_path, "nocam.py", "import bpy\n"),
        name="nocam",
    )
    with pytest.raises(RuntimeError, match="no camera"):
        _call(runner, tmp_path, "run", request, monkeypatch)


def test_a_script_exception_fails_with_its_type(tmp_path: Path, runner, monkeypatch) -> None:
    """A ZeroDivisionError names the script and the exception type."""
    request = _request(
        tmp_path,
        "blender.scene",
        "run",
        script=_script(tmp_path, "bad.py", "def f():\n    return 1 / 0\nf()\n"),
        name="bad",
    )
    with pytest.raises(RuntimeError) as excinfo:
        _call(runner, tmp_path, "run", request, monkeypatch)

    assert "script bad.py failed: ZeroDivisionError" in str(excinfo.value)


def test_a_flat_still_fails_as_a_uniform_image(tmp_path: Path, runner, monkeypatch) -> None:
    """A solid frame fails the run, naming the framing and the lights."""
    monkeypatch.setenv("STUB_FLAT", "1")
    request = _request(
        tmp_path,
        "blender.scene",
        "run",
        script=_script(tmp_path, "flat.py", CAMERA_SCRIPT),
        name="flat",
    )
    with pytest.raises(RuntimeError) as excinfo:
        _call(runner, tmp_path, "run", request, monkeypatch)

    assert "uniform image" in str(excinfo.value)
    assert "check the camera's framing and the lights" in str(excinfo.value)


def test_a_graded_still_passes_and_records_its_spread(tmp_path: Path, runner, monkeypatch) -> None:
    """The two-tone frame passes the guard with its mean and deviation."""
    request = _request(
        tmp_path,
        "blender.scene",
        "run",
        script=_script(tmp_path, "graded.py", CAMERA_SCRIPT),
        name="graded",
    )
    result = _call(runner, tmp_path, "run", request, monkeypatch)

    properties = result["assets"][0]["properties"]
    assert properties["mean"] == pytest.approx(MEAN)
    assert properties["stddev"] == pytest.approx(SPREAD)


def test_the_animation_renders_eevee_with_the_ffmpeg_block(
    tmp_path: Path, runner, monkeypatch
) -> None:
    """An animation render is Eevee, the frame range, and Blender's MP4."""
    request = _request(
        tmp_path,
        "blender.animation",
        "run",
        script=_script(tmp_path, "move.py", CAMERA_SCRIPT),
        name="movi",
        frames=SHORT_FRAMES,
        fps=SHORT_FPS,
    )
    result = _call(runner, tmp_path, "run", request, monkeypatch)

    trail = _trail(tmp_path)
    assert trail["render_calls"] == [{"animation": True, "write_still": False}]
    render = trail["render"]
    assert render["engine"] == "BLENDER_EEVEE"
    assert render["eevee_samples"] == EEVEE_SAMPLES
    assert render["frames"] == [1, SHORT_FRAMES]
    assert render["fps"] == SHORT_FPS
    assert (render["media_type"], render["file_format"]) == ("VIDEO", "FFMPEG")
    assert render["ffmpeg"] == {"format": "MPEG4", "codec": "H264", "crf": "HIGH"}
    assert render["use_file_extension"] is False
    assert render["filepath"] == str(tmp_path / "out" / "movi.mp4")
    assert (tmp_path / "out" / "movi.mp4").is_file()
    asset = result["assets"][0]
    assert asset["file"] == "movi.mp4"
    assert (asset["kind"], asset["mime"]) == ("video", "video/mp4")
    assert asset["seed"] == 0


def test_the_records_carry_the_recipe_and_the_script(tmp_path: Path, runner, monkeypatch) -> None:
    """Properties hold the owned output and the script's sha256, not its text."""
    script_path = tmp_path / "record.py"
    script_path.write_text(CAMERA_SCRIPT, encoding="utf-8")
    request = _request(tmp_path, "blender.scene", "run", script="record.py", name="record")
    result = _call(runner, tmp_path, "run", request, monkeypatch)

    digest = hashlib.sha256(script_path.read_bytes()).hexdigest()
    asset = result["assets"][0]
    assert asset["properties"] == {
        "width": WIDTH,
        "height": HEIGHT,
        "engine": "cycles",
        "samples": 128,
        "exposure": 0.0,
        "seed": 0,
        "script_sha256": digest,
        "mean": pytest.approx(MEAN),
        "stddev": pytest.approx(SPREAD),
    }
    assert asset["params"] == {"script": "record.py", "name": "record"}
    assert asset["inputs"] == ["record.py"]

    clip_request = _request(
        tmp_path,
        "blender.animation",
        "run",
        script="record.py",
        name="record-clip",
        frames=SHORT_FRAMES,
        fps=SHORT_FPS,
    )
    clip = _call(runner, tmp_path, "run", clip_request, monkeypatch)
    assert clip["assets"][0]["properties"] == {
        "width": WIDTH,
        "height": HEIGHT,
        "engine": "eevee",
        "samples": 64,
        "exposure": 0.0,
        "seed": 0,
        "script_sha256": digest,
        "frames": 48,
        "fps": 12,
    }
    assert clip["assets"][0]["inputs"] == ["record.py"]


def _box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body) + 8) + kind + body


def _mp4(width: int, height: int, frames: int, fps: int, timescale: int = 24_000) -> bytes:
    """A minimal ISO BMFF file carrying just what the probe reads."""
    duration = frames * timescale // fps
    body = b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, timescale, duration)
    mvhd = _box(b"mvhd", body)
    entry = b"\x00" * 6 + struct.pack(">H", 1) + b"\x00" * 16 + struct.pack(">HH", width, height)
    avc1 = _box(b"avc1", entry)
    stsd = _box(b"stsd", b"\x00\x00\x00\x00" + struct.pack(">I", 1) + avc1)
    stts = _box(
        b"stts",
        b"\x00\x00\x00\x00" + struct.pack(">I", 1) + struct.pack(">II", frames, timescale // fps),
    )
    stbl = _box(b"stbl", stsd + stts)
    return _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41") + _box(
        b"moov", mvhd + _box(b"trak", _box(b"mdia", _box(b"minf", stbl)))
    )


def _png(tmp_path: Path, name: str, width: int, height: int) -> str:
    path = tmp_path / "out" / name
    path.parent.mkdir(exist_ok=True)
    PIL.Image.new("RGB", (width, height), (10, 20, 30)).save(path)
    return str(path)


def _scene_inputs(**overrides) -> dict:
    inputs = {"script": "build.py", "name": "still", "width": WIDTH, "height": HEIGHT}
    inputs.update(overrides)
    return inputs


def test_verify_passes_a_png_at_the_piece_size(tmp_path: Path, runner, monkeypatch) -> None:
    """The PNG's size against the piece's own width and height passes."""
    asset = _png(tmp_path, "still.png", WIDTH, HEIGHT)
    request = _request(tmp_path, "blender.scene", "verify", assets=[asset], **_scene_inputs())

    verdict = _call(runner, tmp_path, "verify", request, monkeypatch)["assets"][0]

    assert verdict["passed"] is True
    assert verdict["verifier"] == "png"
    assert verdict["metrics"] == {"width": WIDTH, "height": HEIGHT}
    assert verdict["thresholds"] == {"width": WIDTH, "height": HEIGHT}


def test_verify_fails_a_png_off_the_piece_size(tmp_path: Path, runner, monkeypatch) -> None:
    """An 800x600 PNG against a 1920x1080 piece fails on the size."""
    asset = _png(tmp_path, "small.png", SMALL_WIDTH, SMALL_HEIGHT)
    request = _request(tmp_path, "blender.scene", "verify", assets=[asset], **_scene_inputs())

    verdict = _call(runner, tmp_path, "verify", request, monkeypatch)["assets"][0]

    assert verdict["passed"] is False
    assert verdict["metrics"] == {"width": SMALL_WIDTH, "height": SMALL_HEIGHT}
    assert verdict["thresholds"] == {"width": WIDTH, "height": HEIGHT}


def _clip_inputs(**overrides) -> dict:
    inputs = {
        "script": "build.py",
        "name": "clip",
        "width": WIDTH,
        "height": HEIGHT,
        "frames": FRAMES,
        "fps": FPS,
    }
    inputs.update(overrides)
    return inputs


def test_verify_passes_a_clip_matching_the_piece(tmp_path: Path, runner, monkeypatch) -> None:
    """The probe's width, height, frames and fps meet the piece's own."""
    path = tmp_path / "out" / "clip.mp4"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(_mp4(WIDTH, HEIGHT, FRAMES, FPS))
    request = _request(
        tmp_path, "blender.animation", "verify", assets=[str(path)], **_clip_inputs()
    )

    verdict = _call(runner, tmp_path, "verify", request, monkeypatch)["assets"][0]

    assert verdict["passed"] is True
    assert verdict["verifier"] == "mp4"
    assert verdict["metrics"] == {"width": WIDTH, "height": HEIGHT, "frames": FRAMES, "fps": FPS}


def test_verify_fails_a_clip_short_of_the_frame_count(tmp_path: Path, runner, monkeypatch) -> None:
    """A 48-frame clip against a 120-frame piece fails on the count."""
    path = tmp_path / "out" / "short.mp4"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(_mp4(WIDTH, HEIGHT, SHORT_FRAMES, FPS))
    request = _request(
        tmp_path, "blender.animation", "verify", assets=[str(path)], **_clip_inputs()
    )

    verdict = _call(runner, tmp_path, "verify", request, monkeypatch)["assets"][0]

    assert verdict["passed"] is False
    assert verdict["metrics"]["frames"] == SHORT_FRAMES
    assert verdict["thresholds"]["frames"] == FRAMES


def test_preview_names_the_asset_its_engine_and_its_script(
    tmp_path: Path, runner, monkeypatch
) -> None:
    """The image preview carries the summary the viewer shows."""
    asset = _png(tmp_path, "still.png", WIDTH, HEIGHT)
    request = _request(tmp_path, "blender.scene", "preview", assets=[asset], **_scene_inputs())

    entry = _call(runner, tmp_path, "preview", request, monkeypatch)["assets"][0]

    assert entry["file"] == "still.png"
    preview = json.loads((tmp_path / "out" / "still.png.preview.json").read_text())
    assert preview["kind"] == "image"
    assert preview["name"] == "still"
    for token in ("still", "1920×1080", "cycles", "build.py"):
        assert token in preview["summary"], token
    assert preview["width"] == WIDTH and preview["height"] == HEIGHT
    assert "scripted scene" in preview["prompt"]


def test_preview_reports_the_clip_measurements(tmp_path: Path, runner, monkeypatch) -> None:
    """The video preview carries the probe's frames and rate."""
    path = tmp_path / "out" / "clip.mp4"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(_mp4(WIDTH, HEIGHT, FRAMES, FPS))
    request = _request(
        tmp_path, "blender.animation", "preview", assets=[str(path)], **_clip_inputs()
    )

    entry = _call(runner, tmp_path, "preview", request, monkeypatch)["assets"][0]

    assert entry["file"] == "clip.mp4"
    preview = json.loads((tmp_path / "out" / "clip.mp4.preview.json").read_text())
    assert preview["kind"] == "video"
    assert (preview["length"], preview["fps"]) == (FRAMES, FPS)
    for token in ("clip", "1920×1080", "eevee", "build.py"):
        assert token in preview["summary"], token


def test_the_plan_defaults_follow_the_engine(
    runner,
) -> None:
    """A still defaults to Cycles at 128, an animation to Eevee at 64."""
    scene_script = runner.scene_script
    still = scene_script.plan("image", {"name": "a", "script": "a.py"})
    clip = scene_script.plan("video", {"name": "a", "script": "a.py"})
    assert (still.engine, still.samples) == ("cycles", CYCLES_SAMPLES)
    assert (clip.engine, clip.samples) == ("eevee", 64)
    assert (still.frames, still.fps) == (FRAMES, FPS)
    explicit = scene_script.plan("image", {"name": "a", "script": "a.py", "engine": "eevee"})
    assert (explicit.engine, explicit.samples) == ("eevee", 64)


def test_the_verbs_cover_run_verify_preview_and_doctor(runner) -> None:
    """Both scripted capabilities answer the four verbs."""
    for capability in ("blender.scene", "blender.animation"):
        assert set(runner._verbs(capability)) == {"run", "verify", "preview", "doctor"}
    assert runner.scene_script.CAPABILITIES == {
        "blender.scene": "image",
        "blender.animation": "video",
    }


def test_doctor_reports_bpy(tmp_path: Path, runner, monkeypatch) -> None:
    """Doctor names the running Blender's bpy, like the other capabilities."""
    request = _request(tmp_path, "blender.scene", "doctor")
    result = _call(runner, tmp_path, "doctor", request, monkeypatch)

    assert result["checks"] == [
        {"name": "bpy", "ok": True, "detail": "bpy 5.2.2 LTS imports", "fix": ""}
    ]
    failed = runner.scene_script._doctor(SimpleNamespace(), {})
    assert failed["checks"][0]["ok"] is False


def _shared_inputs(capability: str) -> dict:
    return MANIFEST["capabilities"][capability]["inputs"]


def test_the_manifest_declares_both_scripted_capabilities() -> None:
    """Scene is the image kind, animation the video kind, with the viewers."""
    scene = MANIFEST["capabilities"]["scene"]
    animation = MANIFEST["capabilities"]["animation"]
    assert (scene["kind"], scene["preview"]) == ("image", {"viewer": "image"})
    assert (animation["kind"], animation["preview"]) == ("video", {"viewer": "video"})


def test_the_scripted_inputs_carry_the_spec_ranges() -> None:
    """Every shared input has its type, default and range from the spec."""
    for capability in ("scene", "animation"):
        inputs = _shared_inputs(capability)
        script = inputs["script"]
        assert (script["type"], script["required"]) == ("path", True)
        assert "scene.camera" in script["description"]
        assert inputs["name"]["type"] == "string"
        assert inputs["name"]["required"] is True
        assert inputs["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
        for key, default in (("width", 1920), ("height", 1080)):
            field = inputs[key]
            assert (field["type"], field["default"]) == ("integer", default)
            assert (field["min"], field["max"]) == (64, 4096)
        assert inputs["engine"]["values"] == ["cycles", "eevee"]
        samples = inputs["samples"]
        assert (samples["type"], samples["min"], samples["max"]) == ("integer", 1, 4096)
        exposure = inputs["exposure"]
        assert (exposure["type"], exposure["default"]) == ("number", 0.0)
        assert (exposure["min"], exposure["max"]) == (-5, 5)
        assert (inputs["seed"]["type"], inputs["seed"]["default"]) == ("integer", 0)
    assert _shared_inputs("scene")["engine"]["default"] == "cycles"
    assert _shared_inputs("animation")["engine"]["default"] == "eevee"
    assert _shared_inputs("scene")["samples"]["default"] == CYCLES_SAMPLES
    assert _shared_inputs("animation")["samples"]["default"] == EEVEE_SAMPLES


def test_the_animation_inputs_carry_frames_and_rate() -> None:
    """Frames and fps are animation-only, with the spec's ranges."""
    assert "frames" not in _shared_inputs("scene")
    assert "fps" not in _shared_inputs("scene")
    animation = _shared_inputs("animation")
    assert (animation["frames"]["type"], animation["frames"]["default"]) == ("integer", 120)
    assert (animation["frames"]["min"], animation["frames"]["max"]) == (1, 1440)
    assert (animation["fps"]["type"], animation["fps"]["default"]) == ("integer", 24)
    assert (animation["fps"]["min"], animation["fps"]["max"]) == (1, 60)


def test_the_example_pieces_validate() -> None:
    """Both example pieces parse, use declared inputs, and ship the script."""
    for piece, capability, name in (
        ("scene.toml", "scene", "study-script"),
        ("animation.toml", "animation", "study-animated"),
    ):
        data = tomllib.loads((SCENE_EXAMPLE / piece).read_text(encoding="utf-8"))
        declared = set(MANIFEST["capabilities"][capability]["inputs"])
        assert set(data["inputs"]) <= declared
        assert {"script", "name"} <= set(data["inputs"])
        assert data["inputs"]["name"] == name
        assert (SCENE_EXAMPLE / data["inputs"]["script"]).is_file()


def test_the_skill_teaches_both_scripted_capabilities() -> None:
    """The skill names both ids, and the scene reference carries the contract."""
    body = SKILL.split("---", 2)[2]
    assert "blender.scene" in body
    assert "blender.animation" in body
    assert "references/scene.md" in body
    assert SCENE_REFERENCE.is_file()
    reference = SCENE_REFERENCE.read_text(encoding="utf-8")
    for token in (
        "FACET_ASSETS",
        "FACET_PIECE_DIR",
        "scene.camera",
        "uniform",
        "unsandboxed",
        "blender.assets",
    ):
        assert token in reference, token


def test_a_wsl_absolute_script_is_not_joined_to_the_piece_dir_inside_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene_script = _load_runner().scene_script
    monkeypatch.setattr(scene_script.os, "path", ntpath)
    absolute = "/home/lab/pieces/scene/build.py"
    assert scene_script._resolve(absolute, "/home/lab/pieces/scene") == absolute
    assert scene_script._resolve("C:\\lab\\build.py", "/home/lab") == "C:\\lab\\build.py"
    assert scene_script._resolve("build.py", "/home/lab/scene") == "/home/lab/scene/build.py"
