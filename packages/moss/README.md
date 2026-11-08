# moss — MOSS-SoundEffect v2

Described sound effects with
[OpenMOSS/MOSS-SoundEffect-v2.0](https://huggingface.co/OpenMOSS-Team/MOSS-SoundEffect-v2.0)
(**Apache-2.0**), ported from the lab's `tools/efectos.py`. One capability,
`moss.efecto`, writing 48 kHz mono WAVs.

## The code comes from a pinned clone

The pipeline code is `moss_soundeffect_v2` inside the MOSS-TTS clone —
there is no `engine.server`, the clone ships no HTTP server. The runner
puts `MOSS_DIR` (default `~/Projects/open-source/MOSS-TTS`, like the lab's
`tools/efectos.py`) on `sys.path` and imports the pipeline in-process.
`doctor` checks the clone exists and its HEAD is the pinned commit
(`934d682`).

## The memory rule

A full GPU load of this model needs ~9 GB and spills into shared memory
on the 8 GB card, taking minutes per effect. The runner therefore never
does one: the pipeline loads on the CPU (`from_pretrained(device="cpu")`,
DiT tensors cast to bf16) and only the active stage moves to the GPU
(`engine.device = "cuda"`, `vram_management_enabled = True`). Before
loading, `run` estimates the staged peak (~4 GB, the bf16 text encoder
stage) and refuses with a plain error — reported as `runner_failed` — when
it cannot fit the card. `doctor` checks the GPU, the ~10 GB of RAM the CPU
stage needs, the pinned clone and the model files.

## The normalization rule

Every effect is normalised to its declared `target-lufs` (default **-23**,
the level for beds under voice; pass a louder target up to -10 for hits).
`verify` passes while the measured integrated loudness sits within
`lufs_tol = 1.0` LU of the target.

## The event-count caveat

The model does not count events: asking for one click can give two.
Loudness, duration and peak verify; the count and the timbre are judged
by listening or by reading the spectrogram.

## Approved effects

Seven effects were approved on the reference machine, with
`espectrogramas.png` in the lab's `projects/prueba-efectos/`:

- `cafe-ambiente`
- `campana-notificacion`
- `clic-interfaz`
- `lluvia-ventana`
- `pagina-libro`
- `pasos-madera`
- `whoosh-transicion`

## Fallback

Stable Audio Open stays out (licence plus acceptance). If MOSS stops
convincing, the fallback is a CC0 sound-effects library.
