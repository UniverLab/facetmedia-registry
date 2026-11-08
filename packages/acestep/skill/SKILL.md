---
name: acestep
description: Instrumental background beds from an English caption with ACE-Step 1.5, at most 30 s, checked by duration and peak.
---
# ACE-Step 1.5

Compose an instrumental bed from one English caption with ACE-Step 1.5 (MIT,
commercial use allowed). The bed sits under narration, so it is always
instrumental: a caption that asks for voice is refused.

## When to use

- `acestep.bed` for a background bed under narration: an acoustic style
  named in English, at most 30 s per piece. About 50 s to render a 30 s
  track on the reference GPU.
- Ask for acoustic instruments and end the caption with `No drums, no
  percussion, no bass beat, no synthesizers`: without that guidance the
  model loads bass and kick with about 60 % of the energy below 120 Hz.
- Never for sung music. The lab discarded sung music forever; the runner
  refuses a caption naming a voice, singer, vocals, lyrics, choir, rap,
  chant or speech.

## Pieces

One bed per piece: a `caption`, a `name` and a `duracion` in seconds.

```toml
[inputs]
caption = "Lively, joyful Baroque chamber orchestra piece in the style of a Vivaldi allegro. Bright strings playing fast staccato and spiccato runs, harpsichord continuo, playful solo violin and flute melodies. Acoustic instruments only. No drums, no percussion, no bass beat, no synthesizers."
name = "clasica-alegre"
duracion = 30
```

`name` matches `[a-z0-9][a-z0-9-]*` and writes `<name>.wav` beside the piece.
`duracion` is at most 30.

## Judging the result

`verify` opens the WAV and passes when its duration is within 1 s of
`duracion` and its peak sits above -40 dBFS, reporting both. The run
normalises the bed to -16 LUFS and records `duration_s`, `sample_rate_hz`,
`lufs` and `peak_dbfs`; the preview serves the waveform and loudness in the
audio viewer. The lab's approved reference tracks are `clasica-alegre.wav`
and `clasica-melancolica.wav` (not shipped): acoustic, no percussion,
2.5-16 % low energy. `examples/clasica-alegre.toml` is the approved
allegro caption as a piece.

## Pitfalls

- One heavy job at a time: the package needs the GPU exclusively, 16 GB of
  RAM and 24 GB of disk.
- The checkpoints come from the server on first start; a missing checkout
  or checkpoint names `facet pull acestep` as its fix.
- A caption without the no-drums guidance comes back with a bass and kick
  under 120 Hz; the caption decides the style.
