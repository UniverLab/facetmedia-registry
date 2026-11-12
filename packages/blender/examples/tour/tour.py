"""The lab's study on a camera tour, for ``blender.animation``.

A starting point: copy this folder and edit ``DATA``. Every creative choice
is here — the light, the materials, the orbit, the lens — and facet owns only
the output (resolution, engine, samples, exposure, seed, frame range and rate),
which the piece TOML carries.

The script imports the study ``../study-photo/estudio.glb``, dresses it the
way the study photo does, then keyframes the camera once per frame from the
move's start triple to its end triple with a smoothstep, so it leaves and
arrives gently like a crane. It sets Eevee's screen-space ray tracing, fast GI
and shadows, and leaves ``scene.camera`` set.

Run it with ``facet run blender.animation tour.toml``.
"""

import math

import bpy

DATA = {
    "model": "../study-photo/estudio.glb",
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
    "move": {
        "azimuth": (-75.0, -15.0),
        "elevation": (55.0, 40.0),
        "distance": (14.0, 10.5),
        "frames": 240,
    },
    "camera": {"focal": 30.0, "clip_end": 500.0},
    "eevee": {"raytracing": "SCREEN", "fast_gi": True, "shadows": True},
}


def world_point(matrix, corner):
    """One local bound-box corner in world space, without mathutils."""
    return tuple(
        sum(matrix[axis][column] * corner[column] for column in range(3)) + matrix[axis][3]
        for axis in range(3)
    )


def corners(scene):
    """Every mesh's world bound-box corners."""
    return [
        world_point(obj.matrix_world, corner)
        for obj in scene.objects
        if getattr(obj, "type", "") == "MESH"
        for corner in obj.bound_box
    ]


def middle(points):
    """The middle of a set of world points; the origin when there is none."""
    if not points:
        return (0.0, 0.0, 0.0)
    lows = [min(point[axis] for point in points) for axis in range(3)]
    highs = [max(point[axis] for point in points) for axis in range(3)]
    return tuple((lows[axis] + highs[axis]) / 2 for axis in range(3))


def import_model(scene, model, scale):
    """Import the glTF and turn its millimetres into metres."""
    bpy.ops.import_scene.gltf(filepath=model)
    for obj in [item for item in scene.objects if item.parent is None]:
        obj.scale = tuple(side * scale for side in obj.scale)
        obj.location = tuple(side * scale for side in obj.location)


def bake_pieces(scene):
    """Clear each mesh's parent and bake its rotation and scale into the mesh."""
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


def sun_and_sky(scene, sun, sky):
    """A sky texture washing from the sun's direction, plus the sun lamp."""
    block = bpy.data.worlds.new("sky")
    scene.world = block
    block.use_nodes = True
    azimuth, elevation = math.radians(sun["azimuth"]), math.radians(sun["elevation"])
    sky_texture = block.node_tree.nodes.new("ShaderNodeTexSky")
    sky_texture.sun_elevation, sky_texture.sun_rotation = elevation, azimuth
    background = block.node_tree.nodes["Background"]
    block.node_tree.links.new(sky_texture.outputs["Color"], background.inputs["Color"])
    background.inputs["Strength"].default_value = sky["strength"]
    lamp = bpy.data.lights.new("sol", "SUN")
    lamp.energy, lamp.angle = sun["strength"], math.radians(sun["angle"])
    obj = bpy.data.objects.new("sol", lamp)
    scene.collection.objects.link(obj)
    obj.rotation_euler = (math.pi / 2 - elevation, 0, azimuth + math.pi / 2)


def smooth(t):
    """The lab's ease: it starts and stops slowly, like a camera crane."""
    return t * t * (3 - 2 * t)


def between(pair, t):
    """The value ``t`` of the way from the pair's start to its end."""
    return pair[0] + (pair[1] - pair[0]) * t


def pose(move, frame, centre):
    """``(location, rotation_euler)`` of the camera on the given frame."""
    span = max(move["frames"] - 1, 1)
    t = smooth((frame - 1) / span)
    azimuth = between(move["azimuth"], t)
    elevation = between(move["elevation"], t)
    distance = between(move["distance"], t)
    azimuth_rad, elevation_rad = math.radians(azimuth), math.radians(elevation)
    offset = (
        distance * math.cos(elevation_rad) * math.cos(azimuth_rad),
        distance * math.cos(elevation_rad) * math.sin(azimuth_rad),
        distance * math.sin(elevation_rad),
    )
    location = tuple(centre[axis] + offset[axis] for axis in range(3))
    rotation = (math.pi / 2 - elevation_rad, 0.0, azimuth_rad + math.pi / 2)
    return location, rotation


def camera(scene, data):
    """A perspective camera at the move's start, with the piece's lens."""
    block = bpy.data.cameras.new("camara")
    block.type = "PERSP"
    block.lens = data["focal"]
    block.clip_end = data["clip_end"]
    obj = bpy.data.objects.new("camara", block)
    obj.rotation_mode = "XYZ"
    scene.collection.objects.link(obj)
    scene.camera = obj
    return obj


def keyframes(obj, move, centre):
    """One location plus rotation_euler keyframe per frame, the lab's loop."""
    for frame in range(1, move["frames"] + 1):
        location, rotation = pose(move, frame, centre)
        obj.location = location
        obj.rotation_euler = rotation
        obj.keyframe_insert("location", frame=frame)
        obj.keyframe_insert("rotation_euler", frame=frame)


def build(scene, data):
    """Build the whole scene from ``DATA`` and leave ``scene.camera`` set."""
    piece_dir = globals()["FACET_PIECE_DIR"]
    import_model(scene, f"{piece_dir}/{data['model']}", data["scale"])
    bake_pieces(scene)
    points = corners(scene)
    centre = middle(points)
    dress(scene, data["materials"])
    lowest_z = min((point[2] for point in points), default=0.0)
    floor(scene, data["floor"], centre, lowest_z)
    sun_and_sky(scene, data["sun"], data["sky"])
    keyframes(camera(scene, data["camera"]), data["move"], centre)
    eevee = scene.eevee
    eevee.use_raytracing = True
    eevee.ray_tracing_method = data["eevee"]["raytracing"]
    eevee.use_fast_gi = data["eevee"]["fast_gi"]
    eevee.use_shadows = data["eevee"]["shadows"]
    scene.view_settings.look = data["look"]


build(bpy.context.scene, DATA)
