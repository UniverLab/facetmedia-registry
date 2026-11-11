# The tour recipe

`packages/blender/recorrido.py` renders the tour recipe: a still is Cycles, a
tour is Eevee.

## Why Eevee and not Cycles

A still is Cycles; a tour is Eevee. The same 10 s move is 240 frames at
1280x720: Cycles takes about 45 minutes for it, Eevee about 100 s. The quality
holds because the scene is static and only the camera moves; Cycles stays the
engine where every frame is looked at.

Eevee's default configuration comes out flat with black windows. The tour
turns the missing light back on with four flags:

```python
scene.render.engine = "BLENDER_EEVEE"
eevee = scene.eevee
eevee.taa_render_samples = 32
eevee.use_raytracing = True
eevee.ray_tracing_method = "SCREEN"
eevee.use_fast_gi = True
eevee.use_shadows = True
```

`use_raytracing` with `ray_tracing_method = "SCREEN"` gives reflections and
screen-space bounced light; `use_fast_gi` adds fast occlusion and bounce;
`use_shadows` keeps the sun's shadow. Without them the first Eevee attempt was
unfairly rejected as flat (`estudio-eevee.png` in the lab notes).

The lab's `escena.py` also pulls the sun out of its HDRI as a shadow-casting
light with `world.use_sun_shadow`. This package has no HDRI:
`packages/blender/escena.py` lights the scene with a sky texture plus a sun
lamp of its own and never sets that flag. Both keep the still's look,
`AgX - Medium High Contrast`, at exposure -0.4 here (the still is -0.6), set
in the shared scene so the tour and the photo read as the same place.

## The move: one smoothstep, one keyframe per frame

The camera starts at the piece's start triple and ends at its end triple. The
lab's defaults are azimut -75 → -15, elevacion 55 → 40 and distancia 14.0 →
10.5 m, with a 30 mm lens and a 500 m far clip.

The interpolation is the camera-crane ease, not a line:

```python
def smooth(t):
    return t * t * (3 - 2 * t)
```

For each frame the runner computes `t = smooth(n / (frames - 1))`, walks each
of the three legs from `inicio` to `fin`, places the camera on the orbit and
inserts one `location` and one `rotation_euler` keyframe on that frame. 240
frames therefore mean 240 location keys and 240 rotation keys, on frames 1 to
240. Blender interpolates between them; the pose on screen is the ease, so the
move leaves and arrives gently.

The pose is a plain orbit around the model's centre:

```python
offset = (
    distance * cos(elevacion) * cos(azimut),
    distance * cos(elevacion) * sin(azimut),
    distance * sin(elevacion),
)
rotation = (pi / 2 - elevacion, 0.0, azimut + pi / 2)
```

## The file Blender writes

Blender writes the MP4 directly; no second ffmpeg pass:

```python
image = scene.render.image_settings
image.media_type = "VIDEO"
image.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "HIGH"
scene.render.use_file_extension = False
```

`media_type = "VIDEO"` and `file_format = "FFMPEG"` pick the video writer;
`MPEG4` with `H264` is the container and codec; `HIGH` is the constant-rate
factor. `use_file_extension = False` keeps the exact output path, so the clip
lands as `<model>-recorrido.mp4` and the probe reads its width, height, frame
count and fps back from the file.

## What `verify` checks

The MP4 probe (`packages/blender/mp4.py`) reads the ISO BMFF boxes: `avc1`
for width and height, `stts` for the frame count, `mvhd` for the timescale. A
240-frame, 24 fps entry is what a 10 s tour produces; a 120-frame clip fails
on the frame count. A file that is not an MP4 comes back as a failed verdict
with the parse error in `metrics`, never as an exception.
