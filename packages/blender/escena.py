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
from pathlib import Path
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
    "pavimento": ((0.55, 0.55, 0.55), 0.9, 0.0),
}

#: One material recipe: base colour, roughness and glass transmission.
Recipe = tuple[tuple[float, float, float], float, float]

#: Poly Haven fetch resolutions: 2k for skies and textures, 1k for models.
SKY_RES = "2k"
TEXTURE_RES = "2k"
MODEL_RES = "1k"
#: The HDRI's turn about Z in degrees and its strength, when a piece asks for none.
GIRO = 200.0
FUERZA = 1.0
#: The texture tile's side in metres and its hue/saturation/value adjust, by default.
LADO = 2.0
AJUSTE = (0.5, 1.0, 1.0)


def scale_roots(scene: Any) -> None:
    """The glTF arrives in millimetres: the top-level pieces become metres."""
    for obj in [item for item in scene.objects if item.parent is None]:
        obj.scale = tuple(side * SCALE for side in obj.scale)
        obj.location = tuple(side * SCALE for side in obj.location)


def bake_pieces(bpy: Any, scene: Any) -> None:
    """Clear each mesh's parent and bake its rotation and scale into the mesh.

    The glTF root arrives turned -90 about X, so a parented piece's
    object-space normal is not its world normal and the BOX projection in
    ``textured`` smears the image into streaks. After the bake every piece
    carries identity rotation and unit scale, so its object-space normals
    equal its world normals. Emptied roots are left alone: they render
    nothing.

    The update first: the caller's edits (the millimetre-to-metre scale and
    the turn) are not in the world matrices until the view layer evaluates,
    and clearing the parent keeps exactly those matrices — without it the
    pieces would keep the import-time size and unturned.
    """
    bpy.context.view_layer.update()
    for obj in scene.objects:
        if getattr(obj, "type", "") == "MESH" and obj.parent is not None:
            _bake_piece(bpy, scene, obj)


def _bake_piece(bpy: Any, scene: Any, obj: Any) -> None:
    """Clear one piece's parent and apply its rotation and scale."""
    _select_only(bpy, scene, obj)
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def _select_only(bpy: Any, scene: Any, obj: Any) -> None:
    """Select one object alone, so the ops touch only it."""
    for other in scene.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


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


def fetched(root: str, asset_id: str, name: str, res: str) -> Path:
    """The fetched file, or the failure naming the assets entry that fetches it."""
    target = Path(root) / asset_id / name
    if target.is_file():
        return target
    raise RuntimeError(
        f"missing {asset_id}/{name}: fetch it with blender.assets "
        f'[[inputs.assets]] with id = "{asset_id}" and res = "{res}"'
    )


def cielo_item(params: dict[str, Any]) -> dict[str, Any]:
    """The piece's sky: the first cielo item, the way _camera reads camera."""
    items = params.get("cielo")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return dict(items[0])
    return {}


def texturas(params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The piece's textures by prefix; a repeated prefix fails loudly."""
    recipes: dict[str, dict[str, Any]] = {}
    for item in params.get("texturas") or []:
        if not isinstance(item, dict):
            continue
        prefix = str(item.get("prefijo", ""))
        if prefix in recipes:
            raise RuntimeError(f"texturas: prefijo repetido: {prefix}")
        recipes[prefix] = item
    return recipes


def plantas(params: dict[str, Any]) -> list[dict[str, Any]]:
    """The piece's plant placements, in the order it lists them."""
    return [item for item in params.get("plantas") or [] if isinstance(item, dict)]


def dress(
    bpy: Any,
    scene: Any,
    recipes: dict[str, Recipe],
    textures: dict[str, dict[str, Any]],
    root: str,
) -> None:
    """Assign each mesh the material of its name prefix; none left over."""
    materials = build_materials(bpy, recipes, textures, root)
    missing = assign(scene, materials)
    if missing:
        raise RuntimeError(f"piezas sin material: {missing}")


def build_materials(
    bpy: Any,
    recipes: dict[str, Recipe],
    textures: dict[str, dict[str, Any]],
    root: str,
) -> dict[str, Any]:
    """One material per prefix: textured where the piece asks, flat elsewhere."""
    dressed: dict[str, Any] = {}
    for prefix, recipe in recipes.items():
        if prefix in textures:
            dressed[prefix] = textured(bpy, prefix, textures[prefix], root)
        else:
            dressed[prefix] = material(bpy, prefix, recipe)
    return dressed


def _textura(bpy: Any, nodes: Any, links: Any, vector: Any, archivo: Path, color: bool) -> Any:
    """One box-projected image tap: sRGB for colour, Non-Color for data."""
    img = nodes.new("ShaderNodeTexImage")
    img.image = bpy.data.images.load(str(archivo), check_existing=True)
    img.image.colorspace_settings.name = "sRGB" if color else "Non-Color"
    img.projection, img.projection_blend = "BOX", 0.25
    links.new(vector, img.inputs["Vector"])
    return img.outputs["Color"]


def textured(bpy: Any, prefix: str, item: dict[str, Any], root: str) -> Any:
    """One Poly Haven texture material: diff, rough and a bump from the rough.

    Ported from the lab's ``textura``/``material``: the world-space position is
    box-projected at ``1/lado`` metres, ``diff.jpg`` tints the base colour
    through the hue/saturation/value adjust, and ``rough.jpg`` drives both the
    roughness and a 0.15 bump. ``nor_gl.jpg`` is never loaded: the lab's models
    carry no UVs for a normal map.
    """
    asset_id = str(item["id"])
    lado = float(item.get("lado", LADO))
    diff = fetched(root, asset_id, "diff.jpg", TEXTURE_RES)
    rough = fetched(root, asset_id, "rough.jpg", TEXTURE_RES)
    block = bpy.data.materials.new(prefix)
    block.use_nodes = True
    nodes, links = block.node_tree.nodes, block.node_tree.links
    bsdf = nodes["Principled BSDF"]
    geo = nodes.new("ShaderNodeNewGeometry")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = [1 / lado] * 3
    links.new(geo.outputs["Position"], mapping.inputs["Vector"])
    vector = mapping.outputs["Vector"]
    colour = _textura(bpy, nodes, links, vector, diff, True)
    ajuste = (
        float(item.get("matiz", AJUSTE[0])),
        float(item.get("saturacion", AJUSTE[1])),
        float(item.get("valor", AJUSTE[2])),
    )
    tint = nodes.new("ShaderNodeHueSaturation")
    for key, value in zip(("Hue", "Saturation", "Value"), ajuste, strict=True):
        tint.inputs[key].default_value = value
    links.new(colour, tint.inputs["Color"])
    colour = tint.outputs["Color"]
    links.new(colour, bsdf.inputs["Base Color"])
    roughness = _textura(bpy, nodes, links, vector, rough, False)
    links.new(roughness, bsdf.inputs["Roughness"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.15
    links.new(roughness, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return block


def place_plants(
    bpy: Any, scene: Any, placements: list[dict[str, Any]], root: str, floor_z: float
) -> None:
    """Import each Poly Haven model and stand its base centre at its place."""
    for placement in placements:
        asset_id = str(placement["id"])
        route = fetched(root, asset_id, f"{asset_id}.gltf", MODEL_RES)
        _place_plant(bpy, scene, asset_id, route, placement, floor_z)


def _place_plant(
    bpy: Any,
    scene: Any,
    asset_id: str,
    route: Path,
    placement: dict[str, Any],
    floor_z: float,
) -> None:
    """One plant: anchored like the lab's colocar, placed like people and cars."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(route))
    bpy.context.view_layer.update()
    nuevos = [obj for obj in bpy.data.objects if obj not in before]
    points = [
        world_point(obj.matrix_world, corner)
        for obj in nuevos
        if getattr(obj, "type", "") == "MESH"
        for corner in obj.bound_box
    ]
    base = (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
        min(point[2] for point in points),
    )
    anchor = bpy.data.objects.new(f"{asset_id}-ancla", None)
    scene.collection.objects.link(anchor)
    anchor.location = list(base)
    bpy.context.view_layer.update()
    for obj in nuevos:
        if obj.parent is None:
            obj.parent = anchor
            obj.matrix_parent_inverse = anchor.matrix_world.inverted()
    anchor.location = [float(placement["x"]), float(placement["y"]), floor_z]
    anchor.rotation_mode = "XYZ"
    anchor.rotation_euler[2] = math.radians(float(placement.get("giro", 0)))


def sky_hdri(bpy: Any, scene: Any, item: dict[str, Any], root: str) -> None:
    """The fetched HDRI sky: an environment texture turned by giro, no lamp.

    Ported from the lab's ``cielo``: the Mapping node turns the HDRI about Z,
    which sets where the sun falls, and ``use_sun_shadow`` lets Eevee pull a
    shadow-casting sun out of the HDRI. There is no "sol" lamp beside it.
    """
    asset_id = str(item["id"])
    route = fetched(root, asset_id, "sky.hdr", SKY_RES)
    world = bpy.data.worlds.new("cielo")
    scene.world = world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    coords = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    hdri = nodes.new("ShaderNodeTexEnvironment")
    hdri.image = bpy.data.images.load(str(route))
    mapping.inputs["Rotation"].default_value[2] = math.radians(float(item.get("giro", GIRO)))
    links.new(coords.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], hdri.inputs["Vector"])
    links.new(hdri.outputs["Color"], nodes["Background"].inputs["Color"])
    nodes["Background"].inputs["Strength"].default_value = float(item.get("fuerza", FUERZA))
    world.use_sun_shadow = True


def dress_scene(bpy: Any, scene: Any, params: dict[str, Any], root: str, floor_z: float) -> None:
    """The whole dressed scene: materials, people, cars and plants, in order."""
    dress(bpy, scene, dict(MATERIALS), texturas(params), root)
    blend, placements = people(params)
    personas(bpy, scene, blend, placements, floor_z)
    car_blend, cars = autos_params(params)
    autos(bpy, scene, car_blend, cars, floor_z)
    place_plants(bpy, scene, plantas(params), root, floor_z)


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


def autos_params(params: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """The prebuilt car blend and the placements a piece asks for."""
    blend = params.get("autos-blend")
    placements = [item for item in params.get("autos") or [] if isinstance(item, dict)]
    return (str(blend) if blend else ""), placements


def autos(
    bpy: Any,
    scene: Any,
    blend: str,
    placements: list[dict[str, Any]],
    floor_z: float,
) -> None:
    """Park each named collection of the prebuilt blend at its place.

    Cars are built once, outside this package, and arrive in metres: only
    their root moves, never their scale. Loading them after ``dress`` keeps
    the pack's own paint and glass materials, which carry no piece prefix.
    """
    if not placements:
        return
    if not blend:
        raise RuntimeError(f"{len(placements)} autos but no autos-blend")
    for placement in placements:
        nombre = str(placement["nombre"])
        collection = _loaded(bpy, blend, nombre, scene)
        root = _root(collection, nombre)
        root.location = (float(placement["x"]), float(placement["y"]), floor_z)
        root.rotation_mode = "XYZ"
        root.rotation_euler[2] = math.radians(float(placement.get("giro", 0)))


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
