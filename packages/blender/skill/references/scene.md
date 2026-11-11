# The scripted scene

`blender.scene` and `blender.animation` render your own Blender Python
script: a still PNG and an MP4. The recipes fix the scene; the script is the
free path — model, light and animate whatever they never foresaw.

## The contract

The runner starts from `bpy.ops.wm.read_factory_settings(use_empty=True)`
and executes the script with `runpy.run_path`. The guarantees, in order:

- **Working directory.** The script runs with its own directory as cwd, so
  `build.py` beside `scene.toml` opens `"build.py"` and its sidecars by bare
  name. `script` is resolved relative to the piece file.
- **Globals.** Two names are already set: `FACET_ASSETS`, the Poly Haven
  root `blender.assets` fills, and `FACET_PIECE_DIR`, the script's directory.
  Fetch skies, textures and models with one `blender.assets` piece first,
  then read them under `FACET_ASSETS` — the script never downloads.
- **Camera.** The script must set `scene.camera`. A run without one fails
  with `no camera: the script must set scene.camera`.
- **Overrides.** After the script, the runner applies facet's output
  settings, overriding whatever the script set: the resolution at 100 %, the
  engine and its samples (Cycles on the GPU through the runner's helper,
  then its samples and seed; Eevee with TAA render samples), the seed, and
  the exposure. An animation also gets the frame range 1..`frames`, the
  `fps`, and the tour's MP4 block (`media_type = "VIDEO"`,
  `file_format = "FFMPEG"`, `ffmpeg.format = "MPEG4"`, `codec = "H264"`,
  `constant_rate_factor = "HIGH"`, `use_file_extension = False`), then the
  output path. Everything else stays the script's: the world, the lights,
  the materials, the colour-management look and view transform, the
  keyframes. Write the scene for any settings; facet's win.
- **Failures.** A script that raises fails with `script <base> failed:
  <Type>: <msg>` plus the last traceback lines — read the type first, then
  the tail. A still whose luminance is flat fails as a uniform image
  (`check the camera's framing and the lights`); the run records its mean
  and standard deviation.

## What facet verifies, and what it does not

`verify` needs no Blender: the PNG's size against the piece's width and
height, the MP4's width, height, frames and fps against the piece's. The
record carries the same thresholds plus the script's sha256, and the asset's
`inputs` list the script, so the core hashes it. Nothing checks the look:
the framing, the light, the materials, the move. Aesthetics are the
script's, which is to say yours — `preview` names the asset, the size, the
engine and the script, and the viewer shows the file.

## Unsandboxed

The script runs **unsandboxed with the person's permissions**, like any code
you write: it can read and write what the person can. Treat it like a shell
command, not like a prompt — review `build.py` before you run it, keep it
beside the piece so the review is on the record, and never fetch remote code
into the scene at render time.
