---
name: moss
description: Described sound effects with MOSS-SoundEffect v2 on the staged CPU/GPU path, normalised to a loudness target.
---
# MOSS-SoundEffect v2

Generate a sound effect from an English description with MOSS-SoundEffect
v2 (**Apache-2.0**, commercial use allowed). One capability, `moss.efecto`,
writing the `audio` kind at 48 kHz mono.

## When to use

- `moss.efecto` for a described effect — an ambience bed, a notification
  chime, a UI click, a whoosh — described in English, at most 30 s.
- The machine needs an NVIDIA GPU and about 19 GB of RAM: the model loads
  on the CPU and only the active stage moves to the card, because a full
  GPU load (~9 GB) does not fit the 8 GB card. One heavy job at a time.
- About 40 s per effect whatever its length: the pipeline always denoises
  30 s of audio and trims to `segundos`.

## Pieces

One effect per piece: a `descripcion` in English, `segundos` up to 30, a
`nombre` matching `[a-z0-9][a-z0-9-]*` and an optional `target-lufs`.

```toml
[inputs]
descripcion = "Rain falling on a window with distant thunder, steady and soft"
segundos = 8
nombre = "lluvia-ventana"
```

`nombre` writes `<name>.wav` beside the piece. `target-lufs` defaults to
-23.0, the level for beds under voice; pass a louder target (up to -10)
for hits that must cut through.

## Judging the result

`verify` measures the WAV's integrated loudness and passes while it sits
within 1 LU of `target-lufs`. The run normalises every effect to that
target and records `duration_s`, `sample_rate_hz`, `lufs` and
`peak_dbfs`; `facet preview <name>.wav --json` writes the waveform and
momentary loudness for the audio viewer.

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
- `segundos` above 30 is refused: the model generates at most 30 s.
- If MOSS stops convincing, the fallback is a CC0 sound-effects library;
  Stable Audio Open stays out (licence plus acceptance).
