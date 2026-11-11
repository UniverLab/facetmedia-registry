# Descriptions and piece shapes for `moss.sfx`

One `.toml` is one effect. The description is the whole style control: it is
English, and the pipeline appends `duration: <seconds>s` itself, so the
length never goes into the text.

## Piece shape

```toml
[inputs]
description = "English effect description, no duration in the text"
name = "cafe-ambiente"
seconds = 12
```

- `description` — English, required. Describe the sound, not the duration:
  the runner appends `duration: <seconds>s` itself.
- `name` — required, matches `[a-z0-9][a-z0-9-]*`; the runner writes
  `<name>.wav` at 48 kHz mono.
- `seconds` — required, seconds of effect, at most 30; the pipeline always
  denoises 30 s and trims.
- `target-lufs` — optional, defaults to -23.0 for beds under voice; pass a
  louder target (up to -10) for hits that must cut through.

`moss.sfx` declares no seed input: the lab pieces carried one, but a
reproducible piece here is the description, the length and the loudness
target.

## Approved: `cafe-ambiente`

Morning cafe ambience, approved by the person on 2026-10-13. Ships as
`examples/cafe-ambiente.toml` and `.wav`.

```toml
[inputs]
description = "Ambience of a quiet cafe in the morning, indistinct distant chatter, cups and saucers clinking, an espresso machine hissing"
name = "cafe-ambiente"
seconds = 12
```

The lab piece also carried seed; it is not an input here.

## Approved: `campana-notificacion`

A rising two-tone notification chime, approved by the person on 2026-10-13.
Ships as `examples/campana-notificacion.toml` and `.wav`.

```toml
[inputs]
description = "A bright, pleasant notification chime, two short bell tones rising in pitch"
name = "campana-notificacion"
seconds = 2
```

The lab piece also carried seed; it is not an input here.

## Approved: `clic-interfaz`

A single soft UI click, approved by the person on 2026-10-13. Ships as
`examples/clic-interfaz.toml` and `.wav`.

```toml
[inputs]
description = "A single soft, clean user interface click, short and subtle, like tapping a modern touchscreen button"
name = "clic-interfaz"
seconds = 1
```

The lab piece also carried seed; it is not an input here.

## Approved: `lluvia-ventana`

Steady rain on a window at night, approved by the person on 2026-10-13.
Ships as `examples/lluvia-ventana.toml` and `.wav`.

```toml
[inputs]
description = "Gentle steady rain falling on a window pane at night, soft drops on glass, distant rolling thunder, calm ambience"
name = "lluvia-ventana"
seconds = 12
```

The lab piece also carried seed; it is not an input here.

## Approved: `pagina-libro`

Close-up page turns, approved by the person on 2026-10-13. The lab piece
omitted `seconds`, so it took the lab default of 3. Ships as
`examples/pagina-libro.toml` and `.wav`.

```toml
[inputs]
description = "Close-up sound of turning the pages of a paper book, crisp paper rustle, quiet room"
name = "pagina-libro"
seconds = 3
```

The lab piece also carried seed; it is not an input here.

## Approved: `pasos-madera`

Slow footsteps on old boards, approved by the person on 2026-10-13. Ships as
`examples/pasos-madera.toml` and `.wav`.

```toml
[inputs]
description = "Slow footsteps of one person walking on an old wooden floor, boards creaking under the weight, indoors"
name = "pasos-madera"
seconds = 6
```

The lab piece also carried seed; it is not an input here.

## Approved: `whoosh-transicion`

A fast cinematic whoosh, approved by the person on 2026-10-13. Ships as
`examples/whoosh-transicion.toml` and `.wav`.

```toml
[inputs]
description = "A fast cinematic whoosh transition, a swish of air passing quickly from left to right, clean, no music"
name = "whoosh-transicion"
seconds = 2
```

The lab piece also carried seed; it is not an input here.
