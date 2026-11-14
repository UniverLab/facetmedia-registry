# Captions and piece shapes for `acestep.bed`

One `.toml` is one track. The caption is the whole style control: it is
English, and the runner always sends `lyrics = "[Instrumental]"` with
`task_type = "text2music"`, so there is no separate instrumental switch to
set in a piece.

## Piece shape

```toml
[inputs]
caption = "English style caption, acoustic instruments, ending in the no-drums line"
name = "baroque-allegro"
duration = 30
```

- `caption` — English, required. Ask for acoustic instruments and end with
  `No drums, no percussion, no bass beat, no synthesizers`. A caption naming
  a voice is refused by the runner: this package is instrumental only.
- `name` — required, matches `[a-z0-9][a-z0-9-]*`; the runner renames the
  randomly-named server output to `<name>.wav`.
- `duration` — required, seconds of music, at most 30.

## Approved: `baroque-allegro`

Major key, joyful and lively; approved by the person as a background bed on
2026-10-13. Ships as `examples/baroque-allegro.toml` and `.wav`.

```toml
[inputs]
caption = "Lively, joyful Baroque chamber orchestra piece in the style of a Vivaldi allegro. Bright strings playing fast staccato and spiccato runs, harpsichord continuo, playful solo violin and flute melodies. Energetic, festive and elegant. Acoustic instruments only. No drums, no percussion, no bass beat, no synthesizers, no electronic sounds."
name = "baroque-allegro"
duration = 30
```

The lab's piece also carried `bpm = 132`, `keyscale = "G major"`,
`timesignature = "4"`, `seed = 22` and `config_path = "acestep-v15-turbo"`.
Those are not `acestep.bed` inputs; the caption is what reproduces the style.

## Approved: `romantic-nocturne`

Minor key, melancholic; approved by the person as a background bed on
2026-10-13. Ships as `examples/romantic-nocturne.toml` and `.wav`.

```toml
[inputs]
caption = "Melancholic classical piece for solo piano and string quartet, Romantic era style. Slow tempo, expressive legato violin melody over gentle piano arpeggios and sustained cello notes. Intimate, sorrowful, reflective. Acoustic instruments only. No drums, no percussion, no bass beat, no synthesizers, no electronic sounds."
name = "romantic-nocturne"
duration = 30
```

The lab's piece also carried `bpm = 66`, `keyscale = "D minor"`,
`timesignature = "3"`, `seed = 21` and `config_path = "acestep-v15-turbo"`.

## The no-drums line

```
No drums, no percussion, no bass beat, no synthesizers
```

Both approved captions add `, no electronic sounds` after it. Without the
line the model loads bass and kick, and about 60 % of the energy falls below
120 Hz; with it the approved acoustic classics came in at 2.5-16 % low
energy. Never ask for sung music: the lab discarded it forever, and the
runner refuses a caption that names a voice.
