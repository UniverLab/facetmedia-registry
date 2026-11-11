"""The Eevee camera tour through a stub host, and the MP4 probe that checks it.

No real Blender and no network. A stub ``bpy`` answers the same calls the tour
makes — import the glTF, dress the scene, keyframe the camera, render the
animation — and records a trail: which engine and Eevee flags reached the
scene, how many keyframes each channel got and on which frames, and that the
render was an animation rather than a still.

The probe is exercised on an MP4 built with ``struct``: known width, height
and frame count, so reading them back proves the ISO BMFF reader. An
unparsable file must come back as a failed verdict with the parse error as its
metric, never as an exception.
"""

from __future__ import annotations

import importlib.util
import json
import math
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"
RUNNER = PACKAGE / "runner.py"
VIDEO_SCHEMA = json.loads(
    (ROOT / "schemas" / "preview" / "video.schema.json").read_text(encoding="utf-8")
)
WIDTH = 1280
HEIGHT = 720
FRAMES = 240
FPS = 24
TAA_SAMPLES = 32
EXPOSURE = -0.4
LOOK = "AgX - Medium High Contrast"
SUMMARY_MAX = 160
#: A short tour, so the interpolation is checked on fewer frames.
SHORT_SECONDS = 4
SHORT_FPS = 12
SHORT_FRAMES = SHORT_SECONDS * SHORT_FPS
#: A clip with fewer frames than its entry expects.
HALF_FRAMES = 120
#: The seed a piece may ask for, which only labels the record.
SEED = 7
#: A second MP4's measurements, so the probe is not pinned to one file shape.
SMALL_WIDTH = 640
SMALL_HEIGHT = 480
#: The lens a piece may ask for, in millimetres.
WIDE_FOCAL = 50.0
#: The lab's study pieces: names are the material prefixes.
PIECES = [
    ("muros", (6000.0, 4500.0, 2600.0)),
    ("piso", (6300.0, 4800.0, 120.0)),
    ("vidrio-1", (1200.0, 20.0, 1200.0)),
    ("cama", (1400.0, 2000.0, 450.0)),
    ("mesa", (1000.0, 1000.0, 750.0)),
]

STUB_BPY = r'''
"""A stub bpy: the tour's scene, and a trail of what it built."""

import json
import math
import os
from pathlib import Path

TRAIL = {"keyframes": {}, "render_calls": []}


class Input:
    def __init__(self, value=None):
        self.default_value = value


class Node:
    def __init__(self, name):
        self.name = name
        self.inputs = {key: Input() for key in (
            "Base Color", "Metallic", "Roughness", "Transmission Weight", "IOR",
            "Color", "Strength")}
        self.outputs = {"Color": object()}
        self.sun_elevation = 0.0
        self.sun_rotation = 0.0


class Nodes(dict):
    def new(self, kind):
        return Node(kind)


class Links:
    def new(self, source, target):
        return None


class NodeTree:
    def __init__(self):
        self.nodes = Nodes({
            "Principled BSDF": Node("Principled BSDF"),
            "Background": Node("Background"),
        })
        self.links = Links()


class Material:
    def __init__(self, name):
        self.name = name
        self.use_nodes = False
        self.node_tree = NodeTree()


class MeshData:
    def __init__(self, name):
        self.name = name
        self.materials = []
        self.baked = False


class Object:
    def __init__(self, name, kind="MESH", size=(1000.0, 1000.0, 1000.0), data=None):
        self.name = name
        self.type = kind
        self.parent = None
        self.scale = [1.0, 1.0, 1.0]
        self.location = [0.0, 0.0, 0.0]
        self.rotation_mode = "XYZ"
        self.rotation_euler = [0.0, 0.0, 0.0]
        self.selected = False
        self.data = data if data is not None else MeshData(name) if kind == "MESH" else object()
        half = [side / 2 for side in size]
        self.bound_box = [
            [x, y, z]
            for x in (-half[0], half[0])
            for y in (-half[1], half[1])
            for z in (-half[2], half[2])
        ]

    def select_set(self, value):
        self.selected = value

    @property
    def matrix_world(self):
        scale = self.scale
        return [
            [scale[0], 0.0, 0.0, self.location[0]],
            [0.0, scale[1], 0.0, self.location[1]],
            [0.0, 0.0, scale[2], self.location[2]],
        ]

    def keyframe_insert(self, channel, frame=1):
        TRAIL["keyframes"].setdefault(channel, []).append(frame)
        TRAIL.setdefault("camera_poses", {}).setdefault(frame, {})[channel] = list(
            self.location if channel == "location" else self.rotation_euler
        )


class Camera:
    def __init__(self, name):
        self.name = name
        self.type = "PERSP"
        self.lens = 50.0
        self.clip_end = 100.0


class Light:
    def __init__(self, name, kind="SUN"):
        self.name = name
        self.type = kind
        self.energy = 0.0
        self.angle = 0.0


class World:
    def __init__(self, name):
        self.name = name
        self.use_nodes = False
        self.node_tree = NodeTree()


class Materials:
    def new(self, name):
        TRAIL.setdefault("events", []).append(f"material:{name}")
        return Material(name)


class Cameras:
    def new(self, name):
        return Camera(name)


class Lights:
    def new(self, name, kind="SUN"):
        return Light(name, kind)


class Worlds:
    def new(self, name):
        return World(name)


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
        self.worlds = Worlds()
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


class EeveeSettings:
    def __init__(self):
        self.taa_render_samples = 64
        self.use_raytracing = False
        self.ray_tracing_method = "PROBE"
        self.use_fast_gi = False
        self.use_shadows = False


class Scene:
    def __init__(self):
        self.objects = []
        self.collection = Collection(self)
        self.render = RenderSettings()
        self.view_settings = ViewSettings()
        self.eevee = EeveeSettings()
        self.camera = None
        self.world = None
        self.frame_start = 1
        self.frame_end = 250


class LayerObjects:
    def __init__(self):
        self.active = None


class ViewLayer:
    def __init__(self):
        self.objects = LayerObjects()

    def update(self):
        return None


class Context:
    def __init__(self):
        self.scene = Scene()
        self.active_object = None
        self.view_layer = ViewLayer()


class App:
    version_string = "5.2.2 LTS"


class WmOps:
    def read_factory_settings(self, use_empty=False):
        context.scene = Scene()


class ImportOps:
    def gltf(self, filepath):
        TRAIL["import_filepath"] = filepath
        source = os.environ.get("STUB_SCENE", "")
        pieces = json.loads(Path(source).read_text())["pieces"] if source else []
        root = Object("estudio", kind="EMPTY")
        root.rotation_euler = [-math.pi / 2, 0.0, 0.0]
        context.scene.objects.append(root)
        for piece in pieces:
            obj = Object(
                piece["name"], size=tuple(piece.get("size", (1000.0, 1000.0, 1000.0)))
            )
            obj.parent = root
            context.scene.objects.append(obj)


class MeshOps:
    def primitive_plane_add(self, size=2.0, location=(0.0, 0.0, 0.0)):
        obj = Object("Plane", size=(size, size, 0.0))
        obj.location = list(location)
        context.scene.objects.append(obj)
        context.active_object = obj


class RenderOps:
    def render(self, animation=False, write_still=False):
        scene = context.scene
        TRAIL["render_calls"].append({"animation": animation, "write_still": write_still})
        TRAIL["render"] = {
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "filepath": scene.render.filepath,
            "engine": scene.render.engine,
            "fps": scene.render.fps,
            "frames": [scene.frame_start, scene.frame_end],
            "exposure": scene.view_settings.exposure,
            "look": scene.view_settings.look,
            "eevee": {
                "taa_render_samples": scene.eevee.taa_render_samples,
                "use_raytracing": scene.eevee.use_raytracing,
                "ray_tracing_method": scene.eevee.ray_tracing_method,
                "use_fast_gi": scene.eevee.use_fast_gi,
                "use_shadows": scene.eevee.use_shadows,
            },
            "media_type": scene.render.image_settings.media_type,
            "file_format": scene.render.image_settings.file_format,
            "ffmpeg": {
                "format": scene.render.ffmpeg.format,
                "codec": scene.render.ffmpeg.codec,
                "crf": scene.render.ffmpeg.constant_rate_factor,
            },
            "use_file_extension": scene.render.use_file_extension,
        }
        TRAIL["camera"] = None if scene.camera is None else {
            "type": scene.camera.data.type,
            "lens": scene.camera.data.lens,
            "clip_end": scene.camera.data.clip_end,
        }
        TRAIL["materials"] = {
            obj.name: obj.data.materials[0].name
            for obj in scene.objects
            if obj.type == "MESH" and obj.data.materials
        }
        TRAIL["parents"] = {
            obj.name: None if obj.parent is None else obj.parent.name
            for obj in scene.objects
            if obj.type == "MESH"
        }
        TRAIL["baked"] = sorted(
            obj.name
            for obj in scene.objects
            if obj.type == "MESH" and getattr(obj.data, "baked", False)
        )
        TRAIL["sky_strength"] = (
            None if scene.world is None
            else scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value
        )
        if scene.render.filepath:
            Path(scene.render.filepath).write_bytes(b"stub-mp4")
        target = os.environ.get("STUB_TRAIL", "")
        if target:
            Path(target).write_text(json.dumps(TRAIL, default=list))


class ObjectOps:
    def parent_clear(self, **kwargs):
        assert kwargs == {"type": "CLEAR_KEEP_TRANSFORM"}
        obj = context.view_layer.objects.active
        TRAIL.setdefault("events", []).append(f"parent_clear:{obj.name}")
        obj.parent = None

    def transform_apply(self, location=False, rotation=True, scale=True):
        assert location is False and rotation is True and scale is True
        obj = context.view_layer.objects.active
        TRAIL.setdefault("events", []).append(f"bake:{obj.name}")
        obj.scale = [1.0, 1.0, 1.0]
        obj.rotation_euler = [0.0, 0.0, 0.0]
        obj.data.baked = True


class Ops:
    def __init__(self):
        self.wm = WmOps()
        self.import_scene = ImportOps()
        self.mesh = MeshOps()
        self.object = ObjectOps()
        self.render = RenderOps()


context = Context()
app = App()
data = DataBlocks()
ops = Ops()
'''


def _stub_bpy() -> object:
    """Load the stub once per test: ``bpy`` is imported by name inside the runner."""
    sys.modules.pop("bpy", None)
    module = type(sys)("bpy")
    exec(STUB_BPY, module.__dict__)
    sys.modules["bpy"] = module
    return module


def _runner():
    sys.modules.pop("blender_runner", None)
    spec = importlib.util.spec_from_file_location("blender_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runner():
    return _runner()


def _scene(tmp_path: Path) -> Path:
    path = tmp_path / "scene.json"
    entries = [{"name": name, "size": list(size)} for name, size in PIECES]
    path.write_text(json.dumps({"pieces": entries}), encoding="utf-8")
    return path


def _model(tmp_path: Path) -> Path:
    path = tmp_path / "estudio.glb"
    path.write_bytes(b"glTF-stub")
    return path


def _request(tmp_path: Path, verb: str, assets: list[str] | None = None, **inputs) -> dict:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "blender.tour",
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(tmp_path),
        "models": {},
        "assets": [str(item) for item in assets or ()],
    }


def _call(runner, tmp_path: Path, verb: str, request: dict, monkeypatch) -> dict:
    monkeypatch.setenv("STUB_SCENE", str(_scene(tmp_path)))
    monkeypatch.setenv("STUB_TRAIL", str(tmp_path / "trail.json"))
    _stub_bpy()
    input_path = tmp_path / f"{verb}-request.json"
    result_path = tmp_path / f"{verb}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    runner.main([verb, "--input", str(input_path), "--result", str(result_path)])
    sys.modules.pop("bpy", None)
    return json.loads(result_path.read_text(encoding="utf-8"))


def _trail(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "trail.json").read_text(encoding="utf-8"))


def test_the_tour_renders_in_eevee_with_its_recipe(tmp_path: Path, runner, monkeypatch) -> None:
    """Eevee's flags, the AgX exposure and the MP4 output all reach the scene."""
    model = _model(tmp_path)
    result = _call(
        runner, tmp_path, "run", _request(tmp_path, "run", model=str(model)), monkeypatch
    )

    trail = _trail(tmp_path)
    render = trail["render"]
    assert render["engine"] == "BLENDER_EEVEE"
    assert render["eevee"] == {
        "taa_render_samples": TAA_SAMPLES,
        "use_raytracing": True,
        "ray_tracing_method": "SCREEN",
        "use_fast_gi": True,
        "use_shadows": True,
    }
    assert render["resolution"] == [WIDTH, HEIGHT]
    assert render["exposure"] == EXPOSURE
    assert render["look"] == LOOK
    assert render["fps"] == FPS
    assert render["frames"] == [1, FRAMES]
    assert (render["media_type"], render["file_format"]) == ("VIDEO", "FFMPEG")
    assert render["ffmpeg"] == {"format": "MPEG4", "codec": "H264", "crf": "HIGH"}
    assert render["filepath"] == str(tmp_path / "out" / "estudio-tour.mp4")
    # A perspective camera with the default 30 mm lens, as the recipe says.
    assert trail["camera"] == {"type": "PERSP", "lens": 30.0, "clip_end": 500.0}

    asset = result["assets"][0]
    assert asset["file"] == "estudio-tour.mp4"
    assert (asset["kind"], asset["mime"]) == ("video", "video/mp4")
    assert asset["properties"] == {
        "width": WIDTH,
        "height": HEIGHT,
        "frames": FRAMES,
        "fps": FPS,
        "seed": 0,
    }
    assert asset["seed"] == 0 and asset["inputs"] == [str(model)]
    assert result["tool"]["name"] == "blender"


def test_the_animation_render_writes_the_mp4(tmp_path: Path, runner, monkeypatch) -> None:
    """The tour renders an animation, not a still, and the clip lands on disk."""
    model = _model(tmp_path)
    _call(runner, tmp_path, "run", _request(tmp_path, "run", model=str(model)), monkeypatch)

    calls = _trail(tmp_path)["render_calls"]
    assert calls == [{"animation": True, "write_still": False}]
    assert (tmp_path / "out" / "estudio-tour.mp4").is_file()


def test_tour_bakes_before_materials(tmp_path: Path, runner, monkeypatch) -> None:
    """The tour bakes every piece before any material is created."""
    model = _model(tmp_path)
    request = _request(tmp_path, "run", model=str(model), seconds=2, fps=12)
    _call(runner, tmp_path, "run", request, monkeypatch)

    trail = _trail(tmp_path)
    events = trail["events"]
    bakes = [event for event in events if event.split(":")[0] in {"parent_clear", "bake"}]
    materials = [event for event in events if event.startswith("material:")]
    assert bakes == [
        "parent_clear:muros",
        "bake:muros",
        "parent_clear:piso",
        "bake:piso",
        "parent_clear:vidrio-1",
        "bake:vidrio-1",
        "parent_clear:cama",
        "bake:cama",
        "parent_clear:mesa",
        "bake:mesa",
    ]
    assert max(events.index(event) for event in bakes) < min(
        events.index(event) for event in materials
    )
    assert all(parent is None for parent in trail["parents"].values())
    assert trail["baked"] == ["cama", "mesa", "muros", "piso", "vidrio-1"]


def test_one_keyframe_pair_per_frame_across_the_tour(tmp_path: Path, runner, monkeypatch) -> None:
    """240 frames means 240 location and 240 rotation_euler keys, on 1..240."""
    model = _model(tmp_path)
    _call(runner, tmp_path, "run", _request(tmp_path, "run", model=str(model)), monkeypatch)

    keyframes = _trail(tmp_path)["keyframes"]
    assert sorted(keyframes) == ["location", "rotation_euler"]
    expected = list(range(1, FRAMES + 1))
    assert keyframes["location"] == expected
    assert keyframes["rotation_euler"] == expected


def test_the_camera_moves_from_the_start_triple_to_the_end_triple(
    tmp_path: Path, runner, monkeypatch
) -> None:
    """The first pose is the start triple, the last is the end triple."""
    model = _model(tmp_path)
    _call(runner, tmp_path, "run", _request(tmp_path, "run", model=str(model)), monkeypatch)

    poses = _trail(tmp_path)["camera_poses"]
    first = poses["1"]["location"]
    last = poses[str(FRAMES)]["location"]
    # Azimut -75, elevation 55, distance 14.0 at the start; -15/40/10.5 at the end.
    start = 14.0
    assert math.hypot(math.hypot(first[0], first[1]), first[2]) == pytest.approx(start)
    assert poses["1"]["rotation_euler"][0] == pytest.approx(math.pi / 2 - math.radians(55))
    assert math.hypot(math.hypot(last[0], last[1]), last[2]) == pytest.approx(10.5)
    assert poses[str(FRAMES)]["rotation_euler"][0] == pytest.approx(math.pi / 2 - math.radians(40))


def test_the_move_uses_the_smoothstep_and_the_piece_pairs(
    tmp_path: Path, runner, monkeypatch
) -> None:
    """The interpolation is smoothstep, not linear, and the piece's pairs win."""
    model = _model(tmp_path)
    request = _request(
        tmp_path,
        "run",
        model=str(model),
        azimuth=[{"start": -90, "end": 90}],
        elevation=[{"start": 60, "end": 30}],
        distance=[{"start": 20.0, "end": 10.0}],
        focal=WIDE_FOCAL,
        seconds=SHORT_SECONDS,
        fps=SHORT_FPS,
    )
    result = _call(runner, tmp_path, "run", request, monkeypatch)

    tour = runner.recorrido.plan(request["inputs"])
    assert (tour.frames, tour.fps, tour.focal) == (SHORT_FRAMES, SHORT_FPS, WIDE_FOCAL)
    assert (tour.azimuth, tour.elevation, tour.distance) == (
        (-90.0, 90.0),
        (60.0, 30.0),
        (20.0, 10.0),
    )
    frames = tour.frames
    keyframes = _trail(tmp_path)["keyframes"]
    assert len(keyframes["location"]) == frames
    assert _trail(tmp_path)["camera"]["lens"] == WIDE_FOCAL
    assert result["assets"][0]["properties"]["frames"] == SHORT_FRAMES
    # Frame 13 is a quarter of the way through; smoothstep puts it at ~0.162,
    # not the 0.25 a linear interpolation would, so the pose names which one ran.
    t = 12 / (frames - 1)
    eased = runner.recorrido.smooth(t)
    assert eased == pytest.approx(t * t * (3 - 2 * t))
    assert eased < t - 0.05
    rotation = _trail(tmp_path)["camera_poses"]["13"]["rotation_euler"]
    assert rotation[2] == pytest.approx(math.radians(-90 + 180 * eased) + math.pi / 2)


def test_a_tour_without_a_model_entry_falls_back_to_the_lab_defaults(runner) -> None:
    """The plan's defaults are the lab's: 10 s, 24 fps, -75/-15, 55/40, 14/10.5."""
    tour = runner.recorrido.plan({})
    assert (tour.frames, tour.fps, tour.focal) == (240, 24, 30.0)
    assert tour.azimuth == (-75.0, -15.0)
    assert tour.elevation == (55.0, 40.0)
    assert tour.distance == (14.0, 10.5)


# --- the probe: a struct-built MP4 with known measurements.


def _box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body) + 8) + kind + body


def _ftyp() -> bytes:
    return _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")


def _mvhd(timescale: int, duration: int) -> bytes:
    body = b"\x00\x00\x00\x00"  # version 0, flags 0
    body += struct.pack(
        ">IIII", 0, 0, timescale, duration
    )  # created, modified, timescale, duration
    return _box(b"mvhd", body)


def _avc1(width: int, height: int) -> bytes:
    body = b"\x00" * 6 + struct.pack(">H", 1)  # reserved, data reference index
    body += b"\x00" * 16  # pre_defined and reserved before the size
    body += struct.pack(">HH", width, height)
    return _box(b"avc1", body)


def _stsd(width: int, height: int) -> bytes:
    body = b"\x00\x00\x00\x00" + struct.pack(">I", 1)  # version/flags, entry count
    body += _avc1(width, height)
    return _box(b"stsd", body)


def _stts(frames: int, timescale: int, fps: int) -> bytes:
    delta = timescale // fps
    body = b"\x00\x00\x00\x00" + struct.pack(">I", 1)  # version/flags, entry count
    body += struct.pack(">II", frames, delta)
    return _box(b"stts", body)


def _mp4(width: int, height: int, frames: int, fps: int, timescale: int = 24_000) -> bytes:
    """A minimal ISO BMFF file carrying just what the probe reads."""
    duration = frames * timescale // fps
    stbl = _box(b"stbl", _stsd(width, height) + _stts(frames, timescale, fps))
    minf = _box(b"minf", stbl)
    mdia = _box(b"mdia", minf)
    trak = _box(b"trak", mdia)
    moov = _box(b"moov", _mvhd(timescale, duration) + trak)
    return _ftyp() + moov


def test_the_probe_reads_an_mp4s_size_and_frame_count(tmp_path: Path, runner) -> None:
    """A file built to be 1280x720 with 240 frames reads back as exactly that."""
    path = tmp_path / "tour.mp4"
    path.write_bytes(_mp4(WIDTH, HEIGHT, FRAMES, FPS))

    assert runner._probe_mp4(str(path)) == {
        "width": WIDTH,
        "height": HEIGHT,
        "frames": FRAMES,
        "fps": FPS,
    }


def test_the_probe_reads_other_measurements_too(tmp_path: Path, runner) -> None:
    """Nothing is pinned to 720p: the reader returns what the file says."""
    path = tmp_path / "small.mp4"
    path.write_bytes(_mp4(SMALL_WIDTH, SMALL_HEIGHT, SHORT_FRAMES, SHORT_FPS))

    assert runner._probe_mp4(str(path)) == {
        "width": SMALL_WIDTH,
        "height": SMALL_HEIGHT,
        "frames": SHORT_FRAMES,
        "fps": SHORT_FPS,
    }


def test_verify_passes_an_mp4_that_matches_the_entry(tmp_path: Path, runner, monkeypatch) -> None:
    """The thresholds come from the piece's entry, and the probe meets them."""
    clip = tmp_path / "out" / "estudio-tour.mp4"
    clip.parent.mkdir()
    clip.write_bytes(_mp4(WIDTH, HEIGHT, FRAMES, FPS))
    request = _request(tmp_path, "verify", assets=[str(clip)], model="estudio.glb")

    result = _call(runner, tmp_path, "verify", request, monkeypatch)

    verdict = result["assets"][0]
    assert verdict["passed"] is True
    assert verdict["verifier"] == "mp4"
    assert verdict["metrics"] == {"width": WIDTH, "height": HEIGHT, "frames": FRAMES, "fps": FPS}
    assert verdict["thresholds"] == {
        "width": WIDTH,
        "height": HEIGHT,
        "frames": FRAMES,
        "fps": FPS,
    }


def test_verify_fails_a_clip_whose_frame_count_disagrees(
    tmp_path: Path, runner, monkeypatch
) -> None:
    """A 120-frame clip against a 10 s 24 fps entry fails on the frame count."""
    clip = tmp_path / "out" / "estudio-tour.mp4"
    clip.parent.mkdir()
    clip.write_bytes(_mp4(WIDTH, HEIGHT, 120, FPS))
    request = _request(tmp_path, "verify", assets=[str(clip)], model="estudio.glb")

    verdict = _call(runner, tmp_path, "verify", request, monkeypatch)["assets"][0]

    assert verdict["passed"] is False
    assert verdict["metrics"]["frames"] == HALF_FRAMES
    assert verdict["thresholds"]["frames"] == FRAMES


def _empty_mvhd() -> bytes:
    """An MP4 whose ``mvhd`` body is empty: there is no timescale to read."""
    return _ftyp() + _box(b"moov", _box(b"mvhd", b""))


def _lying_stts() -> bytes:
    """An MP4 whose ``stts`` claims a million entries in an eight-byte body."""
    stts = _box(b"stts", b"\x00\x00\x00\x00" + struct.pack(">I", 1_000_000))
    stbl = _box(b"stbl", _stsd(WIDTH, HEIGHT) + stts)
    minf = _box(b"minf", stbl)
    moov = _box(b"moov", _mvhd(24_000, 10_000) + _box(b"trak", _box(b"mdia", minf)))
    return _ftyp() + moov


def test_verify_passes_an_unparsable_file_false_with_its_error(
    tmp_path: Path, runner, monkeypatch
) -> None:
    """A file that is not an MP4 is a failed verdict, never an exception."""
    broken = tmp_path / "out" / "broken.mp4"
    broken.parent.mkdir()
    broken.write_bytes(b"definitely not an mp4")
    request = _request(tmp_path, "verify", assets=[str(broken)], model="estudio.glb")

    done = _call(runner, tmp_path, "verify", request, monkeypatch)

    verdict = done["assets"][0]
    assert verdict["passed"] is False
    assert "error" in verdict["metrics"]
    assert verdict["verifier"] == "mp4"


@pytest.mark.parametrize("build", [_empty_mvhd, _lying_stts])
def test_the_probe_refuses_a_truncated_box(tmp_path: Path, runner, build) -> None:
    """A body shorter than its own fields is a ValueError, not an IndexError."""
    path = tmp_path / "truncated.mp4"
    path.write_bytes(build())

    with pytest.raises(ValueError):
        runner._probe_mp4(str(path))


@pytest.mark.parametrize("build", [_empty_mvhd, _lying_stts])
def test_verify_passes_a_truncated_mp4_false_without_raising(
    tmp_path: Path, runner, monkeypatch, build
) -> None:
    """No malformed clip escapes the verdict: each one comes back passed False."""
    clip = tmp_path / "out" / "estudio-tour.mp4"
    clip.parent.mkdir()
    clip.write_bytes(build())
    request = _request(tmp_path, "verify", assets=[str(clip)], model="estudio.glb")

    verdict = _call(runner, tmp_path, "verify", request, monkeypatch)["assets"][0]

    assert verdict["passed"] is False
    assert verdict["verifier"] == "mp4"
    assert set(verdict["metrics"]) == {"error"}


def test_preview_writes_the_video_schema_beside_the_clip(
    tmp_path: Path, runner, monkeypatch
) -> None:
    """The preview carries the probe's measurements and the tour line."""
    clip = tmp_path / "out" / "estudio-tour.mp4"
    clip.parent.mkdir()
    clip.write_bytes(_mp4(WIDTH, HEIGHT, FRAMES, FPS))
    request = _request(tmp_path, "preview", assets=[str(clip)], model="estudio.glb", seed=7)

    result = _call(runner, tmp_path, "preview", request, monkeypatch)

    entry = result["assets"][0]
    assert entry["file"] == "estudio-tour.mp4"
    assert entry["preview"] == "estudio-tour.mp4.preview.json"
    data = json.loads((clip.parent / entry["preview"]).read_text(encoding="utf-8"))
    assert set(data) == set(VIDEO_SCHEMA["required"])
    assert data["preview"] == 1 and data["kind"] == "video"
    assert data["name"] == "estudio-tour"
    assert (data["width"], data["height"]) == (WIDTH, HEIGHT)
    assert (data["length"], data["fps"]) == (FRAMES, FPS)
    assert data["seed"] == SEED
    assert data["prompt"] == ("estudio-tour · camera tour · azimuth -75→-15 · 240f @ 24fps")
    assert len(data["summary"]) <= SUMMARY_MAX


def test_the_default_route_is_untouched(runner) -> None:
    """product and the default table keep their verbs; tour has its own."""
    assert set(runner.VERBS) == {"run", "verify", "preview", "doctor"}
    assert runner.PRODUCTO_VERBS["run"].__name__ == "_producto_run"
    assert runner.RECORRIDO_VERBS["run"].__name__ == "_recorrido_run"
    assert runner.RECORRIDO_VERBS["verify"].__name__ == "_recorrido_verify"
    assert runner.RECORRIDO_VERBS["preview"].__name__ == "_recorrido_preview"
    assert runner.RECORRIDO_VERBS["doctor"].__name__ == "_doctor"
    assert runner._verbs("blender.tour") is runner.RECORRIDO_VERBS
    assert runner._verbs("blender.product") is runner.PRODUCTO_VERBS
    assert runner._verbs("blender.photo") is runner.VERBS
