"""The blender cycle through a stub host: paths, materials, failure, verify.

No real Blender runs here. A stub ``blender`` stands where the host binary
does: it answers ``--version``, records each launch, and executes the package
entry with a stub ``bpy`` on its path, so the entry takes its in-Blender
branch. The stub scene reads a small JSON of pieces (one per glTF element,
with its name) and writes a trail of what the recipe built — the material each
mesh received, the scale and the turn applied, the render settings and the
paths it was handed.

The launcher process deliberately does *not* see the stub ``bpy``: it must
resolve ``BLENDER_EXE`` and drive the host, which is the route the spec names
(convert paths, one retry only on a WSL interop failure).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import PIL.Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"
RUNNER = PACKAGE / "runner.py"
SCHEMA = json.loads(
    (ROOT / "schemas" / "preview" / "image.schema.json").read_text(encoding="utf-8")
)
GENERIC_SCHEMA = json.loads(
    (ROOT / "schemas" / "preview" / "generic.schema.json").read_text(encoding="utf-8")
)
WIDTH = 1600
HEIGHT = 1000
#: The recipe the approved lab render pinned: Cycles on the GPU, denoised.
SAMPLES = 128
EXPOSURE = -0.6
#: The frame's height over its width, the ratio fit_scale renders with.
ASPECT = HEIGHT / WIDTH
#: The smallest scale fit_scale returns, so a tiny piece stays a piece.
SCALE_FLOOR = 4.0
SKY_STRENGTH = 0.2
SUN_FORCE = 3.0
#: The preview's one-line summary cap, from the image schema.
SUMMARY_MAX = 160
#: The attempts a WSL interop failure may take: the first launch and one retry.
RETRIES = 2
#: The scene plane's drop under the model's lowest point, in metres.
FLOOR_DROP = 0.001
#: The turned view a piece may ask for.
TURNED_SCALE = 12.0
TURNED_EXPOSURE = -0.9
TURNED_ROTATION = 90
#: The lab's study pieces: names are the material prefixes.
PIECES = [
    ("muros", (6000.0, 4500.0, 2600.0)),
    ("piso", (6300.0, 4800.0, 120.0)),
    ("vidrio-1", (1200.0, 20.0, 1200.0)),
    ("vidrio-2", (1200.0, 20.0, 1200.0)),
    ("cama", (1400.0, 2000.0, 450.0)),
    ("almohada", (1200.0, 400.0, 120.0)),
    ("mesa", (1000.0, 1000.0, 750.0)),
    ("sillas", (400.0, 400.0, 900.0)),
]

STUB_BPY = '''
"""A stub bpy: the daylight recipe's scene, and a trail of what it built."""

import json
import math
import os
from pathlib import Path

TRAIL = {}


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


class Euler:
    """Blender's ``rotation_euler``: writes are ignored in ``QUATERNION`` mode.

    Blender keeps the rotation in one channel per mode; the glTF importer
    leaves every object in ``QUATERNION``, so a recipe that writes
    ``rotation_euler`` without switching the mode first turns nothing.
    """

    def __init__(self, owner):
        self._owner = owner

    def __getitem__(self, index):
        return self._owner._euler[index]

    def __setitem__(self, index, value):
        if self._owner._rotation_mode == "QUATERNION":
            return
        self._owner._euler[index] = value

    def __iter__(self):
        return iter(self._owner._euler)

    def __len__(self):
        return 3


class Object:
    def __init__(
        self,
        name,
        kind="MESH",
        size=(1.0, 1.0, 1.0),
        location=(0.0, 0.0, 0.0),
        data=None,
        rotation_mode="XYZ",
    ):
        self.name = name
        self.type = kind
        self.parent = None
        self.scale = [1.0, 1.0, 1.0]
        self.location = list(location)
        self._rotation_mode = rotation_mode
        self._euler = [0.0, 0.0, 0.0]
        self.rotation_quaternion = [1.0, 0.0, 0.0, 0.0]
        self.data = data if data is not None else MeshData(name) if kind == "MESH" else object()
        half = [side / 2 for side in size]
        self.bound_box = [
            [x, y, z]
            for x in (-half[0], half[0])
            for y in (-half[1], half[1])
            for z in (-half[2], half[2])
        ]

    @property
    def rotation_mode(self):
        return self._rotation_mode

    @rotation_mode.setter
    def rotation_mode(self, value):
        if value == self._rotation_mode:
            return
        if self._rotation_mode == "QUATERNION":
            self._euler = _quaternion_euler(self.rotation_quaternion)
        else:
            self.rotation_quaternion = _euler_quaternion(self._euler)
        self._rotation_mode = value

    @property
    def rotation_euler(self):
        return Euler(self)

    @rotation_euler.setter
    def rotation_euler(self, value):
        if self._rotation_mode == "QUATERNION":
            return
        self._euler = [float(item) for item in value]

    @property
    def rotation(self):
        """The rotation Blender actually applies, as ``(cos, sin)`` about Z."""
        if self._rotation_mode == "QUATERNION":
            turn = _quaternion_euler(self.rotation_quaternion)[2]
        else:
            turn = self._euler[2]
        return math.cos(turn), math.sin(turn)

    @property
    def matrix_world(self):
        cos, sin = self.rotation
        scale = self.scale
        return [
            [cos * scale[0], -sin * scale[1], 0.0, self.location[0]],
            [sin * scale[0], cos * scale[1], 0.0, self.location[1]],
            [0.0, 0.0, scale[2], self.location[2]],
        ]


def _quaternion_euler(quaternion):
    """A quaternion's Z turn in radians, enough for the stub's single axis."""
    w, x, y, z = quaternion
    return [0.0, 0.0, math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))]


def _euler_quaternion(euler):
    """The quaternion of a Z turn, which is all the stub ever rotates about."""
    half = euler[2] / 2
    return [math.cos(half), 0.0, 0.0, math.sin(half)]


class Camera:
    def __init__(self, name):
        self.name = name
        self.type = "PERSP"
        self.ortho_scale = 6.0
        self.lens = 50.0
        self.clip_start = 0.1


class Light:
    def __init__(self, name, kind="SUN"):
        self.name = name
        self.kind = kind
        self.type = kind
        self.energy = 0.0
        self.angle = 0.0
        self.shape = "POINT"
        self.size = 0.0


class World:
    def __init__(self, name):
        self.name = name
        self.use_nodes = False
        self.node_tree = NodeTree()


class Device:
    def __init__(self, name, kind):
        self.name = name
        self.type = kind
        self.use = False


class Materials:
    def new(self, name):
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


class RenderSettings:
    def __init__(self):
        self.resolution_x = 1920
        self.resolution_y = 1080
        self.filepath = ""
        self.engine = ""


class ViewSettings:
    def __init__(self):
        self.exposure = 0.0
        self.look = ""


class CyclesSettings:
    def __init__(self):
        self.device = "CPU"
        self.samples = 1
        self.use_denoising = False
        self.seed = 0


class Scene:
    def __init__(self):
        self.objects = []
        self.collection = Collection(self)
        self.render = RenderSettings()
        self.view_settings = ViewSettings()
        self.cycles = CyclesSettings()
        self.camera = None
        self.world = None


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

    def stl_import(self, filepath):
        TRAIL["stl_import"] = filepath
        _load_pieces()


class ImportOps:
    def gltf(self, filepath):
        TRAIL["import_filepath"] = filepath
        _load_pieces()


def _load_pieces():
    source = os.environ.get("STUB_SCENE", "")
    pieces = json.loads(Path(source).read_text())["pieces"] if source else []
    for piece in pieces:
        context.scene.objects.append(
            Object(
                piece["name"],
                size=tuple(piece.get("size", (1000.0, 1000.0, 1000.0))),
                location=tuple(piece.get("location", (0.0, 0.0, 0.0))),
                # The glTF importer leaves every object in QUATERNION mode,
                # where Blender ignores rotation_euler. The identity
                # quaternion keeps the stub's single-axis geometry exact.
                rotation_mode="QUATERNION",
            )
        )


class MeshOps:
    def primitive_plane_add(self, size=2.0, location=(0.0, 0.0, 0.0)):
        obj = Object("Plane", size=(size, size, 0.0), location=location)
        context.scene.objects.append(obj)
        context.active_object = obj


class RenderOps:
    def render(self, write_still=False):
        scene = context.scene
        meshes = [obj for obj in scene.objects if obj.type == "MESH"]
        TRAIL["pieces"] = [obj.name for obj in meshes]
        TRAIL["materials"] = {
            obj.name: obj.data.materials[0].name for obj in meshes if obj.data.materials
        }
        TRAIL["missing_material"] = [obj.name for obj in meshes if not obj.data.materials]
        roots = [obj for obj in scene.objects if obj.parent is None]
        TRAIL["scales"] = {obj.name: list(obj.scale) for obj in roots}
        TRAIL["turns"] = {obj.name: math.atan2(*reversed(obj.rotation)) for obj in roots}
        TRAIL["rotmodes"] = {obj.name: obj.rotation_mode for obj in roots}
        TRAIL["render"] = {
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "filepath": scene.render.filepath,
            "exposure": scene.view_settings.exposure,
            "look": scene.view_settings.look,
            "engine": scene.render.engine,
            "device": scene.cycles.device,
            "samples": scene.cycles.samples,
            "denoise": scene.cycles.use_denoising,
            "seed": scene.cycles.seed,
        }
        TRAIL["camera"] = None if scene.camera is None else {
            "type": scene.camera.data.type,
            "ortho_scale": scene.camera.data.ortho_scale,
            "lens": scene.camera.data.lens,
            "clip_start": scene.camera.data.clip_start,
            "location": list(scene.camera.location),
        }
        TRAIL["sun"] = {
            obj.name: obj.data.energy for obj in scene.objects if obj.type == "LIGHT"
        }
        TRAIL["lights"] = {
            obj.name: {
                "type": obj.data.type,
                "shape": obj.data.shape,
                "energy": obj.data.energy,
                "size": obj.data.size,
                "location": list(obj.location),
            }
            for obj in scene.objects
            if obj.type == "LIGHT"
        }
        TRAIL["span"] = _span(meshes)
        TRAIL["floor"] = next(
            (list(obj.location) for obj in scene.objects if obj.name == "suelo"), None
        )
        world = scene.world
        background = (
            None if world is None else world.node_tree.nodes["Background"]
        )
        TRAIL["backdrop"] = (
            None if background is None else background.inputs["Color"].default_value
        )
        TRAIL["sky_strength"] = (
            None if background is None else background.inputs["Strength"].default_value
        )
        _write_png(scene)
        target = os.environ.get("STUB_TRAIL", "")
        if target:
            Path(target).write_text(json.dumps(TRAIL, default=list))


def _span(meshes):
    """The longest side of every mesh's world bound box, in metres."""
    points = [
        [
            sum(obj.matrix_world[axis][column] * corner[column] for column in range(3))
            + obj.matrix_world[axis][3]
            for axis in range(3)
        ]
        for obj in meshes
        for corner in obj.bound_box
    ]
    if not points:
        return 0.0
    return max(
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    )


def _write_png(scene):
    target = os.environ.get("STUB_PNG_OUT", "") or str(scene.render.filepath)
    if not target:
        return
    import PIL.Image

    size = (scene.render.resolution_x, scene.render.resolution_y)
    PIL.Image.new("RGB", size, (20, 40, 60)).save(target)


class Ops:
    def __init__(self):
        self.wm = WmOps()
        self.import_scene = ImportOps()
        self.mesh = MeshOps()
        self.render = RenderOps()


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


def _load_escena():
    spec = importlib.util.spec_from_file_location("blender_escena", PACKAGE / "escena.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


escena = _load_escena()


def _stub_bpy(tmp_path: Path) -> Path:
    folder = tmp_path / "stub-bpy"
    folder.mkdir()
    (folder / "bpy.py").write_text(STUB_BPY, encoding="utf-8")
    return folder


def _stub_blender(tmp_path: Path) -> Path:
    path = tmp_path / "bin" / "blender"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(STUB_BLENDER.replace("{python}", sys.executable), encoding="utf-8")
    path.chmod(0o755)
    return path


def _scene(
    tmp_path: Path, pieces: list[tuple[str, tuple[float, float, float]]] | None = None
) -> Path:
    path = tmp_path / "scene.json"
    entries = [
        {"name": name, "size": list(size)} for name, size in (PIECES if pieces is None else pieces)
    ]
    path.write_text(json.dumps({"pieces": entries}), encoding="utf-8")
    return path


def _model(tmp_path: Path) -> Path:
    path = tmp_path / "estudio.glb"
    path.write_bytes(b"glTF-stub")
    return path


def _request(
    tmp_path: Path, verb: str, capability: str = "blender.photo", **inputs
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


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        **os.environ,
        "BLENDER_EXE": str(_stub_blender(tmp_path)),
        "STUB_BPY": str(_stub_bpy(tmp_path)),
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


def _trail(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "trail.json").read_text(encoding="utf-8"))


def test_the_cycle_renders_the_study_and_dresses_every_piece(tmp_path: Path) -> None:
    """run drives the host, which imports the glTF and writes the photo."""
    model = _model(tmp_path)
    request = _request(tmp_path, "run", model=str(model))
    env = _env(
        tmp_path,
        STUB_SCENE=str(_scene(tmp_path)),
        STUB_TRAIL=str(tmp_path / "trail.json"),
    )

    done, result_path = _call("run", request, tmp_path, env)

    assert done.returncode == 0, done.stdout + done.stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    asset = result["assets"][0]
    assert asset["file"] == "estudio-photo.png"
    assert (asset["kind"], asset["mime"]) == ("image", "image/png")
    assert asset["seed"] == 0
    assert asset["inputs"] == [str(model)]
    assert asset["properties"] == {
        "width": WIDTH,
        "height": HEIGHT,
        "samples": 128,
        "exposure": -0.6,
        "rotation": 0.0,
    }
    assert result["tool"]["name"] == "blender"
    with PIL.Image.open(tmp_path / "out" / "estudio-photo.png") as image:
        assert image.size == (WIDTH, HEIGHT)
    trail = _trail(tmp_path)
    assert trail["import_filepath"] == str(model)
    assert trail["pieces"] == [name for name, _size in PIECES] + ["suelo"]
    assert trail["missing_material"] == []
    assert trail["materials"]["vidrio-1"] == "vidrio"
    assert trail["materials"]["vidrio-2"] == "vidrio"
    assert trail["materials"]["muros"] == "muros"
    assert trail["materials"]["suelo"] == "suelo"


def test_the_floor_sits_below_the_model_and_never_through_it(tmp_path: Path) -> None:
    """A plane at the model's mid-height would hide the furniture from the camera."""
    model = _model(tmp_path)
    request = _request(tmp_path, "run", model=str(model))
    env = _env(
        tmp_path,
        STUB_SCENE=str(_scene(tmp_path)),
        STUB_TRAIL=str(tmp_path / "trail.json"),
    )

    done, _result = _call("run", request, tmp_path, env)

    assert done.returncode == 0, done.stdout + done.stderr
    floor = _trail(tmp_path)["floor"]
    # The stub's pieces straddle z = 0; the tallest is 2600 mm, so the lowest
    # corner is -1.3 m and the plane sits a hair under it, never at the middle.
    lowest = -max(size[2] for _name, size in PIECES) / 2 * 0.001
    assert floor[2] == pytest.approx(lowest - FLOOR_DROP)
    # The model's own mid-height is 0 here, so a plane there would cut it in two.
    assert floor[2] < lowest < 0.0


def test_the_recipe_scales_to_metres_and_lights_the_scene(tmp_path: Path) -> None:
    """The glTF is millimetres; the recipe is Cycles, OPTIX, 128, denoised."""
    model = _model(tmp_path)
    request = _request(tmp_path, "run", model=str(model))
    env = _env(
        tmp_path,
        STUB_SCENE=str(_scene(tmp_path)),
        STUB_TRAIL=str(tmp_path / "trail.json"),
    )

    done, _result = _call("run", request, tmp_path, env)

    assert done.returncode == 0, done.stdout + done.stderr
    trail = _trail(tmp_path)
    for piece, _size in PIECES:
        assert trail["scales"][piece] == [0.001, 0.001, 0.001], piece
    render = trail["render"]
    assert render["resolution"] == [WIDTH, HEIGHT]
    assert render["engine"] == "CYCLES"
    assert render["device"] == "GPU"
    assert render["samples"] == SAMPLES
    assert render["denoise"] is True
    assert render["exposure"] == EXPOSURE
    assert render["look"] == "AgX - Medium High Contrast"
    assert render["filepath"] == str(tmp_path / "out" / "estudio-photo.png")
    assert trail["camera"]["type"] == "ORTHO"
    assert trail["camera"]["ortho_scale"] == pytest.approx(_expected_scale())
    assert trail["sky_strength"] == SKY_STRENGTH
    assert trail["sun"]["sol"] == SUN_FORCE


def _box_corners(size: tuple[float, float, float]) -> list[tuple[float, float, float]]:
    """The eight corners of a box of ``size`` metres centred at the origin."""
    half = [side / 2 for side in size]
    return [
        (x, y, z)
        for x in (-half[0], half[0])
        for y in (-half[1], half[1])
        for z in (-half[2], half[2])
    ]


def _stub_corners() -> list[tuple[float, float, float]]:
    """The stub study's world corners in metres: millimetre sizes at the origin."""
    corners: list[tuple[float, float, float]] = []
    for _name, size in PIECES:
        half = [side / 2 * 0.001 for side in size]
        corners.extend(
            (x, y, z)
            for x in (-half[0], half[0])
            for y in (-half[1], half[1])
            for z in (-half[2], half[2])
        )
    return corners


def _expected_scale() -> float:
    """The scale the recipe fits to the stub study when the piece omits scale."""
    return escena.fit_scale(_stub_corners(), (0.0, 0.0, 0.0), -40.0, 48.0, ASPECT)


def _projected(
    corner: tuple[float, float, float],
    centre: tuple[float, float, float],
    azimuth: float,
    elevation: float,
) -> tuple[float, float]:
    """One corner's frame coordinates along the camera's own right and up axes."""
    azimuth, elevation = math.radians(azimuth), math.radians(elevation)
    right = (-math.sin(azimuth), math.cos(azimuth), 0.0)
    up = (
        -math.sin(elevation) * math.cos(azimuth),
        -math.sin(elevation) * math.sin(azimuth),
        math.cos(elevation),
    )
    offset = [corner[axis] - centre[axis] for axis in range(3)]
    across = sum(offset[axis] * right[axis] for axis in range(3))
    upright = sum(offset[axis] * up[axis] for axis in range(3))
    return across, upright


def test_fit_scale_floors_a_one_metre_cube_at_four_metres() -> None:
    """A 1 m cube needs less than 4 m, so the floor holds: the photo stays a piece."""
    corners = _box_corners((1.0, 1.0, 1.0))
    assert escena.fit_scale(corners, (0.0, 0.0, 0.0), -40.0, 48.0, ASPECT) == SCALE_FLOOR


def test_fit_scale_frames_a_wide_low_block() -> None:
    """A 16 x 12 x 3 m block: every projected corner lands inside the frame."""
    corners = _box_corners((16.0, 12.0, 3.0))
    centre = (0.0, 0.0, 0.0)
    scale = escena.fit_scale(corners, centre, -40.0, 48.0, ASPECT)
    assert scale > SCALE_FLOOR
    for corner in corners:
        across, upright = _projected(corner, centre, -40.0, 48.0)
        assert abs(across) <= scale / 2
        assert abs(upright) <= scale * ASPECT / 2


def test_fit_scale_is_driven_by_height_for_a_tall_tower() -> None:
    """A 4 x 4 x 16 m tower: the height over the aspect beats the width."""
    corners = _box_corners((4.0, 4.0, 16.0))
    centre = (0.0, 0.0, 0.0)
    spans = [_projected(corner, centre, -40.0, 48.0) for corner in corners]
    width = 2 * max(abs(across) for across, _upright in spans)
    height = 2 * max(abs(upright) for _across, upright in spans)
    assert height / ASPECT > width
    assert escena.fit_scale(corners, centre, -40.0, 48.0, ASPECT) == pytest.approx(
        1.1 * height / ASPECT
    )


def test_model_corners_skips_the_floor_plane() -> None:
    """model_corners reads every MESH but the suelo the recipe adds."""
    scene = SimpleNamespace(
        objects=[
            SimpleNamespace(
                type="MESH",
                name="muros",
                matrix_world=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]],
                bound_box=[[2.0, 3.0, 4.0]],
            ),
            SimpleNamespace(
                type="MESH",
                name="suelo",
                matrix_world=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]],
                bound_box=[[5.0, 6.0, 7.0]],
            ),
        ]
    )
    assert escena.model_corners(scene) == [(2.0, 3.0, 4.0)]


def test_the_piece_camera_the_turn_and_the_exposure_reach_the_scene(tmp_path: Path) -> None:
    """The three scene parameters the manifest declares are applied."""
    model = _model(tmp_path)
    request = _request(
        tmp_path,
        "run",
        model=str(model),
        camera=[{"azimuth": 25, "elevation": 40, "scale": 12}],
        rotation=90,
        exposure=-0.9,
    )
    env = _env(
        tmp_path,
        STUB_SCENE=str(_scene(tmp_path)),
        STUB_TRAIL=str(tmp_path / "trail.json"),
    )

    done, result_path = _call("run", request, tmp_path, env)

    assert done.returncode == 0, done.stdout + done.stderr
    trail = _trail(tmp_path)
    assert trail["camera"]["ortho_scale"] == TURNED_SCALE
    assert trail["render"]["exposure"] == TURNED_EXPOSURE
    assert trail["turns"]["muros"] == pytest.approx(math.radians(TURNED_ROTATION))
    # The glTF importer leaves the pieces in QUATERNION mode, where Blender
    # ignores rotation_euler: the recipe must switch the mode to turn them.
    assert trail["rotmodes"]["muros"] == "XYZ"
    properties = json.loads(result_path.read_text())["assets"][0]["properties"]
    assert properties["rotation"] == float(TURNED_ROTATION)


def test_no_turn_leaves_the_gltf_import_untouched(tmp_path: Path) -> None:
    """Without ``rotation`` the recipe never rewrites the importer's rotation."""
    model = _model(tmp_path)
    request = _request(tmp_path, "run", model=str(model))
    env = _env(
        tmp_path,
        STUB_SCENE=str(_scene(tmp_path)),
        STUB_TRAIL=str(tmp_path / "trail.json"),
    )

    done, _result = _call("run", request, tmp_path, env)

    assert done.returncode == 0, done.stdout + done.stderr
    trail = _trail(tmp_path)
    imported = {name: trail["rotmodes"][name] for name, _size in PIECES}
    assert set(imported.values()) == {"QUATERNION"}
    assert trail["turns"]["muros"] == 0.0


def test_a_piece_without_a_material_prefix_fails_the_run_loudly(tmp_path: Path) -> None:
    """Nothing is rendered half-dressed: the run fails naming the piece."""
    model = _model(tmp_path)
    pieces = [*PIECES, ("techo", (6300.0, 4800.0, 100.0))]
    request = _request(tmp_path, "run", model=str(model))
    env = _env(tmp_path, STUB_SCENE=str(_scene(tmp_path, pieces)))

    done, result_path = _call("run", request, tmp_path, env)

    assert done.returncode != 0
    assert "piezas sin material" in done.stderr
    assert "techo" in done.stderr
    assert not result_path.exists()
    assert not (tmp_path / "out" / "estudio-photo.png").exists()


def _failures(tmp_path: Path, mode: str) -> tuple[subprocess.CompletedProcess[str], int]:
    model = _model(tmp_path)
    request = _request(tmp_path, "run", model=str(model))
    counter = tmp_path / "attempts.txt"
    env = _env(
        tmp_path,
        STUB_SCENE=str(_scene(tmp_path)),
        STUB_BLENDER_MODE=mode,
        STUB_ATTEMPTS=str(counter),
    )
    done, _result = _call("run", request, tmp_path, env)
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
    model = _model(tmp_path)
    request = _request(tmp_path, "run", model=str(model))
    env = {**os.environ, "PATH": str(tmp_path / "empty")}
    env.pop("BLENDER_EXE", None)

    done, _result = _call("run", request, tmp_path, env)

    assert done.returncode != 0
    assert "blender not found" in done.stderr
    assert "BLENDER_EXE" in done.stderr
    assert "blender.path" in done.stderr


def test_a_windows_exe_gets_windows_paths_for_the_host(tmp_path: Path) -> None:
    """The conversion the lab's tools/blender.sh does, per path form."""
    assert runner._host_path("/mnt/c/lab/estudio.glb", True) == "C:\\lab\\estudio.glb"
    assert runner._host_path("/mnt/c/lab/out/estudio-photo.png", True) == (
        "C:\\lab\\out\\estudio-photo.png"
    )
    assert runner._host_path("/home/lab/estudio.glb", False) == "/home/lab/estudio.glb"
    # A path outside /mnt asks wslpath, exactly as the lab's script does.
    assert runner._drive_path("/mnt/c/x") == "C:\\x"
    assert runner._drive_path("/home/x") is None


def test_the_scene_receives_the_converted_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The importer and the renderer are handed the paths Blender can open."""
    trail = tmp_path / "trail.json"
    monkeypatch.setenv("STUB_SCENE", str(_scene(tmp_path)))
    monkeypatch.setenv("STUB_TRAIL", str(trail))
    monkeypatch.setenv("STUB_PNG_OUT", str(tmp_path / "photo.png"))
    monkeypatch.setattr(runner, "_on_windows", lambda: True)
    monkeypatch.setattr(runner, "_host_path", lambda value, windows: f"WIN:{value}")
    bpy = _import_stub_bpy(tmp_path)
    try:
        runner._render(
            bpy, "/mnt/c/lab/estudio.glb", "/mnt/c/lab/out/estudio-photo.png", {"model": "x"}
        )
    finally:
        sys.modules.pop("bpy", None)
    recorded = json.loads(trail.read_text(encoding="utf-8"))
    assert recorded["import_filepath"] == "WIN:/mnt/c/lab/estudio.glb"
    assert recorded["render"]["filepath"] == "WIN:/mnt/c/lab/out/estudio-photo.png"


def test_a_posix_path_becomes_a_unc_path_under_the_discovered_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blender reads ``/mnt/c`` natively; anything else goes under WSL's UNC root.

    The launcher converts ``--input`` with ``wslpath -w`` before the host
    launches, so the entry learns the root from the argument it was handed.
    """
    monkeypatch.setattr(runner, "_UNC_ROOT", [""])
    runner._remember_root("\\\\wsl.localhost\\Ubuntu\\tmp\\req.json")
    assert runner._UNC_ROOT[0] == "\\\\wsl.localhost\\Ubuntu"
    assert runner._host_path("/tmp/out/estudio-photo.png", True) == (
        "\\\\wsl.localhost\\Ubuntu\\tmp\\out\\estudio-photo.png"
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


def _import_stub_bpy(tmp_path: Path):
    folder = _stub_bpy(tmp_path)
    spec = importlib.util.spec_from_file_location("bpy", folder / "bpy.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bpy"] = module
    spec.loader.exec_module(module)
    return module


def test_verify_measures_the_png_header_without_blender(tmp_path: Path) -> None:
    """verify and preview answer under plain Python: no host binary needed."""
    good = tmp_path / "out" / "estudio-photo.png"
    good.parent.mkdir()
    PIL.Image.new("RGB", (WIDTH, HEIGHT), (10, 20, 30)).save(good)
    small = tmp_path / "out" / "small.png"
    PIL.Image.new("RGB", (32, 24), (1, 2, 3)).save(small)
    broken = tmp_path / "out" / "broken.png"
    broken.write_bytes(b"not a png")

    request = _request(tmp_path, "verify", model="estudio.glb")
    request["assets"] = [str(good), str(small), str(broken)]
    done, result_path = _call("verify", request, tmp_path, {**os.environ, "PATH": str(tmp_path)})

    assert done.returncode == 0, done.stdout + done.stderr
    verdicts = json.loads(result_path.read_text(encoding="utf-8"))["assets"]
    assert verdicts[0]["passed"] is True
    assert verdicts[0]["metrics"] == {"width": WIDTH, "height": HEIGHT}
    assert verdicts[0]["verifier"] == "png"
    assert verdicts[1]["passed"] is False
    assert verdicts[1]["metrics"] == {"width": 32, "height": 24}
    assert verdicts[2]["passed"] is False
    assert "error" in verdicts[2]["metrics"]


def test_preview_writes_the_image_schema(tmp_path: Path) -> None:
    """The preview file carries exactly the image kind's fields."""
    photo = tmp_path / "out" / "estudio-photo.png"
    photo.parent.mkdir()
    PIL.Image.new("RGB", (WIDTH, HEIGHT), (10, 20, 30)).save(photo)
    request = _request(
        tmp_path,
        "preview",
        model="estudio.glb",
        exposure=-0.6,
        rotation=0,
        assets=[str(photo)],
    )

    done, result_path = _call("preview", request, tmp_path, {**os.environ})

    assert done.returncode == 0, done.stdout + done.stderr
    entry = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert entry["file"] == "estudio-photo.png"
    assert entry["preview"] == "estudio-photo.png.preview.json"
    data = json.loads((photo.parent / entry["preview"]).read_text(encoding="utf-8"))
    assert set(data) == set(SCHEMA["required"])
    assert data["preview"] == 1
    assert data["kind"] == "image"
    assert data["name"] == "estudio-photo"
    assert (data["width"], data["height"]) == (WIDTH, HEIGHT)
    assert data["seed"] == 0
    assert data["prompt"].startswith("estudio · daylight architectural photo")
    assert len(data["summary"]) <= SUMMARY_MAX


def test_doctor_reports_the_blender_modules(tmp_path: Path) -> None:
    """doctor runs inside the host and names bpy, the glTF importer and Cycles."""
    request = _request(tmp_path, "doctor", depth="quick")
    env = _env(tmp_path, STUB_SCENE=str(_scene(tmp_path)))

    done, result_path = _call("doctor", request, tmp_path, env)

    assert done.returncode == 0, done.stdout + done.stderr
    checks = {check["name"]: check for check in json.loads(result_path.read_text())["checks"]}
    assert set(checks) == {"bpy", "gltf", "cycles"}
    assert all(check["ok"] for check in checks.values())
    assert "5.2.2 LTS" in checks["bpy"]["detail"]


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
