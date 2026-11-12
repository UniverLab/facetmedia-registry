"""One CAD part as a studio product photo, for ``blender.scene``.

A starting point: copy this folder and edit ``DATA``. Every creative choice
is here — the metal, the world, the two softboxes, the camera — and facet owns
only the output (resolution, engine, samples, exposure, seed), which the piece
TOML carries.

The script imports ``part.stl`` (a 10x20x30 mm box from ``cad.solid``) from
the piece's own directory, scales it from millimetres to metres, measures its
bounding box and frames it from that. Metal has nothing to reflect in a black
studio: here two large square area lights act as softboxes around the part and
the world is a light grey, so the metal carries a highlight instead of the
black box the old fixed recipe produced.

Run it with ``facet run blender.scene product.toml``.
"""

import math

import bpy

DATA = {
    "model": "part.stl",
    "scale": 0.001,
    "look": "AgX - Medium High Contrast",
    # A dark world: the metal shows the softboxes against it, which is what
    # reads as metal. A bright, even world turns brushed metal into grey plastic.
    "world": {"color": (0.02, 0.02, 0.025), "strength": 1.0},
    "metal": {"color": (0.80, 0.81, 0.83), "metallic": 1.0, "roughness": 0.22},
    "floor": {"size": 1.2, "color": (0.12, 0.12, 0.13), "roughness": 0.3, "drop": 0.0005},
    "lights": [
        {
            "name": "softbox-key",
            "azimuth": -60.0,
            "elevation": 40.0,
            "size": 0.5,
            "energy": 2.8,
            "distance": 0.45,
        },
        {
            "name": "softbox-fill",
            "azimuth": 30.0,
            "elevation": 20.0,
            "size": 0.4,
            "energy": 1.0,
            "distance": 0.45,
        },
        {
            "name": "strip-rim",
            "azimuth": 150.0,
            "elevation": 35.0,
            "size": 0.3,
            "energy": 2.5,
            "distance": 0.4,
        },
    ],
    "camera": {"azimuth": -35.0, "elevation": 25.0, "lens": 50.0, "fill": 0.6, "sensor": 36.0},
}


def world_point(matrix, corner):
    """One local bound-box corner in world space, without mathutils."""
    return tuple(
        sum(matrix[axis][column] * corner[column] for column in range(3)) + matrix[axis][3]
        for axis in range(3)
    )


def bounds(scene):
    """The part's centre, longest side and bounding radius, in metres."""
    points = [
        world_point(obj.matrix_world, corner)
        for obj in scene.objects
        if getattr(obj, "type", "") == "MESH"
        for corner in obj.bound_box
    ]
    if not points:
        raise RuntimeError("part.stl imported no mesh: check the STL beside the piece")
    lows = [min(point[axis] for point in points) for axis in range(3)]
    highs = [max(point[axis] for point in points) for axis in range(3)]
    centre = tuple((lows[axis] + highs[axis]) / 2 for axis in range(3))
    extents = [highs[axis] - lows[axis] for axis in range(3)]
    radius = 0.5 * math.sqrt(sum(side * side for side in extents))
    return centre, max(extents), radius, lows[2]


def offset(centre, azimuth, elevation, distance):
    """A point ``distance`` from ``centre`` along the given direction, in degrees."""
    azimuth_rad, elevation_rad = math.radians(azimuth), math.radians(elevation)
    direction = (
        math.cos(elevation_rad) * math.cos(azimuth_rad),
        math.cos(elevation_rad) * math.sin(azimuth_rad),
        math.sin(elevation_rad),
    )
    return tuple(centre[axis] + distance * direction[axis] for axis in range(3))


def aim(obj, azimuth, elevation):
    """Turn an object so its -Z axis points from its place towards the origin."""
    obj.rotation_euler = (
        math.pi / 2 - math.radians(elevation),
        0.0,
        math.radians(azimuth) + math.pi / 2,
    )


def metal(data):
    """One metallic Principled material: colour, metallic and roughness."""
    block = bpy.data.materials.new("metal")
    block.use_nodes = True
    inputs = block.node_tree.nodes["Principled BSDF"].inputs
    inputs["Base Color"].default_value = (*data["color"], 1.0)
    inputs["Metallic"].default_value = data["metallic"]
    inputs["Roughness"].default_value = data["roughness"]
    return block


def studio_floor(data, centre, lowest_z):
    """A plane under the part, so the metal reflects a floor and not the void."""
    bpy.ops.mesh.primitive_plane_add(
        size=data["size"],
        location=(centre[0], centre[1], lowest_z - data["drop"]),
    )
    obj = bpy.context.active_object
    obj.name = "suelo"
    block = bpy.data.materials.new("suelo")
    block.use_nodes = True
    inputs = block.node_tree.nodes["Principled BSDF"].inputs
    inputs["Base Color"].default_value = (*data["color"], 1.0)
    inputs["Roughness"].default_value = data["roughness"]
    obj.data.materials.append(block)


def world(data):
    """The studio's light grey world: what the metal reflects between lights."""
    block = bpy.data.worlds.new("estudio")
    bpy.context.scene.world = block
    block.use_nodes = True
    background = block.node_tree.nodes["Background"]
    background.inputs["Color"].default_value = (*data["color"], 1.0)
    background.inputs["Strength"].default_value = data["strength"]


def softboxes(scene, lights, centre):
    """Two large square area lights around the part: the softboxes."""
    for light in lights:
        block = bpy.data.lights.new(light["name"], "AREA")
        block.shape = "SQUARE"
        block.size = light["size"]
        block.energy = light["energy"]
        obj = bpy.data.objects.new(light["name"], block)
        scene.collection.objects.link(obj)
        obj.location = offset(centre, light["azimuth"], light["elevation"], light["distance"])
        aim(obj, light["azimuth"], light["elevation"])


def camera(scene, view, centre, radius):
    """A perspective camera at the distance where the part fills the frame."""
    block = bpy.data.cameras.new("camara")
    block.type = "PERSP"
    block.lens = view["lens"]
    distance = radius / (view["fill"] * view["sensor"] / (2 * view["lens"]))
    block.clip_start = max(0.001, (distance - radius) / 2)
    block.clip_end = 100.0
    obj = bpy.data.objects.new("camara", block)
    scene.collection.objects.link(obj)
    obj.location = offset(centre, view["azimuth"], view["elevation"], distance)
    aim(obj, view["azimuth"], view["elevation"])
    scene.camera = obj


def build(scene, data):
    """Build the whole studio from ``DATA`` and leave ``scene.camera`` set."""
    piece_dir = globals()["FACET_PIECE_DIR"]
    bpy.ops.wm.stl_import(filepath=f"{piece_dir}/{data['model']}")
    for obj in [item for item in scene.objects if item.parent is None]:
        obj.scale = tuple(side * data["scale"] for side in obj.scale)
        obj.location = tuple(side * data["scale"] for side in obj.location)
    bpy.context.view_layer.update()
    centre, _span, radius, lowest_z = bounds(scene)
    for obj in [item for item in scene.objects if getattr(item, "type", "") == "MESH"]:
        obj.data.materials.clear()
        obj.data.materials.append(metal(data["metal"]))
    studio_floor(data["floor"], centre, lowest_z)
    world(data["world"])
    softboxes(scene, data["lights"], centre)
    camera(scene, data["camera"], centre, radius)
    scene.view_settings.look = data["look"]


build(bpy.context.scene, DATA)
