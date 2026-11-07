"""The daylight scene both blender renders share: glTF, metres, materials, light.

``blender.foto`` photographs this scene and ``blender.recorrido`` moves a
camera through it, so the pieces every render needs live here once: the glTF
import's millimetres to metres, the floor the sun casts its shadow on, one
Principled material per piece-name prefix, and the sky texture plus sun pair.

It is a module of its own and not a part of the runner because neither renderer
may import the other: inside Blender the entry runs as ``__main__``, so
importing the runner back would execute the entry twice (``producto.py`` says
the same about itself).

A piece left without a material prefix fails the render loudly: nothing is ever
rendered half-dressed.
"""

from __future__ import annotations

import math
from typing import Any

#: glTF arrives in millimetres; Blender works in metres.
SCALE = 0.001
#: The view transform that keeps sun plus sky from washing the colours out.
LOOK = "AgX - Medium High Contrast"
#: The sun the approved render uses, and the sky wash strength beside it.
SUN = {"azimut": 210.0, "elevacion": 32.0, "fuerza": 3.0}
SKY_STRENGTH = 0.2
SUN_ANGLE_DEG = 2.0
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

#: One material recipe: base colour, roughness and glass transmission.
Recipe = tuple[tuple[float, float, float], float, float]


def scale_roots(scene: Any) -> None:
    """The glTF arrives in millimetres: the top-level pieces become metres."""
    for obj in [item for item in scene.objects if item.parent is None]:
        obj.scale = tuple(side * SCALE for side in obj.scale)
        obj.location = tuple(side * SCALE for side in obj.location)


def floor(bpy: Any, scene: Any, centre: tuple[float, float, float]) -> float:
    """An outside plane just under the model, so the sun casts a shadow.

    It sits below the lowest mesh, never at the model's mid-height: a plane
    through the room would hide the furniture and the slab from the camera.
    Returns that level, which is where people stand.
    """
    drop = lowest_z(scene) - FLOOR_DROP
    bpy.ops.mesh.primitive_plane_add(size=FLOOR_SIZE, location=(centre[0], centre[1], drop))
    bpy.context.active_object.name = "suelo"
    return drop


def lowest_z(scene: Any) -> float:
    """The lowest point of every mesh, in metres; zero for an empty scene."""
    lows = [
        world_point(obj.matrix_world, corner)[2]
        for obj in scene.objects
        if getattr(obj, "type", "") == "MESH"
        for corner in obj.bound_box
    ]
    return min(lows) if lows else 0.0


def centre(scene: Any) -> tuple[float, float, float]:
    """The middle of every mesh, in metres; the origin for an empty scene."""
    points = [
        world_point(obj.matrix_world, corner)
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


def world_point(matrix: Any, corner: Any) -> tuple[float, float, float]:
    """One local bound-box corner in world space, without mathutils."""
    point = [
        sum(matrix[axis][column] * corner[column] for column in range(3)) + matrix[axis][3]
        for axis in range(3)
    ]
    return (point[0], point[1], point[2])


def dress(bpy: Any, scene: Any, recipes: dict[str, Recipe]) -> None:
    """Assign each mesh the material of its name prefix; none left over."""
    materials = {prefix: material(bpy, prefix, recipe) for prefix, recipe in recipes.items()}
    missing = assign(scene, materials)
    if missing:
        raise RuntimeError(f"piezas sin material: {missing}")


def material(bpy: Any, name: str, recipe: Recipe) -> Any:
    """One Principled material: colour, roughness and glass transmission."""
    colour, roughness, transmission = recipe
    material_block = bpy.data.materials.new(name)
    material_block.use_nodes = True
    inputs = material_block.node_tree.nodes["Principled BSDF"].inputs
    inputs["Base Color"].default_value = (*colour, 1)
    inputs["Roughness"].default_value = roughness
    inputs["Transmission Weight"].default_value = transmission
    if transmission:
        inputs["IOR"].default_value = 1.45
    return material_block


def assign(scene: Any, materials: dict[str, Any]) -> list[str]:
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


def people(params: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """The prebuilt collection blend and the placements a piece asks for."""
    blend = params.get("personas-blend")
    placements = [item for item in params.get("personas") or [] if isinstance(item, dict)]
    return (str(blend) if blend else ""), placements


def personas(
    bpy: Any,
    scene: Any,
    blend: str,
    placements: list[dict[str, Any]],
    floor_z: float,
) -> None:
    """Stand each named collection of the prebuilt blend at its place.

    People are built once, outside this package, and arrive in metres: only
    their root moves, never their scale. Loading them after ``dress`` keeps
    their own MPFB skin and clothing materials, which carry no piece prefix.
    """
    if not placements:
        return
    if not blend:
        raise RuntimeError(f"{len(placements)} personas but no personas-blend")
    for placement in placements:
        nombre = str(placement["nombre"])
        collection = _loaded(bpy, blend, nombre, scene)
        root = _root(collection, nombre)
        root.location = (float(placement["x"]), float(placement["y"]), floor_z)
        root.rotation_mode = "XYZ"
        root.rotation_euler[2] = math.radians(float(placement.get("giro", 0)))


def _loaded(bpy: Any, blend: str, nombre: str, scene: Any) -> Any:
    """Link one named collection of the blend into the scene; raise if absent."""
    with bpy.data.libraries.load(blend) as (source, target):
        if nombre not in source.collections:
            names = sorted(source.collections)
            raise KeyError(f"{nombre} is not a collection in {blend} (has: {names})")
        target.collections = [nombre]
    collection = target.collections[0]
    scene.collection.children.link(collection)
    return collection


def _root(collection: Any, nombre: str) -> Any:
    """The collection's single parentless object: the skeleton root."""
    roots = [obj for obj in collection.objects if obj.parent is None]
    if len(roots) != 1:
        raise RuntimeError(f"{nombre}: expected one root object, found {len(roots)}")
    return roots[0]


def sky_and_sun(bpy: Any, scene: Any) -> None:
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
