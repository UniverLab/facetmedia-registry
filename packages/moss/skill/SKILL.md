---
name: moss
description: Described sound effects with MOSS-SoundEffect v2 on the staged CPU/GPU path, normalised to a loudness target.
---
# MOSS-SoundEffect v2

Generate a sound effect from an English description with MOSS-SoundEffect
v2 (**Apache-2.0**, commercial use allowed). One capability, `moss.sfx`,
writing the `audio` kind at 48 kHz mono.

## When to use

- `moss.sfx` for a described effect — an ambience bed, a notification
  chime, a UI click, a whoosh — described in English, at most 30 s.
- The machine needs an NVIDIA GPU and about 19 GB of RAM: the model loads
  on the CPU and only the active stage moves to the card, because a full
  GPU load (~9 GB) does not fit the 8 GB card. One heavy job at a time.
- About 40 s per effect at the default 100 steps, whatever its length: the
  pipeline always denoises 30 s of audio and trims to `seconds`. Fewer
  `steps` are faster but rougher.
- `facet pull moss` fetches MOSS-TTS at the pinned commit (about 15 MB of
  code) plus the model (about 11 GB): never clone it by hand. `MOSS_DIR`
  is only for a manual run outside facet.

## Pieces

One effect per piece: a `description` in English, `seconds` up to 30, a
`name` matching `[a-z0-9][a-z0-9-]*` and an optional `target-lufs`.

```toml
[inputs]
description = "Rain falling on a window with distant thunder, steady and soft"
seconds = 8
name = "lluvia-ventana"
steps = 100
guidance = 4.0
seed = 0
```

`name` writes `<name>.wav` beside the piece. `target-lufs` defaults to
-23.0, the level for beds under voice; pass a louder target (up to -10)
for hits that must cut through.

The last three lines are optional and show the defaults: `steps` (1 to
200) is sent as `num_inference_steps` and fewer steps are faster but
rougher — the ~40 s per effect is the 100-step figure; `guidance` (0 to
20) is sent as `cfg_scale`, 0 being no guidance; `seed` (0 or more) makes
the effect reproducible, the same seed giving the same effect. The asset
records the values used in `params` and the seed in `seed`.

## Judging the result

`verify` measures the WAV's integrated loudness and passes while it sits
within 1 LU of `target-lufs`. A transient-heavy effect may sit below the
target, held at the -1 dBFS peak ceiling; `verify` accepts it and records
`peak_limited: true`. No limiter is added. The run normalises every
effect to that target and records `duration_s`, `sample_rate_hz`, `lufs`,
`peak_dbfs` and `peak_limited`; `facet preview <name>.wav --json` writes
the waveform and momentary loudness for the audio viewer.

Event count is unreliable: asking for one click can give two, so listen
to the WAV or read the spectrogram — loudness and duration verify, timbre
is judged by ear.

Seven effects are approved on the reference machine: `cafe-ambiente`,
`campana-notificacion`, `clic-interfaz`, `lluvia-ventana`,
`pagina-libro`, `pasos-madera` and `whoosh-transicion`.

Each approved effect ships as a runnable piece with its WAV:
`examples/cafe-ambiente.toml`, `examples/campana-notificacion.toml`,
`examples/clic-interfaz.toml`, `examples/lluvia-ventana.toml`,
`examples/pagina-libro.toml`, `examples/pasos-madera.toml` and
`examples/whoosh-transicion.toml`. The seven descriptions, and the piece
shape, are in
[references/descriptions.md](references/descriptions.md).

## Pitfalls

- Descriptions are in English; the pipeline appends `duration: <s>s`
  itself, so do not write the duration into the text.
- `seconds` above 30 is refused: the model generates at most 30 s.
- If MOSS stops convincing, the fallback is a CC0 sound-effects library;
  Stable Audio Open stays out (licence plus acceptance).
