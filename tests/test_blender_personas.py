"""People for scale through a stub host: load order, the floor and the failures.

No real Blender and no network. A stub ``bpy`` records what the runner did: the
materials dressed before any library load, each person's root location, scale
and yaw after the collection was linked, and where the camera came in the
order. The prebuilt ``people.blend`` is a JSON catalog of collection names
and root counts, so a name the file does not hold and a collection that holds
two roots are both reproducible without the MPFB add-on.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"
RUNNER = PACKAGE / "runner.py"
#: The scene plane's drop under the model's lowest point, in metres.
FLOOR_DROP = 0.001
#: The lab's reference triple, from architecture-render / escena.py:45.
PEOPLE = [
    {"name": "luis", "x": 3.0, "y": 2.6, "rotation": 90},
    {"name": "ana", "x": 4.5, "y": 3.85, "rotation": 180},
    {"name": "sara", "x": 1.45, "y": -1.3, "rotation": 180},
]
CATALOG = {"luis": 1, "ana": 1, "sara": 1}
#: The lab's study pieces: names are the material prefixes.
PIECES = [("muros", (6000.0, 4500.0, 2600.0)), ("piso", (6300.0, 4800.0, 120.0))]

STUB_BPY = r'''
"""A stub bpy: the daylight scene, the library load and an ordered trail."""

import json
import math
import os
from pathlib import Path

TRAIL = {"events": []}


def event(name):
    TRAIL["events"].append(name)


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
    """Blender's ``rotation_euler``: a write is lost in ``QUATERNION`` mode.

    The MPFB collections arrive in QUATERNION mode, so a placement that writes
    the yaw without switching the mode first turns nobody.
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
    def __init__(self, name, kind="MESH", size=(1.0, 1.0, 1.0), rotation_mode="XYZ"):
        self.name = name
        self.type = kind
        self.parent = None
        self.is_person = False
        self.scale = [1.0, 1.0, 1.0]
        self.location = [0.0, 0.0, 0.0]
        self._rotation_mode = rotation_mode
        self._euler = [0.0, 0.0, 0.0]
        self.rotation_quaternion = [1.0, 0.0, 0.0, 0.0]
        self.data = MeshData(name) if kind == "MESH" else object()
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
    def matrix_world(self):
        scale = self.scale
        return [
            [scale[0], 0.0, 0.0, self.location[0]],
            [0.0, scale[1], 0.0, self.location[1]],
            [0.0, 0.0, scale[2], self.location[2]],
        ]

    def keyframe_insert(self, channel, frame=1):
        return None


class Camera:
    def __init__(self, name):
        self.name = name
        self.type = "PERSP"
        self.ortho_scale = 6.0
        self.lens = 50.0
        self.clip_end = 100.0


class Light:
    def __init__(self, name, kind="SUN"):
        self.name = name
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
        event(f"material:{name}")
        return Material(name)


class Cameras:
    def new(self, name):
        event("camera")
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
            return Object(name, kind="CAMERA")
        if isinstance(data, Light):
            return Object(name, kind="LIGHT")
        return Object(name)


class LibraryCollection:
    def __init__(self, name):
        self.name = name
        self.objects = []


def _catalog():
    source = os.environ.get("STUB_PEOPLE", "")
    return json.loads(Path(source).read_text()) if source else {}


def _library_collection(name, roots):
    """One loaded collection: ``roots`` parentless objects, each with a mesh."""
    collection = LibraryCollection(name)
    for index in range(roots):
        label = f"{name}-root-{index}" if roots > 1 else f"{name}-root"
        root = Object(label, size=(0.5, 0.3, 1.8), rotation_mode="QUATERNION")
        root.is_person = True
        child = Object(f"{name}-malla-{index}", size=(0.5, 0.3, 1.8))
        child.is_person = True
        child.parent = root
        collection.objects.extend([root, child])
    return collection


class LoadSource:
    def __init__(self, names):
        self.collections = list(names)


class LoadTarget:
    def __init__(self):
        self.collections = []


class LoadContext:
    """``bpy.data.libraries.load``: the names it holds, the loaded collections."""

    def __init__(self, blend):
        self.blend = blend
        self.source = LoadSource(_catalog())
        self.target = LoadTarget()

    def __enter__(self):
        return self.source, self.target

    def __exit__(self, kind, value, traceback):
        requested = list(self.target.collections or [])
        catalog = _catalog()
        self.target.collections = [
            _library_collection(name, catalog.get(name, 0)) for name in requested
        ]
        for name in requested:
            event(f"load:{name}")
        return False


class Libraries:
    def load(self, blend):
        return LoadContext(blend)


class DataBlocks:
    def __init__(self):
        self.materials = Materials()
        self.cameras = Cameras()
        self.lights = Lights()
        self.worlds = Worlds()
        self.objects = Objects()
        self.libraries = Libraries()


class SceneObjects:
    def __init__(self, scene):
        self.scene = scene

    def link(self, obj):
        self.scene.objects.append(obj)


class Children:
    def __init__(self, scene):
        self.scene = scene
        self.linked = []

    def link(self, collection):
        self.linked.append(collection)
        self.scene.objects.extend(collection.objects)


class SceneCollection:
    def __init__(self, scene):
        self.objects = SceneObjects(scene)
        self.children = Children(scene)


class ImageSettings:
    def __init__(self):
        self.media_type = ""
        self.file_format = ""


class FFmpeg:
    def __init__(self):
        self.format = ""
        self.codec = ""
        self.constant_rate_factor = ""


class RenderSettings:
    def __init__(self):
        self.resolution_x = 1920
        self.resolution_y = 1080
        self.filepath = ""
        self.engine = ""
        self.fps = 24
        self.use_file_extension = True
        self.image_settings = ImageSettings()
        self.ffmpeg = FFmpeg()


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


class Eevee:
    def __init__(self):
        self.taa_render_samples = 1
        self.use_raytracing = False
        self.ray_tracing_method = ""
        self.use_fast_gi = False
        self.use_shadows = False


class Scene:
    def __init__(self):
        self.objects = []
        self.collection = SceneCollection(self)
        self.render = RenderSettings()
        self.view_settings = ViewSettings()
        self.cycles = CyclesSettings()
        self.eevee = Eevee()
        self.camera = None
        self.world = None
        self.frame_start = 1
        self.frame_end = 1


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


class ImportOps:
    def gltf(self, filepath):
        TRAIL["import_filepath"] = filepath
        _load_pieces()


def _load_pieces():
    source = os.environ.get("STUB_SCENE", "")
    pieces = json.loads(Path(source).read_text())["pieces"] if source else []
    for piece in pieces:
        context.scene.objects.append(
            Object(piece["name"], size=tuple(piece.get("size", (1000.0, 1000.0, 1000.0))))
        )


class MeshOps:
    def primitive_plane_add(self, size=2.0, location=(0.0, 0.0, 0.0)):
        obj = Object("Plane", size=(size, size, 0.0))
        obj.location = list(location)
        context.scene.objects.append(obj)
        context.active_object = obj


def _person_trail(objects):
    people = [obj for obj in objects if getattr(obj, "is_person", False)]
    roots = {
        obj.name: {
            "location": list(obj.location),
            "scale": list(obj.scale),
            "yaw": obj._euler[2],
            "mode": obj.rotation_mode,
        }
        for obj in people
        if obj.parent is None
    }
    materials = {
        obj.name: [block.name for block in obj.data.materials]
        for obj in people
        if getattr(obj.data, "materials", None) is not None
    }
    return roots, materials


class RenderOps:
    def render(self, write_still=False, animation=False):
        scene = context.scene
        TRAIL["people"], TRAIL["person_materials"] = _person_trail(scene.objects)
        TRAIL["floor"] = next(
            (list(obj.location) for obj in scene.objects if obj.name == "suelo"), None
        )
        TRAIL["animation"] = bool(animation)
        TRAIL["camera_created"] = scene.camera is not None
        target = os.environ.get("STUB_TRAIL", "")
        if target:
            Path(target).write_text(json.dumps(TRAIL))


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


def _scene(tmp_path: Path) -> Path:
    path = tmp_path / "scene.json"
    entries = [{"name": name, "size": list(size)} for name, size in PIECES]
    path.write_text(json.dumps({"pieces": entries}), encoding="utf-8")
    return path


def _catalog(tmp_path: Path, names: dict[str, int]) -> Path:
    path = tmp_path / "people.json"
    path.write_text(json.dumps(names), encoding="utf-8")
    return path


def _model(tmp_path: Path) -> Path:
    path = tmp_path / "estudio.glb"
    path.write_bytes(b"glTF-stub")
    return path


def _blend(tmp_path: Path) -> Path:
    path = tmp_path / "people.blend"
    path.write_bytes(b"BLENDER-stub")
    return path


def _request(tmp_path: Path, verb: str, capability: str = "blender.photo", **inputs) -> dict:
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
        "assets": [],
    }


def _env(tmp_path: Path, catalog: dict[str, int] | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "BLENDER_EXE": str(_stub_blender(tmp_path)),
        "STUB_BPY": str(_stub_bpy(tmp_path)),
        "STUB_SCENE": str(_scene(tmp_path)),
        "STUB_TRAIL": str(tmp_path / "trail.json"),
        "STUB_PEOPLE": str(_catalog(tmp_path, CATALOG if catalog is None else catalog)),
    }
    env.pop("PYTHONPATH", None)
    return env


def _call(verb: str, request: dict, tmp_path: Path, env: dict[str, str]):
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


def _events(trail: dict) -> list[str]:
    return [str(entry) for entry in trail["events"]]


def test_people_load_after_dress_and_stand_on_the_floor(tmp_path: Path) -> None:
    """The prebuilt collections load after dressing and stand at (x, y, floor)."""
    model = _model(tmp_path)
    request = _request(
        tmp_path,
        "run",
        model=str(model),
        **{"people-blend": str(_blend(tmp_path)), "people": PEOPLE},
    )

    done, result_path = _call("run", request, tmp_path, _env(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    assert result_path.exists()
    trail = _trail(tmp_path)
    events = _events(trail)
    first_load = min(index for index, name in enumerate(events) if name.startswith("load:"))
    last_dress = max(index for index, name in enumerate(events) if name.startswith("material:"))
    assert last_dress < first_load
    floor_z = trail["floor"][2]
    for placement in PEOPLE:
        root = trail["people"][f"{placement['name']}-root"]
        assert root["location"][:2] == [placement["x"], placement["y"]]
        assert root["location"][2] == pytest.approx(floor_z)
        assert root["scale"] == [1.0, 1.0, 1.0]
        assert root["yaw"] == pytest.approx(math.radians(placement["rotation"]))
        assert root["mode"] == "XYZ"
    # Nobody was dressed: the people were not part of the scene at dress time.
    assert all(not blocks for blocks in trail["person_materials"].values())


def test_the_unknown_name_lists_the_collections_the_blend_holds(tmp_path: Path) -> None:
    """A name the blend does not hold fails loudly, naming what it has."""
    model = _model(tmp_path)
    blend = _blend(tmp_path)
    request = _request(
        tmp_path,
        "run",
        model=str(model),
        **{"people-blend": str(blend), "people": [{"name": "nadie", "x": 1, "y": 2}]},
    )

    done, result_path = _call("run", request, tmp_path, _env(tmp_path))

    assert done.returncode != 0
    assert f"nadie is not a collection in {blend}" in done.stderr
    assert "(has: ['ana', 'luis', 'sara'])" in done.stderr
    assert not result_path.exists()
    assert not (tmp_path / "out" / "estudio-photo.png").exists()


def test_a_collection_with_two_roots_fails_loudly(tmp_path: Path) -> None:
    """Moving one root is the only safe placement, so two roots is a failure."""
    model = _model(tmp_path)
    request = _request(
        tmp_path,
        "run",
        model=str(model),
        **{
            "people-blend": str(_blend(tmp_path)),
            "people": [{"name": "dos", "x": 0, "y": 0}],
        },
    )

    done, result_path = _call("run", request, tmp_path, _env(tmp_path, {"dos": 2}))

    assert done.returncode != 0
    assert "dos: expected one root object, found 2" in done.stderr
    assert not result_path.exists()
    assert not (tmp_path / "out" / "estudio-photo.png").exists()


def test_an_empty_list_never_touches_the_missing_blend(tmp_path: Path) -> None:
    """Nobody is placed, so a blend that does not exist is never opened."""
    model = _model(tmp_path)
    request = _request(
        tmp_path,
        "run",
        model=str(model),
        **{"people-blend": str(tmp_path / "nada.blend"), "people": []},
    )

    done, result_path = _call("run", request, tmp_path, _env(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    assert result_path.exists()
    assert not [name for name in _events(_trail(tmp_path)) if name.startswith("load:")]


def test_the_tour_loads_people_before_it_builds_the_camera(tmp_path: Path) -> None:
    """The tour stands the same people, between the dressing and the camera."""
    model = _model(tmp_path)
    request = _request(
        tmp_path,
        "run",
        capability="blender.tour",
        model=str(model),
        seconds=2,
        fps=12,
        **{"people-blend": str(_blend(tmp_path)), "people": PEOPLE},
    )

    done, result_path = _call("run", request, tmp_path, _env(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    assert result_path.exists()
    trail = _trail(tmp_path)
    events = _events(trail)
    first_load = min(index for index, name in enumerate(events) if name.startswith("load:"))
    last_dress = max(index for index, name in enumerate(events) if name.startswith("material:"))
    assert last_dress < first_load < events.index("camera")
    assert trail["animation"] is True
    for placement in PEOPLE:
        root = trail["people"][f"{placement['name']}-root"]
        assert root["location"][:2] == [placement["x"], placement["y"]]
        assert root["location"][2] == pytest.approx(trail["floor"][2])
        assert root["scale"] == [1.0, 1.0, 1.0]
    assert (
        "people-blend" in json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]["params"]
    )
