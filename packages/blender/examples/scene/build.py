"""A short scripted scene: a plane, three primitives, two lights, a camera.

``blender.scene`` runs this and renders one still; ``blender.animation``
runs the same file and renders the keyframed camera move (frames 1..120,
the animation default) as an MP4. facet owns the output — the resolution,
the engine and its samples, the exposure, the frame range — so the script
sets only the scene: the objects, the materials, the lights, the camera.

``FACET_ASSETS`` (the Poly Haven root ``blender.assets`` fills) and
``FACET_PIECE_DIR`` (this file's directory) are already in the globals;
this scene needs neither. The script must leave ``scene.camera`` set.
"""

import math

import bpy

START, END = -60.0, 60.0
RADIUS, HEIGHT = 8.0, 5.0
FRAMES = 120


def _material(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
        *color,
        1.0,
    )
    return mat


bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0.0, 0.0, 0.0))

bpy.ops.mesh.primitive_cube_add(size=2.0, location=(-2.0, 0.0, 1.0))
bpy.context.active_object.data.materials.append(_material("rojo", (0.8, 0.1, 0.1)))

bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(1.5, -1.0, 1.0))
bpy.context.active_object.data.materials.append(_material("verde", (0.1, 0.6, 0.2)))

bpy.ops.mesh.primitive_cone_add(radius1=1.0, depth=2.0, location=(1.5, 2.0, 1.0))
bpy.context.active_object.data.materials.append(_material("azul", (0.1, 0.3, 0.8)))

area = bpy.data.lights.new("area", type="AREA")
area.energy = 500.0
area.shape = "RECTANGLE"
area.size = 3.0
obj = bpy.data.objects.new("area", area)
obj.location = (-4.0, -4.0, 6.0)
bpy.context.scene.collection.objects.link(obj)

sun = bpy.data.lights.new("sol", type="SUN")
sun.energy = 3.0
obj = bpy.data.objects.new("sol", sun)
obj.rotation_euler = (math.radians(50.0), 0.0, math.radians(30.0))
bpy.context.scene.collection.objects.link(obj)

data = bpy.data.cameras.new("camara")
camera = bpy.data.objects.new("camara", data)
bpy.context.scene.collection.objects.link(camera)
bpy.context.scene.camera = camera

elevation = math.atan2(HEIGHT, RADIUS)
for frame in range(1, FRAMES + 1):
    t = (frame - 1) / (FRAMES - 1)
    azimuth = math.radians(START + (END - START) * t)
    camera.location = (
        RADIUS * math.cos(azimuth),
        RADIUS * math.sin(azimuth),
        HEIGHT,
    )
    camera.rotation_euler = (math.pi / 2 - elevation, 0.0, azimuth + math.pi / 2)
    camera.keyframe_insert("location", frame=frame)
    camera.keyframe_insert("rotation_euler", frame=frame)
