"""The camera tour: a 10 s orbit of the daylight scene, rendered by Eevee.

``blender.tour`` moves through the scene ``escena.py`` builds — the same
glTF import, millimetre scale, per-prefix materials, sun plus sky wash and
floor the daylight photo uses — and writes ``<model>-tour.mp4``. The
recipe is the lab's ``architecture-render / escena.py`` tour block.

**Eevee, never Cycles.** A tour is 240 frames at 1280x720 and 24 fps: Cycles
takes about 45 minutes for that, Eevee about 100 s, at a level of quality that
holds because the scene is static and only the camera moves. Cycles stays the
still-photo engine where every frame is looked at.

The camera starts at the piece's ``azimuth``/``elevation``/``distance`` start
triple and glides to its end triple with a smoothstep ``t*t*(3-2*t)`` — it
leaves and arrives gently, like a camera crane. One ``location`` and one
``rotation_euler`` keyframe per frame is what makes Blender interpolate the
move, exactly as the lab loop does.

This module is imported by the runner, so it never imports the runner back:
inside Blender that module is ``__main__`` and importing it would execute the
entry twice (``producto.py`` says the same about itself).
"""

from __future__ import annotations

import math
import posixpath
import re
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import escena

#: The tour's format: 16:9 at 720p, the lab's clip size.
WIDTH = 1280
HEIGHT = 720
#: Eevee's samples: 32 is the lab's tour recipe, about 0.4 s per frame.
TAA_SAMPLES = 32
#: Slightly under zero under the AgX look, like the lab's tour.
EXPOSURE = -0.4
#: The speed of the move the lab approved.
DEFAULT_SECONDS = 10
DEFAULT_FPS = 24
#: A 30 mm lens frames the study from 14 m away.
DEFAULT_FOCAL = 30.0
#: Start -> end of each part of the move: around, down, and closer.
DEFAULT_AZIMUTH = (-75.0, -15.0)
DEFAULT_ELEVATION = (55.0, 40.0)
DEFAULT_DISTANCE = (14.0, 10.5)
#: A tour is deterministic, so the seed only labels the record.
DEFAULT_SEED = 0
#: What the run appends to the model's stem: ``estudio.glb`` -> ``estudio-tour``.
ASSET_SUFFIX = "-tour"
#: A start/end pair has exactly two numbers.
PAIR_LENGTH = 2
UNSAFE_NAME = re.compile(r"[^a-z0-9-]+")

#: One leg of the move: the value it starts at and the value it ends at.
Pair = tuple[float, float]


@dataclass(frozen=True)
class Tour:
    """The move the piece asks for: how long, how fast, and where it goes."""

    frames: int
    fps: int
    focal: float
    azimuth: Pair
    elevation: Pair
    distance: Pair


def plan(params: dict[str, Any]) -> Tour:
    """The piece's tour: its pairs and frame count, the lab defaults if absent."""
    fps = int(params.get("fps", DEFAULT_FPS))
    seconds = int(params.get("seconds", DEFAULT_SECONDS))
    return Tour(
        frames=seconds * fps,
        fps=fps,
        focal=float(params.get("focal", DEFAULT_FOCAL)),
        azimuth=_pair(params.get("azimuth"), DEFAULT_AZIMUTH),
        elevation=_pair(params.get("elevation"), DEFAULT_ELEVATION),
        distance=_pair(params.get("distance"), DEFAULT_DISTANCE),
    )


def _pair(value: Any, default: Pair) -> Pair:
    """One ``{ start, end }`` item, or a bare pair, or the default."""
    item = value[0] if isinstance(value, list) and value else value
    if isinstance(item, dict):
        return (float(item.get("start", default[0])), float(item.get("end", default[1])))
    if isinstance(item, list) and len(item) == PAIR_LENGTH:
        return (float(item[0]), float(item[1]))
    return default


def smooth(t: float) -> float:
    """The lab's ease: it starts and stops slowly, like a camera crane."""
    return t * t * (3 - 2 * t)


def pose(tour: Tour, frame: int, centre: tuple[float, float, float]) -> tuple[tuple, tuple]:
    """``(location, rotation_euler)`` of the camera on the given frame."""
    t = smooth(frame / (tour.frames - 1)) if tour.frames > 1 else 1.0
    azimuth = _at(tour.azimuth, t)
    elevation = _at(tour.elevation, t)
    distance = _at(tour.distance, t)
    azimuth_rad, elevation_rad = math.radians(azimuth), math.radians(elevation)
    offset = (
        distance * math.cos(elevation_rad) * math.cos(azimuth_rad),
        distance * math.cos(elevation_rad) * math.sin(azimuth_rad),
        distance * math.sin(elevation_rad),
    )
    location = tuple(centre[axis] + offset[axis] for axis in range(3))
    rotation = (math.pi / 2 - elevation_rad, 0.0, azimuth_rad + math.pi / 2)
    return location, rotation


def _at(pair: Pair, t: float) -> float:
    return pair[0] + (pair[1] - pair[0]) * t


def render(bpy: Any, model: str, destination: str, params: dict[str, Any], root: str = "") -> None:
    """Import the glTF, keyframe the tour and render it to ``destination``."""
    tour = plan(params)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    bpy.ops.import_scene.gltf(filepath=model)
    escena.scale_roots(scene)
    escena.bake_pieces(bpy, scene)
    bpy.context.view_layer.update()
    centre = escena.centre(scene)
    floor_z = escena.floor(bpy, scene, centre)
    escena.dress_scene(bpy, scene, params, root, floor_z)
    item = escena.sky_item(params)
    if item:
        escena.sky_hdri(bpy, scene, item, root)
    else:
        escena.sky_and_sun(bpy, scene)
    camera = _camera(bpy, scene, tour)
    _keyframes(camera, centre, tour)
    _settings(scene, tour)
    scene.render.filepath = destination
    bpy.ops.render.render(animation=True)


def _camera(bpy: Any, scene: Any, tour: Tour) -> Any:
    """A perspective camera at the move's start, with the piece's lens."""
    data = bpy.data.cameras.new("camara")
    data.type = "PERSP"
    data.lens = tour.focal
    with suppress(TypeError, AttributeError):
        data.clip_end = 500.0
    obj = bpy.data.objects.new("camara", data)
    obj.rotation_mode = "XYZ"
    scene.collection.objects.link(obj)
    scene.camera = obj
    return obj


def _keyframes(camera: Any, centre: tuple[float, float, float], tour: Tour) -> None:
    """One location plus rotation_euler keyframe per frame, the lab's loop."""
    for frame in range(tour.frames):
        location, rotation = pose(tour, frame, centre)
        camera.location = location
        camera.rotation_euler = rotation
        camera.keyframe_insert("location", frame=frame + 1)
        camera.keyframe_insert("rotation_euler", frame=frame + 1)


def _settings(scene: Any, tour: Tour) -> None:
    """Eevee with screen-space ray tracing, the AgX look, and an MP4 out."""
    scene.frame_start, scene.frame_end, scene.render.fps = 1, tour.frames, tour.fps
    scene.render.resolution_x, scene.render.resolution_y = WIDTH, HEIGHT
    scene.view_settings.exposure = EXPOSURE
    with suppress(TypeError):
        scene.view_settings.look = escena.LOOK
    scene.render.engine = "BLENDER_EEVEE"
    eevee = scene.eevee
    eevee.taa_render_samples = TAA_SAMPLES
    eevee.use_raytracing, eevee.ray_tracing_method = True, "SCREEN"
    eevee.use_fast_gi, eevee.use_shadows = True, True
    image = scene.render.image_settings
    image.media_type, image.file_format = "VIDEO", "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"
    scene.render.use_file_extension = False


def asset_name(model: str) -> str:
    """``estudio.glb`` -> ``estudio-tour``: the asset's base name."""
    return f"{stem(model)}{ASSET_SUFFIX}"


def stem(model: str) -> str:
    """``estudio.glb`` -> ``estudio``: the sanitized base name of a model."""
    name = posixpath.splitext(posixpath.basename(model))[0].lower()
    return UNSAFE_NAME.sub("-", name).strip("-") or "tour"


def prompt(name: str, tour: Tour) -> str:
    """The tour line a preview carries: what the camera does, in one line."""
    azimuth = f"{tour.azimuth[0]:g}→{tour.azimuth[1]:g}"
    return f"{name} · camera tour · azimuth {azimuth} · {tour.frames}f @ {tour.fps}fps"


def asset(params: dict[str, Any], model: str) -> dict[str, Any]:
    """One run's asset record: the clip, its format and the tour's parameters."""
    tour = plan(params)
    name = asset_name(model)
    seed = int(params.get("seed", DEFAULT_SEED))
    return {
        "file": f"{name}.mp4",
        "name": name,
        "kind": "video",
        "mime": "video/mp4",
        "properties": {
            "width": WIDTH,
            "height": HEIGHT,
            "frames": tour.frames,
            "fps": tour.fps,
            "seed": seed,
        },
        "params": dict(params),
        "seed": seed,
        "inputs": [model],
    }
