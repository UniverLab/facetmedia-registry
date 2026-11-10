"""The dressed scene: fetched sky, textures and plants in foto and recorrido.

No real Blender, no network and no facet installed. A stub ``bpy`` answers
the calls the dressing path makes — the HDRI sky, the box-projected texture
materials with their bump, and the anchored plant imports — and records a
trail of what reached the scene: which world lights it, which images loaded
in which colour space, and where each plant anchor stands.

The failure paths need no stub at all: a repeated ``prefijo`` and a missing
fetched file raise before anything renders, and the message names the
``blender.assets`` entry that fetches the file.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"
RUNNER = PACKAGE / "runner.py"
#: The Poly Haven root the scene reads is ``<home>/models/blender/polyhaven``.
MODELS = Path("home") / "models" / "direct"
#: The bump the lab's texture material hard-codes beside the roughness.
BUMP = 0.15
#: The study pieces: names are the material prefixes.
PIECES = [
    ("muros", (6000.0, 4500.0, 2600.0)),
    ("piso", (6300.0, 4800.0, 120.0)),
    ("vidrio-1", (1200.0, 20.0, 1200.0)),
]

STUB_BPY = r'''
"""A stub bpy: the dressed scene — sky, textures, plants — and its trail."""

import json
import math
import os
from pathlib import Path

import PIL.Image

TRAIL = {}
ALL_MATERIALS = []
WORLDS = []
REGISTRY = []


class _Matrix(list):
    """A 3x4 row list the anchor can invert; values are never rendered."""

    def inverted(self):
        return _Matrix([
            [1.0, 0.0, 0.0, -self[0][3]],
            [0.0, 1.0, 0.0, -self[1][3]],
            [0.0, 0.0, 1.0, -self[2][3]],
        ])


class Input:
    def __init__(self, value=None):
        self.default_value = value


class Node:
    def __init__(self, name):
        self.name = name
        self.inputs = {key: Input() for key in (
            "Base Color", "Metallic", "Roughness", "Transmission Weight", "IOR",
            "Color", "Strength", "Vector", "Scale", "Rotation",
            "Hue", "Saturation", "Value", "Height", "Normal",
            "Generated", "Position")}
        self.inputs["Scale"].default_value = [1.0, 1.0, 1.0]
        self.inputs["Rotation"].default_value = [0.0, 0.0, 0.0]
        self.outputs = {key: object() for key in (
            "Color", "Vector", "Normal", "Generated", "Position")}
        self.image = None
        self.projection = ""
        self.projection_blend = 0.0
        self.sun_elevation = 0.0
        self.sun_rotation = 0.0


class Nodes(dict):
    def new(self, kind):
        node = Node(kind)
        self.created.append(node)
        return node


class Links:
    def new(self, source, target):
        return None


class NodeTree:
    def __init__(self):
        self.nodes = Nodes({
            "Principled BSDF": Node("Principled BSDF"),
            "Background": Node("Background"),
        })
        self.nodes.created = []
        self.links = Links()


class Material:
    def __init__(self, name):
        self.name = name
        self.use_nodes = False
        self.node_tree = NodeTree()


class ImageColorspace:
    def __init__(self):
        self.name = ""


class Image:
    def __init__(self, path):
        self.filepath = path
        self.colorspace_settings = ImageColorspace()


class Images:
    def __init__(self):
        self.loaded = []

    def load(self, path, check_existing=False):
        image = Image(path)
        self.loaded.append(image)
        return image


class MeshData:
    def __init__(self, name):
        self.name = name
        self.materials = []
        self.baked = False


class Euler:
    """Blender's ``rotation_euler``: the dressing placements use XYZ mode."""

    def __init__(self, owner):
        self._owner = owner

    def __getitem__(self, index):
        return self._owner._euler[index]

    def __setitem__(self, index, value):
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
        self.matrix_parent_inverse = None
        self.scale = [1.0, 1.0, 1.0]
        self.location = list(location)
        self.rotation_mode = rotation_mode
        self._euler = [0.0, 0.0, 0.0]
        self.selected = False
        if data is not None:
            self.data = data
        elif kind == "MESH":
            self.data = MeshData(name)
        else:
            self.data = object()
        half = [side / 2 for side in size]
        self.bound_box = [
            [x, y, z]
            for x in (-half[0], half[0])
            for y in (-half[1], half[1])
            for z in (-half[2], half[2])
        ]

    @property
    def rotation_euler(self):
        return Euler(self)

    @rotation_euler.setter
    def rotation_euler(self, value):
        self._euler = [float(item) for item in value]

    def select_set(self, value):
        self.selected = value

    @property
    def matrix_world(self):
        location = self.location
        return _Matrix([
            [1.0, 0.0, 0.0, location[0]],
            [0.0, 1.0, 0.0, location[1]],
            [0.0, 0.0, 1.0, location[2]],
        ])

    def keyframe_insert(self, channel, frame=1):
        frames = TRAIL.setdefault("keyframes", {}).setdefault(channel, [])
        frames.append(frame)


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
        self.use_sun_shadow = False
        self.node_tree = NodeTree()


class Materials:
    def new(self, name):
        TRAIL.setdefault("calls", []).append(f"material:{name}")
        material = Material(name)
        ALL_MATERIALS.append(material)
        return material


class Cameras:
    def new(self, name):
        return Camera(name)


class Lights:
    def new(self, name, kind="SUN"):
        return Light(name, kind)


class Worlds:
    def new(self, name):
        world = World(name)
        WORLDS.append(world)
        return world


class DataObjects:
    """bpy.data.objects: every object, so a plant import diffs before/after."""

    def __iter__(self):
        return iter(REGISTRY)

    def __contains__(self, item):
        return item in REGISTRY

    def new(self, name, data):
        if isinstance(data, Camera):
            obj = Object(name, kind="CAMERA", data=data)
        elif isinstance(data, Light):
            obj = Object(name, kind="LIGHT", data=data)
        else:
            obj = Object(name, kind="EMPTY")
        REGISTRY.append(obj)
        return obj


class DataBlocks:
    def __init__(self):
        self.materials = Materials()
        self.cameras = Cameras()
        self.lights = Lights()
        self.worlds = Worlds()
        self.objects = DataObjects()
        self.images = Images()


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


class EeveeSettings:
    def __init__(self):
        self.taa_render_samples = 1
        self.use_raytracing = False
        self.ray_tracing_method = ""
        self.use_fast_gi = False
        self.use_shadows = False


class ImageSettings:
    def __init__(self):
        self.media_type = ""
        self.file_format = ""


class FfmpegSettings:
    def __init__(self):
        self.format = ""
        self.codec = ""
        self.constant_rate_factor = ""


class Scene:
    def __init__(self):
        self.objects = []
        self.collection = Collection(self)
        self.render = RenderSettings()
        self.render.image_settings = ImageSettings()
        self.render.ffmpeg = FfmpegSettings()
        self.render.fps = 24
        self.render.use_file_extension = True
        self.view_settings = ViewSettings()
        self.cycles = CyclesSettings()
        self.eevee = EeveeSettings()
        self.camera = None
        self.world = None
        self.frame_start = 1
        self.frame_end = 1


class CyclesPrefs:
    def __init__(self):
        self.compute_device_type = "NONE"
        self.devices = []

    def get_devices(self):
        return None


class Addon:
    def __init__(self):
        self.preferences = CyclesPrefs()


class Preferences:
    def __init__(self):
        self.addons = {"cycles": Addon()}


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
        self.preferences = Preferences()
        self.active_object = None
        self.view_layer = ViewLayer()


class App:
    version_string = "5.2.2 LTS"


class WmOps:
    def read_factory_settings(self, use_empty=False):
        global context
        context.scene = Scene()
        del REGISTRY[:]
        del ALL_MATERIALS[:]
        del WORLDS[:]


class ImportOps:
    def gltf(self, filepath):
        if str(filepath).endswith(".gltf"):
            stem = Path(str(filepath)).stem
            mesh = Object(
                f"{stem}-mesh",
                size=(500.0, 500.0, 1800.0),
                location=(0.0, 0.0, 900.0),
            )
            context.scene.objects.append(mesh)
            REGISTRY.append(mesh)
            return
        TRAIL["import_filepath"] = filepath
        _load_pieces()


def _load_pieces():
    source = os.environ.get("STUB_SCENE", "")
    pieces = json.loads(Path(source).read_text())["pieces"] if source else []
    root = Object("estudio", kind="EMPTY")
    root.rotation_euler = [-math.pi / 2, 0.0, 0.0]
    context.scene.objects.append(root)
    REGISTRY.append(root)
    for piece in pieces:
        obj = Object(piece["name"], size=tuple(piece.get("size", (1000,) * 3)))
        obj.parent = root
        context.scene.objects.append(obj)
        REGISTRY.append(obj)


class MeshOps:
    def primitive_plane_add(self, size=2.0, location=(0.0, 0.0, 0.0)):
        obj = Object("Plane", size=(size, size, 0.0), location=location)
        context.scene.objects.append(obj)
        REGISTRY.append(obj)
        context.active_object = obj


class RenderOps:
    def render(self, write_still=False, animation=False):
        scene = context.scene
        TRAIL["render_calls"] = [{"write_still": write_still, "animation": animation}]
        meshes = [obj for obj in scene.objects if obj.type == "MESH"]
        TRAIL["materials"] = {
            obj.name: obj.data.materials[0].name for obj in meshes if obj.data.materials
        }
        TRAIL["nodes"] = {
            material.name: [node.name for node in material.node_tree.nodes.created]
            for material in ALL_MATERIALS
        }
        TRAIL["tile"] = {
            material.name: _mapping_scale(material) for material in ALL_MATERIALS
        }
        TRAIL["tint"] = {
            material.name: _tint(material) for material in ALL_MATERIALS
        }
        TRAIL["bump"] = {
            material.name: _bump_strength(material) for material in ALL_MATERIALS
        }
        TRAIL["flat"] = {
            material.name: _flat_colour(material) for material in ALL_MATERIALS
        }
        TRAIL["images"] = [
            [image.filepath, image.colorspace_settings.name]
            for image in data.images.loaded
        ]
        TRAIL["nor_gl"] = [
            path for path, _ in TRAIL["images"] if path.endswith("nor_gl.jpg")
        ]
        TRAIL["sun"] = {
            obj.name: obj.data.energy for obj in scene.objects if obj.type == "LIGHT"
        }
        TRAIL["anchors"] = {
            obj.name: {"location": list(obj.location), "yaw": obj._euler[2]}
            for obj in scene.objects
            if obj.name.endswith("-ancla")
        }
        TRAIL["floor"] = next(
            (list(obj.location) for obj in scene.objects if obj.name == "suelo"), None
        )
        TRAIL["sky"] = _sky(scene)
        TRAIL["camera"] = None if scene.camera is None else scene.camera.name
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
        if write_still:
            PIL.Image.new(
                "RGB", (scene.render.resolution_x, scene.render.resolution_y), (20, 40, 60)
            ).save(str(scene.render.filepath))
        target = os.environ.get("STUB_TRAIL", "")
        if target:
            Path(target).write_text(json.dumps(TRAIL, default=list))


def _created(material):
    return list(material.node_tree.nodes.created)


def _mapping_scale(material):
    mapping = next((n for n in _created(material) if n.name == "ShaderNodeMapping"), None)
    return None if mapping is None else list(mapping.inputs["Scale"].default_value)


def _tint(material):
    tint = next(
        (n for n in _created(material) if n.name == "ShaderNodeHueSaturation"), None
    )
    if tint is None:
        return None
    return [tint.inputs[key].default_value for key in ("Hue", "Saturation", "Value")]


def _bump_strength(material):
    bump = next((n for n in _created(material) if n.name == "ShaderNodeBump"), None)
    return None if bump is None else bump.inputs["Strength"].default_value


def _flat_colour(material):
    nodes = material.node_tree.nodes
    if _created(material):
        return None
    return list(nodes["Principled BSDF"].inputs["Base Color"].default_value)


def _sky(scene):
    world = scene.world
    if world is None:
        return None
    created = list(world.node_tree.nodes.created)
    mapping = next((n for n in created if n.name == "ShaderNodeMapping"), None)
    environment = next(
        (n for n in created if n.name == "ShaderNodeTexEnvironment"), None
    )
    background = world.node_tree.nodes["Background"]
    return {
        "world": world.name,
        "kinds": sorted({node.name for node in created}),
        "rotation": (
            None
            if mapping is None
            else mapping.inputs["Rotation"].default_value[2]
        ),
        "image": (
            None
            if environment is None or environment.image is None
            else environment.image.filepath
        ),
        "strength": background.inputs["Strength"].default_value,
        "sun_shadow": world.use_sun_shadow,
    }


class ObjectOps:
    def parent_clear(self, **kwargs):
        assert kwargs == {"type": "CLEAR_KEEP_TRANSFORM"}
        obj = context.view_layer.objects.active
        TRAIL.setdefault("calls", []).append(f"parent_clear:{obj.name}")
        obj.parent = None

    def transform_apply(self, location=False, rotation=True, scale=True):
        assert location is False and rotation is True and scale is True
        obj = context.view_layer.objects.active
        TRAIL.setdefault("calls", []).append(f"bake:{obj.name}")
        obj.scale = [1.0, 1.0, 1.0]
        obj._euler = [0.0, 0.0, 0.0]
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


def _load_escena():
    """The dressing helpers, loaded without Blender: escena needs no bpy."""
    spec = importlib.util.spec_from_file_location("blender_escena", PACKAGE / "escena.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


escena = _load_escena()


def test_repeated_prefijo_fails_with_the_exact_message() -> None:
    """Two items with the same prefijo fail before anything renders."""
    with pytest.raises(RuntimeError) as caught:
        escena.texturas(
            {"texturas": [{"prefijo": "suelo", "id": "a"}, {"prefijo": "suelo", "id": "b"}]}
        )
    assert str(caught.value) == "texturas: prefijo repetido: suelo"


def test_missing_texture_names_the_assets_entry() -> None:
    """A texture id that was never fetched names its diff.jpg and the 2k entry."""
    with pytest.raises(RuntimeError) as caught:
        escena.textured(None, "suelo", {"prefijo": "suelo", "id": "leafy"}, "/no/root")
    assert str(caught.value) == (
        "missing leafy/diff.jpg: fetch it with blender.assets "
        '[[inputs.assets]] with id = "leafy" and res = "2k"'
    )


def test_missing_model_names_the_assets_entry() -> None:
    """A plant id that was never fetched names its gltf and the 1k entry."""
    with pytest.raises(RuntimeError) as caught:
        escena.place_plants(None, None, [{"id": "shrub_02", "x": 1.0, "y": 2.0}], "/no/root", 0.0)
    assert str(caught.value) == (
        "missing shrub_02/shrub_02.gltf: fetch it with blender.assets "
        '[[inputs.assets]] with id = "shrub_02" and res = "1k"'
    )


def test_missing_sky_names_the_assets_entry() -> None:
    """A sky id that was never fetched names its sky.hdr and the 2k entry."""
    with pytest.raises(RuntimeError) as caught:
        escena.sky_hdri(None, None, {"id": "klopp"}, "/no/root")
    assert str(caught.value) == (
        "missing klopp/sky.hdr: fetch it with blender.assets "
        '[[inputs.assets]] with id = "klopp" and res = "2k"'
    )


def test_cielo_item_reads_only_the_first_item() -> None:
    """The runner reads the first cielo item and ignores the rest, like camera."""
    params = {"cielo": [{"id": "first", "giro": 90}, {"id": "second", "giro": 10}]}
    assert escena.cielo_item(params) == {"id": "first", "giro": 90}
    assert escena.cielo_item({}) == {}
    assert escena.cielo_item({"cielo": []}) == {}
    assert escena.cielo_item({"cielo": "klopp"}) == {}


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


def _polyhaven(tmp_path: Path) -> Path:
    """The fetched files the dressing reads: sky, two texture maps, one model."""
    root = tmp_path / "home" / "models" / "blender" / "polyhaven"
    (root / "kloppenheim_06_puresky").mkdir(parents=True)
    (root / "kloppenheim_06_puresky" / "sky.hdr").write_bytes(b"HDR-stub")
    (root / "aerial_grass_rock").mkdir(parents=True)
    (root / "aerial_grass_rock" / "diff.jpg").write_bytes(b"diff-stub")
    (root / "aerial_grass_rock" / "rough.jpg").write_bytes(b"rough-stub")
    (root / "shrub_02").mkdir(parents=True)
    (root / "shrub_02" / "shrub_02.gltf").write_bytes(b"gltf-stub")
    return root


def _request(tmp_path: Path, capability: str, **inputs) -> dict:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return {
        "protocol": 1,
        "verb": "run",
        "capability": capability,
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(tmp_path),
        "models": {},
        "assets": [],
    }


def _dressing_inputs(model: str) -> dict:
    return {
        "model": model,
        "cielo": [{"id": "kloppenheim_06_puresky", "giro": 200, "fuerza": 1.0}],
        "texturas": [
            {
                "prefijo": "suelo",
                "id": "aerial_grass_rock",
                "lado": 3.0,
                "matiz": 0.5,
                "saturacion": 1.0,
                "valor": 0.9,
            }
        ],
        "plantas": [{"id": "shrub_02", "x": 7.4, "y": 2.25, "giro": 90}],
    }


def _call(runner, tmp_path: Path, request: dict, monkeypatch) -> dict:
    monkeypatch.setenv("STUB_SCENE", str(_scene(tmp_path)))
    monkeypatch.setenv("STUB_TRAIL", str(tmp_path / "trail.json"))
    monkeypatch.setenv("FACET_MODELS", str(tmp_path / MODELS))
    _polyhaven(tmp_path)
    _stub_bpy()
    input_path = tmp_path / "run-request.json"
    result_path = tmp_path / "run-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    try:
        runner.main(["run", "--input", str(input_path), "--result", str(result_path)])
    finally:
        sys.modules.pop("bpy", None)
    return json.loads(result_path.read_text(encoding="utf-8"))


def _trail(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "trail.json").read_text(encoding="utf-8"))


def test_foto_dresses_sky_textures_and_plants(tmp_path: Path, runner, monkeypatch) -> None:
    """Every dressing input reaches the scene builder: sky, maps and anchor."""
    model = _model(tmp_path)
    request = _request(tmp_path, "blender.foto", **_dressing_inputs(str(model)))

    result = _call(runner, tmp_path, request, monkeypatch)

    assert result["assets"][0]["file"] == "estudio-foto.png"
    trail = _trail(tmp_path)
    sky = trail["sky"]
    assert sky["world"] == "cielo"
    assert sky["rotation"] == pytest.approx(math.radians(200))
    assert sky["strength"] == 1.0
    assert sky["image"].endswith("kloppenheim_06_puresky/sky.hdr")
    assert sky["sun_shadow"] is True
    assert {"ShaderNodeTexCoord", "ShaderNodeMapping", "ShaderNodeTexEnvironment"} <= set(
        sky["kinds"]
    )
    assert trail["sun"] == {}
    nodes = trail["nodes"]["suelo"]
    for kind in (
        "ShaderNodeTexImage",
        "ShaderNodeMapping",
        "ShaderNodeHueSaturation",
        "ShaderNodeBump",
        "ShaderNodeNewGeometry",
    ):
        assert kind in nodes
    assert trail["tile"]["suelo"] == pytest.approx([1 / 3.0] * 3)
    assert trail["tint"]["suelo"] == [0.5, 1.0, 0.9]
    assert trail["bump"]["suelo"] == BUMP
    assert trail["nor_gl"] == []
    by_name = {Path(path).name: space for path, space in trail["images"]}
    assert by_name == {"diff.jpg": "sRGB", "rough.jpg": "Non-Color", "sky.hdr": ""}
    anchor = trail["anchors"]["shrub_02-ancla"]
    assert anchor["location"][:2] == [7.4, 2.25]
    assert anchor["location"][2] == pytest.approx(trail["floor"][2])
    assert anchor["yaw"] == pytest.approx(math.radians(90))
    assert trail["materials"]["suelo"] == "suelo"
    assert trail["flat"]["muros"] == [0.92, 0.91, 0.88, 1]


def test_cielo_only_adds_no_sun_lamp(tmp_path: Path, runner, monkeypatch) -> None:
    """A sky without textures or plants still replaces the procedural sun."""
    model = _model(tmp_path)
    request = _request(
        tmp_path, "blender.foto", model=str(model), cielo=[{"id": "kloppenheim_06_puresky"}]
    )

    _call(runner, tmp_path, request, monkeypatch)

    trail = _trail(tmp_path)
    assert trail["sky"]["rotation"] == pytest.approx(math.radians(200))
    assert trail["sky"]["strength"] == 1.0
    assert trail["sky"]["sun_shadow"] is True
    assert trail["sun"] == {}
    assert trail["anchors"] == {}
    assert trail["flat"]["suelo"] == [0.80, 0.80, 0.78, 1]


def test_recorrido_dresses_the_same_scene(tmp_path: Path, runner, monkeypatch) -> None:
    """The tour reads the same three inputs through the same scene builder."""
    model = _model(tmp_path)
    inputs = _dressing_inputs(str(model)) | {"seconds": 2, "fps": 12}
    request = _request(tmp_path, "blender.recorrido", **inputs)

    result = _call(runner, tmp_path, request, monkeypatch)

    assert result["assets"][0]["file"] == "estudio-recorrido.mp4"
    trail = _trail(tmp_path)
    assert trail["render_calls"] == [{"write_still": False, "animation": True}]
    assert trail["camera"] == "camara"
    assert trail["keyframes"]["location"] == list(range(1, 25))
    assert trail["sky"]["sun_shadow"] is True
    assert trail["sky"]["rotation"] == pytest.approx(math.radians(200))
    assert trail["sun"] == {}
    assert "ShaderNodeTexImage" in trail["nodes"]["suelo"]
    assert trail["anchors"]["shrub_02-ancla"]["location"][:2] == [7.4, 2.25]


def test_missing_texture_fails_the_run_with_the_exact_message(
    tmp_path: Path, runner, monkeypatch
) -> None:
    """A texturas id with no fetched folder fails the run, naming the entry."""
    model = _model(tmp_path)
    request = _request(
        tmp_path,
        "blender.foto",
        model=str(model),
        texturas=[{"prefijo": "suelo", "id": "leafy"}],
    )

    with pytest.raises(RuntimeError) as caught:
        _call(runner, tmp_path, request, monkeypatch)

    assert str(caught.value) == (
        "missing leafy/diff.jpg: fetch it with blender.assets "
        '[[inputs.assets]] with id = "leafy" and res = "2k"'
    )


def test_foto_bakes_before_materials(tmp_path: Path, runner, monkeypatch) -> None:
    """The foto run bakes every piece before any material is created."""
    model = _model(tmp_path)
    request = _request(tmp_path, "blender.foto", model=str(model))

    _call(runner, tmp_path, request, monkeypatch)

    trail = _trail(tmp_path)
    calls = trail["calls"]
    bakes = [call for call in calls if call.split(":")[0] in {"parent_clear", "bake"}]
    materials = [call for call in calls if call.startswith("material:")]
    assert bakes == [
        "parent_clear:muros",
        "bake:muros",
        "parent_clear:piso",
        "bake:piso",
        "parent_clear:vidrio-1",
        "bake:vidrio-1",
    ]
    assert max(calls.index(call) for call in bakes) < min(calls.index(call) for call in materials)
    assert all(parent is None for parent in trail["parents"].values())
    assert trail["baked"] == ["muros", "piso", "vidrio-1"]
