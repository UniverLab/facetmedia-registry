"""The product shot: one CAD part in a photographic studio, on Cycles.

``blender.producto`` photographs the STL that ``cad.solid`` writes beside the
piece: the part is imported in millimetres, scaled to metres, dressed in one
metallic Principled material and shot at 1200x1200 under two area lights
against a dark backdrop. The recipe is the lab's approved
``projects/prueba-render-arq/producto.py``.

Small pieces burn out under studio lights, so the lights are derived from the
part's measured bounding box instead of being fixed: a 6 cm piece gets two
4 W lights 0.50 m away, and every other size is clamped into the 2-6 W,
0.15-2 m regime. The backdrop stays dark on purpose, so brushed metal has
contrast against it.

This module is imported by the runner, which lives in the same folder, so it
never imports the runner back: inside Blender that module is ``__main__`` and
importing it would execute the entry twice.
"""

from __future__ import annotations

import math
from contextlib import suppress
from typing import Any

#: The approved product shot is square, the catalogue format.
PRODUCT_WIDTH = 1200
PRODUCT_HEIGHT = 1200
#: The lab's Cycles recipe: 128 samples with denoise, about 10 s on the GPU.
SAMPLES = 128
#: The STL arrives in millimetres; Blender works in metres.
SCALE = 0.001
#: Slightly under zero: metal highlights clip at the studio's light levels.
EXPOSURE = -0.2
LOOK = "AgX - Medium High Contrast"
SEED = 0
#: Name -> (base colour, metallic, roughness).
MATERIALS = {
    "aluminio-cepillado": ((0.75, 0.76, 0.78), 1.0, 0.38),
    "acero": ((0.55, 0.57, 0.60), 1.0, 0.22),
}
#: Name -> linear RGB of the seamless backdrop.
BACKDROPS = {
    "grafito": (0.02, 0.02, 0.025),
    "cemento": (0.09, 0.09, 0.095),
}
DEFAULT_MATERIAL = "aluminio-cepillado"
DEFAULT_BACKDROP = "grafito"
#: The reference the light rule is pinned to: 6 cm across is 4 W at 50 cm.
REFERENCE_SPAN = 0.06
REFERENCE_ENERGY = 4.0
REFERENCE_DISTANCE = 0.5
MIN_ENERGY = 2.0
MAX_ENERGY = 6.0
MIN_DISTANCE = 0.15
MAX_DISTANCE = 2.0
#: The two studio keys, as (azimuth, elevation) in degrees about the part.
LIGHTS = ((-35.0, 55.0), (145.0, 25.0))
#: A three-quarter view looking slightly down at the part.
CAMERA_AZIMUTH = -35.0
CAMERA_ELEVATION = 30.0
#: The camera sits this many part spans away, never closer than 25 cm.
CAMERA_DISTANCE = 3.0
CAMERA_MIN_DISTANCE = 0.25
LENS = 50.0
#: The span an empty import falls back to: the reference 6 cm piece.
DEFAULT_SPAN = REFERENCE_SPAN

#: One metal recipe: base colour, metallic and roughness.
Recipe = tuple[tuple[float, float, float], float, float]


def light_plan(span: float) -> tuple[float, float]:
    """``(energy_w, distance_m)`` for a part whose longest side is ``span``.

    4 W at 50 cm for the reference 6 cm piece, clamped so a tiny part keeps
    enough light and a large one does not wash out the studio.
    """
    factor = span / REFERENCE_SPAN
    energy = _clamp(REFERENCE_ENERGY * factor, MIN_ENERGY, MAX_ENERGY)
    distance = _clamp(REFERENCE_DISTANCE * factor, MIN_DISTANCE, MAX_DISTANCE)
    return energy, distance


def render(bpy: Any, part: str, destination: str, params: dict[str, Any]) -> None:
    """Import the STL, dress the studio and render it to ``destination``.

    ``part`` and ``destination`` are already paths the host can open: the
    runner converts them through ``_host_path`` before handing them over.
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    bpy.ops.wm.stl_import(filepath=part)
    _scale_roots(scene)
    bpy.context.view_layer.update()
    centre, span = _bounds(scene)
    _backdrop(bpy, scene, params)
    _dress(bpy, scene, params)
    _lights(bpy, scene, centre, span)
    _camera(bpy, scene, centre, span)
    scene.render.resolution_x = PRODUCT_WIDTH
    scene.render.resolution_y = PRODUCT_HEIGHT
    scene.view_settings.exposure = EXPOSURE
    with suppress(TypeError):
        scene.view_settings.look = LOOK
    _cycles(bpy, scene)
    scene.render.filepath = destination
    bpy.ops.render.render(write_still=True)


def _scale_roots(scene: Any) -> None:
    """The STL arrives in millimetres: the imported roots become metres."""
    for obj in [item for item in scene.objects if item.parent is None]:
        obj.scale = tuple(side * SCALE for side in obj.scale)
        obj.location = tuple(side * SCALE for side in obj.location)


def _bounds(scene: Any) -> tuple[tuple[float, float, float], float]:
    """The part's centre and longest side, in metres; the reference span if empty."""
    points = [
        _world_point(obj.matrix_world, corner)
        for obj in scene.objects
        if getattr(obj, "type", "") == "MESH"
        for corner in obj.bound_box
    ]
    if not points:
        return (0.0, 0.0, 0.0), DEFAULT_SPAN
    lows = [min(point[axis] for point in points) for axis in range(3)]
    highs = [max(point[axis] for point in points) for axis in range(3)]
    centre = tuple((lows[axis] + highs[axis]) / 2 for axis in range(3))
    span = max(highs[axis] - lows[axis] for axis in range(3))
    return (centre[0], centre[1], centre[2]), span


def _world_point(matrix: Any, corner: Any) -> tuple[float, float, float]:
    """One local bound-box corner in world space, without mathutils."""
    point = [
        sum(matrix[axis][column] * corner[column] for column in range(3)) + matrix[axis][3]
        for axis in range(3)
    ]
    return (point[0], point[1], point[2])


def _backdrop(bpy: Any, scene: Any, params: dict[str, Any]) -> None:
    """A dark seamless world; an unknown backdrop falls back to graphite."""
    name = str(params.get("backdrop") or DEFAULT_BACKDROP)
    colour = BACKDROPS.get(name, BACKDROPS[DEFAULT_BACKDROP])
    world = bpy.data.worlds.new("estudio")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs["Color"].default_value = (*colour, 1.0)
    background.inputs["Strength"].default_value = 1.0


def _dress(bpy: Any, scene: Any, params: dict[str, Any]) -> None:
    """One metal for every mesh; an unknown material fails the run loudly."""
    name = str(params.get("material") or DEFAULT_MATERIAL)
    recipe = MATERIALS.get(name)
    if recipe is None:
        raise RuntimeError(f"material desconocido: {name} (usa {', '.join(MATERIALS)})")
    material = _material(bpy, name, recipe)
    for obj in scene.objects:
        if getattr(obj, "type", "") == "MESH":
            obj.data.materials.clear()
            obj.data.materials.append(material)


def _material(bpy: Any, name: str, recipe: Recipe) -> Any:
    """One metallic Principled material: colour, metallic and roughness."""
    colour, metallic, roughness = recipe
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    inputs = material.node_tree.nodes["Principled BSDF"].inputs
    inputs["Base Color"].default_value = (*colour, 1.0)
    inputs["Metallic"].default_value = metallic
    inputs["Roughness"].default_value = roughness
    return material


def _lights(bpy: Any, scene: Any, centre: tuple[float, float, float], span: float) -> None:
    """Two square area lights, their energy and distance derived from the span."""
    energy, distance = light_plan(span)
    for index, (azimuth, elevation) in enumerate(LIGHTS, start=1):
        light = bpy.data.lights.new(f"luz-{index}", "AREA")
        light.shape = "SQUARE"
        light.size = distance
        light.energy = energy
        obj = bpy.data.objects.new(f"luz-{index}", light)
        scene.collection.objects.link(obj)
        obj.location = _offset(centre, azimuth, elevation, distance)


def _camera(bpy: Any, scene: Any, centre: tuple[float, float, float], span: float) -> None:
    """A 50 mm perspective camera looking down at the part from three quarters."""
    data = bpy.data.cameras.new("camara")
    data.type = "PERSP"
    data.lens = LENS
    obj = bpy.data.objects.new("camara", data)
    scene.collection.objects.link(obj)
    distance = max(CAMERA_DISTANCE * span, CAMERA_MIN_DISTANCE)
    obj.location = _offset(centre, CAMERA_AZIMUTH, CAMERA_ELEVATION, distance)
    elevation = math.radians(CAMERA_ELEVATION)
    obj.rotation_euler = (math.pi / 2 - elevation, 0.0, math.radians(CAMERA_AZIMUTH) + math.pi / 2)
    scene.camera = obj


def _offset(
    centre: tuple[float, float, float], azimuth: float, elevation: float, distance: float
) -> tuple[float, float, float]:
    """A point ``distance`` from ``centre`` along the given direction, in degrees."""
    azimuth_rad, elevation_rad = math.radians(azimuth), math.radians(elevation)
    direction = (
        math.cos(elevation_rad) * math.cos(azimuth_rad),
        math.cos(elevation_rad) * math.sin(azimuth_rad),
        math.sin(elevation_rad),
    )
    return tuple(centre[axis] + distance * direction[axis] for axis in range(3))


def _cycles(bpy: Any, scene: Any) -> None:
    """Cycles on the first GPU device it finds: OPTIX, then CUDA, else CPU.

    The runner has its own copy in ``runner.py``; it cannot be imported from
    here, because inside Blender the runner is ``__main__``.
    """
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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
