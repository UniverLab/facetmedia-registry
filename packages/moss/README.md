# moss — MOSS-SoundEffect v2

Described sound effects with
[OpenMOSS/MOSS-SoundEffect-v2.0](https://huggingface.co/OpenMOSS-Team/MOSS-SoundEffect-v2.0)
(**Apache-2.0**). One capability, `moss.sfx`, writing 48 kHz mono WAVs.

## The code comes from a pinned source checkout

The pipeline code is `moss_soundeffect_v2` inside the MOSS-TTS source
checkout — there is no `engine.server`, the checkout ships no HTTP server.
`facet pull moss` clones MOSS-TTS at the pinned commit (`934d682`, about
15 MB of code) beside the model (about 11 GB): never clone it by hand.
The runner imports the pipeline in-process from `FACET_SOURCE_DIR`, and
`doctor` checks `moss_soundeffect_v2/` is there. `MOSS_DIR` remains only
for a manual run outside facet.

## The memory rule

A full GPU load of this model needs ~9 GB and spills into shared memory
on the 8 GB card, taking minutes per effect. The runner therefore never
does one: the pipeline loads on the CPU (`from_pretrained(device="cpu")`,
DiT tensors cast to bf16) and only the active stage moves to the GPU
(`engine.device = "cuda"`, `vram_management_enabled = True`). Before
loading, `run` estimates the staged peak (~4 GB, the bf16 text encoder
stage) and refuses with a plain error — reported as `runner_failed` — when
it cannot fit the card. `doctor` checks the GPU, the ~10 GB of RAM the CPU
stage needs, the pinned source checkout and the model files.

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

Seven effects were approved on the reference machine:

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
