"""The lab's study as a daylight architectural photo, for ``blender.scene``.

A starting point: copy this folder and edit ``DATA``. Every creative choice
is here — the light, the materials, the camera — and none of it is facet's.
facet owns only the output (resolution, engine, samples, exposure, seed), so
the piece TOML carries those and this script carries the look.

The script imports ``estudio.glb`` (the study ``estudio.py`` exports from
CadQuery, one named element per piece) from the piece's own directory, scales
millimetres to metres, dresses each piece by name prefix and frames it with
an orthographic camera. ``FACET_PIECE_DIR`` is the global facet hands in.

Run it with ``facet run blender.scene study-photo.toml``.
"""

import math

import bpy

DATA = {
    "model": "estudio.glb",
    "scale": 0.001,
    "look": "AgX - Medium High Contrast",
    "sky": {"strength": 0.2},
    "sun": {"azimuth": 210.0, "elevation": 32.0, "strength": 3.0, "angle": 2.0},
    "floor": {"size": 60.0, "drop": 0.001, "color": (0.80, 0.80, 0.78), "roughness": 0.95},
    "materials": {
        "muros": {"color": (0.92, 0.91, 0.88), "roughness": 0.9},
        "piso": {"color": (0.50, 0.34, 0.21), "roughness": 0.45},
        "vidrio": {
            "color": (0.85, 0.93, 1.0),
            "roughness": 0.02,
            "transmission": 1.0,
            "ior": 1.45,
            "blended": True,
        },
        "cama": {"color": (0.23, 0.33, 0.52), "roughness": 0.85},
        "almohada": {"color": (0.95, 0.95, 0.94), "roughness": 0.8},
        "mesa": {"color": (0.40, 0.26, 0.15), "roughness": 0.4},
        "sillas": {"color": (0.90, 0.40, 0.18), "roughness": 0.55},
    },
    "camera": {
        "azimuth": -40.0,
        "elevation": 48.0,
        "aspect": 0.625,
        "margin": 1.1,
        "min_scale": 4.0,
        "distance": 2.5,
    },
}


def world_point(matrix, corner):
    """One local bound-box corner in world space, without mathutils."""
    return tuple(
        sum(matrix[axis][column] * corner[column] for column in range(3)) + matrix[axis][3]
        for axis in range(3)
    )


def corners(scene, skip_names=()):
    """Every mesh's world bound-box corners, optionally skipping some."""
    return [
        world_point(obj.matrix_world, corner)
        for obj in scene.objects
        if getattr(obj, "type", "") == "MESH" and obj.name not in skip_names
        for corner in obj.bound_box
    ]


def middle(points):
    """The middle of a set of world points; the origin when there is none."""
    if not points:
        return (0.0, 0.0, 0.0)
    lows = [min(point[axis] for point in points) for axis in range(3)]
    highs = [max(point[axis] for point in points) for axis in range(3)]
    return tuple((lows[axis] + highs[axis]) / 2 for axis in range(3))


def lowest(points):
    """The lowest point of a set of world points, in metres."""
    return min((point[2] for point in points), default=0.0)


def import_model(scene, model, scale):
    """Import the glTF and turn its millimetres into metres."""
    bpy.ops.import_scene.gltf(filepath=model)
    for obj in [item for item in scene.objects if item.parent is None]:
        obj.scale = tuple(side * scale for side in obj.scale)
        obj.location = tuple(side * scale for side in obj.location)


def bake_pieces(scene):
    """Clear each mesh's parent and bake its rotation and scale into the mesh.

    The glTF root arrives turned -90 about X, so a parented piece's own
    normals are not its world normals; after the bake they are.
    """
    bpy.context.view_layer.update()
    for obj in [item for item in scene.objects if getattr(item, "type", "") == "MESH"]:
        if obj.parent is None:
            continue
        for other in scene.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def material(recipe):
    """One Principled material: colour, roughness and optional glass."""
    block = bpy.data.materials.new("piece")
    block.use_nodes = True
    inputs = block.node_tree.nodes["Principled BSDF"].inputs
    inputs["Base Color"].default_value = (*recipe["color"], 1.0)
    inputs["Roughness"].default_value = recipe["roughness"]
    inputs["Transmission Weight"].default_value = recipe.get("transmission", 0.0)
    if recipe.get("ior"):
        inputs["IOR"].default_value = recipe["ior"]
    if recipe.get("blended"):
        block.surface_render_method = "BLENDED"
    return block


def dress(scene, recipes):
    """Give every mesh the material of its name prefix; none may be left over."""
    blocks = {prefix: material(recipe) for prefix, recipe in recipes.items()}
    missing = []
    for obj in scene.objects:
        if getattr(obj, "type", "") != "MESH":
            continue
        prefix = next((key for key in blocks if obj.name.lower().startswith(key)), None)
        if prefix is None:
            missing.append(obj.name)
            continue
        obj.data.materials.clear()
        obj.data.materials.append(blocks[prefix])
    if missing:
        raise RuntimeError(f"piezas sin material: {missing}")


def floor(scene, data, centre, lowest_z):
    """An outside plane just under the model, so the sun casts a shadow."""
    drop = lowest_z - data["drop"]
    bpy.ops.mesh.primitive_plane_add(
        size=data["size"], location=(centre[0], centre[1], drop)
    )
    bpy.context.active_object.name = "suelo"
    block = material(data)
    bpy.context.active_object.data.materials.append(block)


def sun_and_sky(scene, sun, sky):
    """A sky texture washing from the sun's direction, plus the sun lamp."""
    world = bpy.data.worlds.new("sky")
    scene.world = world
    world.use_nodes = True
    azimuth, elevation = math.radians(sun["azimuth"]), math.radians(sun["elevation"])
    sky_texture = world.node_tree.nodes.new("ShaderNodeTexSky")
    sky_texture.sun_elevation, sky_texture.sun_rotation = elevation, azimuth
    background = world.node_tree.nodes["Background"]
    world.node_tree.links.new(sky_texture.outputs["Color"], background.inputs["Color"])
    background.inputs["Strength"].default_value = sky["strength"]
    lamp = bpy.data.lights.new("sol", "SUN")
    lamp.energy, lamp.angle = sun["strength"], math.radians(sun["angle"])
    obj = bpy.data.objects.new("sol", lamp)
    scene.collection.objects.link(obj)
    obj.rotation_euler = (math.pi / 2 - elevation, 0, azimuth + math.pi / 2)


def fit_scale(points, centre, azimuth_deg, elevation_deg, aspect, margin, floor_scale):
    """The orthographic scale framing every point, with a margin."""
    azimuth, elevation = math.radians(azimuth_deg), math.radians(elevation_deg)
    right = (-math.sin(azimuth), math.cos(azimuth), 0.0)
    up = (
        -math.sin(elevation) * math.cos(azimuth),
        -math.sin(elevation) * math.sin(azimuth),
        math.cos(elevation),
    )

    def reach(direction):
        offsets = [
            abs(sum((point[axis] - centre[axis]) * direction[axis] for axis in range(3)))
            for point in points
        ]
        return max(offsets, default=0.0)

    across, upright = reach(right), reach(up)
    return max(floor_scale, margin * max(2 * across, 2 * upright / aspect))


def camera(scene, data, centre, scale):
    """An orthographic camera looking at the model's centre from the view."""
    azimuth, elevation = math.radians(data["azimuth"]), math.radians(data["elevation"])
    direction = (
        math.cos(elevation) * math.cos(azimuth),
        math.cos(elevation) * math.sin(azimuth),
        math.sin(elevation),
    )
    distance = max(scale, 1.0) * data["distance"]
    block = bpy.data.cameras.new("camara")
    block.type, block.ortho_scale = "ORTHO", scale
    obj = bpy.data.objects.new("camara", block)
    scene.collection.objects.link(obj)
    obj.location = tuple(centre[axis] + distance * direction[axis] for axis in range(3))
    obj.rotation_euler = (math.pi / 2 - elevation, 0, azimuth + math.pi / 2)
    scene.camera = obj


def build(scene, data):
    """Build the whole scene from ``DATA`` and leave ``scene.camera`` set."""
    piece_dir = globals()["FACET_PIECE_DIR"]
    import_model(scene, f"{piece_dir}/{data['model']}", data["scale"])
    bake_pieces(scene)
    model_points = corners(scene)
    centre = middle(model_points)
    dress(scene, data["materials"])
    floor(scene, data["floor"], centre, lowest(model_points))
    sun_and_sky(scene, data["sun"], data["sky"])
    view = data["camera"]
    scale = fit_scale(
        model_points,
        centre,
        view["azimuth"],
        view["elevation"],
        view["aspect"],
        view["margin"],
        view["min_scale"],
    )
    camera(scene, view, centre, scale)
    scene.view_settings.look = data["look"]


build(bpy.context.scene, DATA)
