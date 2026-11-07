"""The blender package runner: a daylight architectural photo of a CAD model.

facet drives a ``host-app`` package through the host binary, so this entry is
Blender's script: ``blender -b --factory-startup --python-exit-code 1 --python
runner.py -- <verb> --input <request> --result <result>``. Inside Blender the
four verbs use ``bpy``: ``run`` imports the CadQuery glTF (millimetres, one
element per piece carrying its name), scales it to metres, assigns one
Principled material per piece by name prefix — a piece left without one fails
the run loudly — builds the sun plus sky wash, the axonometric camera and the
Cycles GPU settings (OPTIX, 128 samples, denoise, exposure -0.6 under AgX
Medium High Contrast), and writes ``<model>-foto.png`` at 1600x1000.
``verify`` measures the PNG header, ``preview`` writes the image kind's
preview file, and ``doctor`` reports the Blender-side modules.

Started with plain Python — ``python runner.py run ...``, as the tests and a
manual paste-back do — the same entry is the launcher the lab's
``tools/blender.sh`` is: it resolves the host Blender (``BLENDER_EXE``, then
``PATH``), converts paths to Windows form when the binary is a ``.exe`` under
WSL, drives it with the lab's flags, and retries once only on a WSL interop
failure (``UtilAcceptVsock``); anything else fails with the tail of its output.
``verify`` and ``preview`` need no Blender and answer directly.
"""

from __future__ import annotations

import importlib
import json
import math
import os
import posixpath
import re
import struct
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

#: The image the daylight recipe produces, per the approved lab render.
RENDER_WIDTH = 1600
RENDER_HEIGHT = 1000
#: Cycles on the GPU: 128 samples with denoise is the lab's 8-10 s recipe.
SAMPLES = 128
#: glTF arrives in millimetres; Blender works in metres.
SCALE = 0.001
#: The view transform that keeps sun plus sky from washing the colours out.
LOOK = "AgX - Medium High Contrast"
DEFAULT_EXPOSURE = -0.6
#: The lab's axonometric view: azimut and elevacion in degrees, escala in metres.
DEFAULT_CAMERA = {"azimut": -40.0, "elevacion": 48.0, "escala": 11.5}
#: The sun the approved render uses, and the sky wash strength beside it.
SUN = {"azimut": 210.0, "elevacion": 32.0, "fuerza": 3.0}
SKY_STRENGTH = 0.2
SUN_ANGLE_DEG = 2.0
#: How far the orthographic camera sits from the model, in frame widths.
CAMERA_DISTANCE = 2.5
#: The outside floor that receives the shadows, in metres.
FLOOR_SIZE = 60.0
FLOOR_DROP = 0.001
#: Piece-name prefix -> (base colour, roughness, transmission).
MATERIALS = {
    "muros": ((0.92, 0.91, 0.88), 0.9, 0.0),
    "piso": ((0.50, 0.34, 0.21), 0.45, 0.0),
    "vidrio": ((0.85, 0.93, 1.0), 0.02, 1.0),
    "cama": ((0.23, 0.33, 0.52), 0.85, 0.0),
    "almohada": ((0.95, 0.95, 0.94), 0.8, 0.0),
    "mesa": ((0.40, 0.26, 0.15), 0.4, 0.0),
    "sillas": ((0.90, 0.40, 0.18), 0.55, 0.0),
    "suelo": ((0.80, 0.80, 0.78), 0.95, 0.0),
}
#: What the run appends to the model's stem: ``estudio.glb`` -> ``estudio-foto.png``.
ASSET_SUFFIX = "-foto"
#: Cycles' sampling seed: one scene gives the same photo every run.
SEED = 0
#: The lab's headless flags; the exit-code flag must precede ``--python``.
HOST_FLAGS = ("-b", "--factory-startup", "--python-exit-code", "1", "--python")
#: The verbs that need Blender; verify and preview read the PNG directly.
NEEDS_BLENDER = ("run", "doctor")
#: The only failure worth a second launch: WSL interop failing the first accept.
INTEROP_MARKER = "UtilAcceptVsock"
ATTEMPTS = 2
TAIL_CHARS = 2000
WSLPATH_TIMEOUT_S = 10.0
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: A PNG header is its 8-byte signature plus a 16-byte IHDR chunk.
PNG_HEADER_BYTES = 24
PNG_SIZE_OFFSET = (16, 24)
#: ``("/", "mnt", "<drive>")``: the WSL mount point's own components.
MOUNT_PARTS = 3
#: ``("", "", "server", "share")``: a UNC path's own leading components.
UNC_PARTS = 4
#: The UNC mount point of WSL's filesystem, discovered from the request's path.
_UNC_ROOT: list[str] = [""]
#: ``C:\`` or ``C:/``: a path the Windows build already understands.
DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")
UNSAFE_NAME = re.compile(r"[^a-z0-9-]+")

#: One material recipe: base colour, roughness and glass transmission.
Recipe = tuple[tuple[float, float, float], float, float]


def main(argv: list[str] | None = None) -> int:
    """Run the verb named on the command line, inside Blender or beside it."""
    verb, input_path, result_path = _parse_argv(sys.argv[1:] if argv is None else argv)
    request = json.loads(Path(input_path).read_text(encoding="utf-8"))
    bpy = _bpy()
    if bpy is None and verb in NEEDS_BLENDER:
        _launch_host(verb, input_path, result_path)
        return 0
    _remember_root(str(input_path))
    result = VERBS[verb](bpy, request)
    Path(result_path).write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


def _bpy() -> Any:
    """Blender's module when this entry runs inside it, else ``None``."""
    try:
        return importlib.import_module("bpy")
    except ImportError:
        return None


def _parse_argv(argv: list[str]) -> tuple[str, Path, Path]:
    """``(verb, request, result)`` from ``[--] VERB --input P --result P``.

    Blender keeps its own flags in ``sys.argv`` and passes what follows ``--``
    through, so the marker is skipped when present.
    """
    rest = list(argv)
    if "--" in rest:
        rest = rest[rest.index("--") + 1 :]
    if not rest:
        raise ValueError("usage: [--] VERB --input REQUEST --result RESULT")
    verb, *tokens = rest
    values: dict[str, str] = {}
    position = 0
    while position < len(tokens):
        flag = tokens[position]
        if flag not in {"--input", "--result"} or position + 1 >= len(tokens):
            raise ValueError(f"usage: [--] VERB --input REQUEST --result RESULT (got {flag!r})")
        values[flag] = tokens[position + 1]
        position += 2
    missing = [flag for flag in ("--input", "--result") if flag not in values]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    return verb, Path(values["--input"]), Path(values["--result"])


# --- the four verbs.


def _run(bpy: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Render one photo and report it as the image asset it is.

    Paths stay POSIX strings: facet resolves them on WSL, and ``pathlib``
    inside the Windows build of Blender would rewrite ``/mnt/c/...`` before the
    host conversion ever sees it.
    """
    params = dict(request.get("inputs") or {})
    model = str(params["model"])
    name = _asset_name(model)
    destination = f"{str(request['out_dir']).rstrip('/')}/{name}.png"
    _render(bpy, model, destination, params)
    return {
        "tool": {"name": "blender", "version": _version(bpy)},
        "assets": [
            {
                "file": f"{name}.png",
                "name": name,
                "kind": "image",
                "mime": "image/png",
                "properties": {
                    "width": RENDER_WIDTH,
                    "height": RENDER_HEIGHT,
                    "samples": SAMPLES,
                    "exposure": _exposure(params),
                    "giro": _giro(params),
                },
                "params": params,
                "seed": SEED,
                "inputs": [model],
            }
        ],
    }


def _verify(bpy: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Measure each PNG's header against the recipe's size."""
    thresholds = {"width": RENDER_WIDTH, "height": RENDER_HEIGHT}
    paths = [str(item) for item in request.get("assets") or []]
    return {"assets": [_verdict(path, thresholds) for path in paths]}


def _verdict(path: str, thresholds: dict[str, int]) -> dict[str, Any]:
    """One asset's verdict: the measured size against the recipe."""
    try:
        width, height = _png_size(path)
    except (OSError, ValueError) as exc:
        return _asset_verdict(path, False, {"error": str(exc)}, thresholds)
    passed = width == thresholds["width"] and height == thresholds["height"]
    return _asset_verdict(path, passed, {"width": width, "height": height}, thresholds)


def _asset_verdict(
    path: str, passed: bool, metrics: dict[str, Any], thresholds: dict[str, int]
) -> dict[str, Any]:
    return {
        "file": posixpath.basename(path),
        "passed": passed,
        "metrics": metrics,
        "thresholds": thresholds,
        "verifier": "png",
    }


def _preview(bpy: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Write the image kind's preview file beside each asset."""
    params = dict(request.get("inputs") or {})
    entries: list[dict[str, Any]] = []
    for item in request.get("assets") or []:
        path = str(item)
        file_name = posixpath.basename(path)
        name = posixpath.splitext(file_name)[0]
        width, height = _png_size(path)
        data = {
            "preview": 1,
            "kind": "image",
            "summary": (
                f"{name} · {width}×{height} · giro {_giro(params):g} · "
                f"exposure {_exposure(params):g}"
            ),
            "name": name,
            "prompt": _prompt(params),
            "seed": SEED,
            "width": width,
            "height": height,
        }
        preview_name = f"{file_name}.preview.json"
        preview_path = f"{posixpath.dirname(path)}/{preview_name}"
        with open(_open_path(preview_path), "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
        entries.append({"file": file_name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _prompt(params: dict[str, Any]) -> str:
    """The one line describing the scene, as the image preview's prompt.

    A render has no sampling prompt; the field belongs to the shared image
    kind, so it carries the recipe that produced the photo instead.
    """
    stem = posixpath.splitext(posixpath.basename(str(params.get("model", ""))))[0]
    camera = _camera(params)
    return (
        f"{stem} · daylight architectural photo · azimut {camera['azimut']:g} "
        f"elevacion {camera['elevacion']:g} · giro {_giro(params):g} · "
        f"exposure {_exposure(params):g}"
    )


def _doctor(bpy: Any, request: dict[str, Any]) -> dict[str, Any]:
    """The Blender-side modules: bpy, its glTF importer and Cycles.

    The host binary itself — present, at least 5.2 — is facet's own check:
    ``facet doctor`` resolves ``blender.path`` and probes ``--version``.
    """
    checks = [_doctor_bpy(bpy), _doctor_gltf(bpy), _doctor_cycles(bpy)]
    if request.get("depth") == "full":
        checks.append(_doctor_devices(bpy))
    return {"checks": checks}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_bpy(bpy: Any) -> dict[str, Any]:
    return _check("bpy", True, f"bpy {_version(bpy)} imports")


def _doctor_gltf(bpy: Any) -> dict[str, Any]:
    try:
        importer = bpy.ops.import_scene.gltf
    except AttributeError as exc:
        return _check("gltf", False, str(exc), "use a Blender build that ships the glTF importer")
    return _check("gltf", importer is not None, "bpy.ops.import_scene.gltf is available")


def _doctor_cycles(bpy: Any) -> dict[str, Any]:
    try:
        preferences = bpy.context.preferences.addons["cycles"].preferences
    except (AttributeError, KeyError) as exc:
        return _check("cycles", False, str(exc), "enable the Cycles add-on in Blender")
    kind = getattr(preferences, "compute_device_type", "")
    return _check("cycles", True, f"Cycles is available (device type {kind})")


def _doctor_devices(bpy: Any) -> dict[str, Any]:
    try:
        preferences = bpy.context.preferences.addons["cycles"].preferences
        preferences.get_devices()
        devices = [str(device.name) for device in preferences.devices if device.type != "CPU"]
    except (AttributeError, KeyError, TypeError) as exc:
        return _check("gpu", False, str(exc), "install the Blender build with an OptiX device")
    detail = ", ".join(devices) if devices else "no OptiX or CUDA device: Cycles falls back to CPU"
    return _check("gpu", bool(devices), detail, "install the NVIDIA driver so OptiX is listed")


VERBS = {"run": _run, "verify": _verify, "preview": _preview, "doctor": _doctor}


# --- the scene: the lab's daylight recipe, one piece per glTF element.


def _render(bpy: Any, model: str, destination: str, params: dict[str, Any]) -> None:
    """Import the glTF, dress the scene and render it to ``destination``."""
    windows = _on_windows()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    bpy.ops.import_scene.gltf(filepath=_host_path(model, windows))
    _scale_roots(scene)
    _turn_roots(scene, _giro(params))
    bpy.context.view_layer.update()
    centre = _centre(scene)
    _floor(bpy, scene, centre)
    _dress(bpy, scene, MATERIALS)
    _sky_and_sun(bpy, scene)
    _place_camera(bpy, scene, _camera(params), centre)
    scene.render.resolution_x = RENDER_WIDTH
    scene.render.resolution_y = RENDER_HEIGHT
    scene.view_settings.exposure = _exposure(params)
    with suppress(TypeError):
        scene.view_settings.look = LOOK
    _cycles(bpy, scene)
    scene.render.filepath = _host_path(destination, windows)
    bpy.ops.render.render(write_still=True)


def _scale_roots(scene: Any) -> None:
    """The glTF arrives in millimetres: the top-level pieces become metres."""
    for obj in [item for item in scene.objects if item.parent is None]:
        obj.scale = tuple(side * SCALE for side in obj.scale)
        obj.location = tuple(side * SCALE for side in obj.location)


def _turn_roots(scene: Any, degrees: float) -> None:
    """Turn the whole model about Z; the sun stays, so the light changes.

    The glTF importer leaves every object in ``QUATERNION`` rotation mode,
    where Blender ignores ``rotation_euler``; switching the mode first is what
    makes the turn reach the scene (Blender carries the existing orientation
    over when the mode changes).
    """
    if not degrees:
        return
    for obj in [item for item in scene.objects if item.parent is None]:
        obj.rotation_mode = "XYZ"
        obj.rotation_euler[2] += math.radians(degrees)


def _floor(bpy: Any, scene: Any, centre: tuple[float, float, float]) -> None:
    """An outside plane just under the model, so the sun casts a shadow.

    It sits below the lowest mesh, never at the model's mid-height: a plane
    through the room would hide the furniture and the slab from the camera.
    """
    drop = _lowest_z(scene) - FLOOR_DROP
    bpy.ops.mesh.primitive_plane_add(size=FLOOR_SIZE, location=(centre[0], centre[1], drop))
    bpy.context.active_object.name = "suelo"


def _lowest_z(scene: Any) -> float:
    """The lowest point of every mesh, in metres; zero for an empty scene."""
    lows = [
        _world_point(obj.matrix_world, corner)[2]
        for obj in scene.objects
        if getattr(obj, "type", "") == "MESH"
        for corner in obj.bound_box
    ]
    return min(lows) if lows else 0.0


def _centre(scene: Any) -> tuple[float, float, float]:
    """The middle of every mesh, in metres; the origin for an empty scene."""
    points = [
        _world_point(obj.matrix_world, corner)
        for obj in scene.objects
        if getattr(obj, "type", "") == "MESH"
        for corner in obj.bound_box
    ]
    if not points:
        return (0.0, 0.0, 0.0)
    lows = [min(point[axis] for point in points) for axis in range(3)]
    highs = [max(point[axis] for point in points) for axis in range(3)]
    middle = [(lows[axis] + highs[axis]) / 2 for axis in range(3)]
    return (middle[0], middle[1], middle[2])


def _world_point(matrix: Any, corner: Any) -> tuple[float, float, float]:
    """One local bound-box corner in world space, without mathutils."""
    point = [
        sum(matrix[axis][column] * corner[column] for column in range(3)) + matrix[axis][3]
        for axis in range(3)
    ]
    return (point[0], point[1], point[2])


def _dress(bpy: Any, scene: Any, recipes: dict[str, Recipe]) -> None:
    """Assign each mesh the material of its name prefix; none left over."""
    materials = {prefix: _material(bpy, prefix, recipe) for prefix, recipe in recipes.items()}
    missing = _assign(scene, materials)
    if missing:
        raise RuntimeError(f"piezas sin material: {missing}")


def _material(bpy: Any, name: str, recipe: Recipe) -> Any:
    """One Principled material: colour, roughness and glass transmission."""
    colour, roughness, transmission = recipe
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    inputs = material.node_tree.nodes["Principled BSDF"].inputs
    inputs["Base Color"].default_value = (*colour, 1)
    inputs["Roughness"].default_value = roughness
    inputs["Transmission Weight"].default_value = transmission
    if transmission:
        inputs["IOR"].default_value = 1.45
    return material


def _assign(scene: Any, materials: dict[str, Any]) -> list[str]:
    """Give every mesh its prefix's material; return the pieces left without."""
    missing: list[str] = []
    for obj in scene.objects:
        if getattr(obj, "type", "") != "MESH":
            continue
        prefix = next((key for key in materials if obj.name.lower().startswith(key)), None)
        if prefix is None:
            missing.append(obj.name)
            continue
        obj.data.materials.clear()
        obj.data.materials.append(materials[prefix])
    return missing


def _sky_and_sun(bpy: Any, scene: Any) -> None:
    """A sky texture washing the scene from the sun's direction, plus the sun."""
    world = bpy.data.worlds.new("cielo")
    scene.world = world
    world.use_nodes = True
    azimuth, elevation = math.radians(SUN["azimut"]), math.radians(SUN["elevacion"])
    try:
        sky = world.node_tree.nodes.new("ShaderNodeTexSky")
        sky.sun_elevation, sky.sun_rotation = elevation, azimuth
        background = world.node_tree.nodes["Background"]
        world.node_tree.links.new(sky.outputs["Color"], background.inputs["Color"])
        background.inputs["Strength"].default_value = SKY_STRENGTH
    except (AttributeError, KeyError, RuntimeError, TypeError):
        world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.75, 0.82, 0.92, 1)
    light = bpy.data.lights.new("sol", "SUN")
    light.energy, light.angle = SUN["fuerza"], math.radians(SUN_ANGLE_DEG)
    sun = bpy.data.objects.new("sol", light)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.pi / 2 - elevation, 0, azimuth + math.pi / 2)


def _place_camera(
    bpy: Any, scene: Any, camera: dict[str, float], centre: tuple[float, float, float]
) -> None:
    """An orthographic camera looking at the model's centre from the view."""
    azimuth, elevation = math.radians(camera["azimut"]), math.radians(camera["elevacion"])
    direction = (
        math.cos(elevation) * math.cos(azimuth),
        math.cos(elevation) * math.sin(azimuth),
        math.sin(elevation),
    )
    distance = max(camera["escala"], 1.0) * CAMERA_DISTANCE
    data = bpy.data.cameras.new("camara")
    data.type, data.ortho_scale = "ORTHO", camera["escala"]
    obj = bpy.data.objects.new("camara", data)
    scene.collection.objects.link(obj)
    obj.location = tuple(centre[axis] + distance * direction[axis] for axis in range(3))
    obj.rotation_euler = (math.pi / 2 - elevation, 0, azimuth + math.pi / 2)
    scene.camera = obj


def _cycles(bpy: Any, scene: Any) -> None:
    """Cycles on the first GPU device it finds: OPTIX, then CUDA, else CPU."""
    scene.render.engine = "CYCLES"
    preferences = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            preferences.compute_device_type = kind
            preferences.get_devices()
            devices = [device for device in preferences.devices if device.type == kind]
        except TypeError:
            continue
        if devices:
            for device in preferences.devices:
                device.use = device.type == kind
            scene.cycles.device = "GPU"
            break
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.cycles.seed = SEED


# --- the request's parameters and the asset's name.


def _camera(params: dict[str, Any]) -> dict[str, float]:
    """The piece's camera view, one ``{ azimut, elevacion, escala }`` item."""
    view = dict(DEFAULT_CAMERA)
    items = params.get("camera")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        view.update({key: float(value) for key, value in items[0].items() if key in view})
    return view


def _giro(params: dict[str, Any]) -> float:
    """The model's turn about Z, in degrees."""
    return float(params.get("giro", 0.0))


def _exposure(params: dict[str, Any]) -> float:
    """The exposure in stops under the AgX view transform."""
    return float(params.get("exposure", DEFAULT_EXPOSURE))


def _asset_name(model: str) -> str:
    """``estudio.glb`` -> ``estudio-foto``: the image schema's base name."""
    stem = posixpath.splitext(posixpath.basename(model))[0].lower()
    safe = UNSAFE_NAME.sub("-", stem).strip("-")
    return f"{safe or 'foto'}{ASSET_SUFFIX}"


def _version(bpy: Any) -> str:
    try:
        return str(bpy.app.version_string)
    except AttributeError:
        return "unknown"


# --- the PNG: measured from its header, which needs no third-party module.


def _png_size(value: str) -> tuple[int, int]:
    """A PNG's pixel size from its IHDR, so verify needs no Pillow in Blender."""
    with open(_open_path(value), "rb") as handle:
        header = handle.read(PNG_HEADER_BYTES)
    if len(header) < PNG_HEADER_BYTES or header[:8] != PNG_SIGNATURE:
        raise ValueError(f"{posixpath.basename(value)}: not a PNG")
    start, end = PNG_SIZE_OFFSET
    width, height = struct.unpack(">II", header[start:end])
    return int(width), int(height)


def _open_path(value: str) -> str:
    """The path ``open`` accepts when this entry runs inside the Windows build."""
    return _host_path(value, _on_windows())


# --- the host launch, for the WSL Windows Blender the lab runs.


def _on_windows() -> bool:
    """True inside the Windows build of Blender, where POSIX paths do not open."""
    return sys.platform.startswith("win")


def _host_path(value: str, windows: bool, root: str | None = None) -> str:
    """The path the Windows build can open; unchanged everywhere else.

    String work only: ``pathlib`` inside the Windows build reads ``/mnt/c/x``
    as ``\\mnt\\c\\x``, and ``wslpath`` is a WSL executable it cannot run,
    so the launcher resolves WSL's own root once and passes it down.
    """
    if not windows or not value or _is_windows(value):
        return value
    mapped = _drive_path(value)
    if mapped is not None:
        return mapped
    anchor = (root if root is not None else _wsl_root()).rstrip("\\")
    if anchor and value.startswith("/"):
        return f"{anchor}\\{value.lstrip('/').replace('/', chr(92))}"
    return value


def _wsl_root() -> str:
    """WSL's own root as a Windows UNC path, discovered from the request's path.

    facet converts ``--input`` with ``wslpath -w`` before the host launches,
    so inside the Windows build that argument already reads
    ``\\\\wsl.localhost\\<distro>\\...``; its server and share are the
    mount point every POSIX path in the request belongs to.
    """
    return _UNC_ROOT[0]


def _remember_root(value: str) -> None:
    """Record the UNC mount point of a path the host already converted."""
    if not value.startswith("\\\\"):
        return
    parts = value.split("\\")
    if len(parts) >= UNC_PARTS:
        _UNC_ROOT[0] = "\\".join(parts[:UNC_PARTS])


def _is_windows(value: str) -> bool:
    """``C:\\x`` or ``\\\\server\\share``: already a path the Windows build opens."""
    return bool(DRIVE_RE.match(value) or value.startswith("\\\\"))


def _drive_path(value: str) -> str | None:
    """``/mnt/c/Users/x`` -> ``C:\\Users\\x``; ``None`` for anything else."""
    parts = value.split("/")
    # ``["", "mnt", "<drive>", ...]``: the WSL mount point's own shape.
    if len(parts) < MOUNT_PARTS or parts[:2] != ["", "mnt"] or len(parts[2]) != 1:
        return None
    drive = parts[2].upper()
    rest = "\\".join(parts[3:])
    return f"{drive}:\\{rest}" if rest else f"{drive}:\\"


def _wsl_unc_root() -> str:
    """The Windows UNC path of WSL's own ``/``, from ``wslpath -w /``."""
    converted = _wslpath("/")
    return converted.rstrip("\\") if converted else ""


def _wslpath(value: str) -> str:
    """``wslpath -w`` of a path the drive mapping does not cover; ``""`` if it cannot."""
    try:
        done = subprocess.run(
            ["wslpath", "-w", value],
            capture_output=True,
            text=True,
            check=False,
            timeout=WSLPATH_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    converted = done.stdout.strip()
    return converted if done.returncode == 0 else ""


def _blender_binary() -> str:
    """The host binary the launcher drives: ``BLENDER_EXE``, then ``PATH``."""
    configured = os.environ.get("BLENDER_EXE", "")
    if configured:
        return configured
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / "blender"
        if candidate.is_file():
            return str(candidate)
    return ""


def _launch_host(verb: str, input_path: Path, result_path: Path) -> None:
    """Drive the host Blender with the lab's flags, retrying interop once."""
    binary = _blender_binary()
    if not binary:
        raise RuntimeError(
            "blender not found (set BLENDER_EXE or put blender on PATH); "
            "facet resolves blender.path"
        )
    windows = binary.lower().endswith(".exe")
    root = _wsl_unc_root() if windows else ""
    command = [
        binary,
        *HOST_FLAGS,
        _host_path(str(Path(__file__).resolve()), windows, root),
        "--",
        verb,
        "--input",
        _host_path(str(input_path), windows, root),
        "--result",
        _host_path(str(result_path), windows, root),
    ]
    _run_host(command)


def _run_host(command: list[str]) -> None:
    """Launch once, and once more only when WSL interop failed."""
    for attempt in range(1, ATTEMPTS + 1):
        done = subprocess.run(command, capture_output=True, text=True, check=False)
        output = f"{done.stdout or ''}{done.stderr or ''}"
        if done.returncode == 0:
            print(output, end="")
            return
        if INTEROP_MARKER not in output or attempt == ATTEMPTS:
            raise RuntimeError(f"blender exited {done.returncode}: {_tail(output)}")
        print(
            f"blender exited {done.returncode} after a WSL interop failure (attempt {attempt})",
            file=sys.stderr,
        )


def _tail(text: str) -> str:
    return text[-TAIL_CHARS:].strip()


if __name__ == "__main__":
    raise SystemExit(main())
