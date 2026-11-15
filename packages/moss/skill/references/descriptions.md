# Descriptions and piece shapes for `moss.sfx`

One `.toml` is one effect. The description is the whole style control: it is
English, and the pipeline appends `duration: <seconds>s` itself, so the
length never goes into the text.

## Piece shape

```toml
[inputs]
description = "English effect description, no duration in the text"
name = "coffee-morning"
seconds = 12
steps = 100
guidance = 4.0
seed = 0
```

- `description` — English, required. Describe the sound, not the duration:
  the runner appends `duration: <seconds>s` itself.
- `name` — required, matches `[a-z0-9][a-z0-9-]*`; the runner writes
  `<name>.wav` at 48 kHz mono.
- `seconds` — required, seconds of effect, at most 30; the pipeline always
  denoises 30 s and trims.
- `target-lufs` — optional, defaults to -23.0 for beds under voice; pass a
  louder target (up to -10) for hits that must cut through.
- `steps` — optional, 1 to 200, default 100, sent as
  `num_inference_steps`; fewer steps are faster but rougher, and the
  ~40 s per effect is the 100-step figure.
- `guidance` — optional, 0 to 20, default 4.0, sent as `cfg_scale`; 0 is a
  valid value and means no guidance.
- `seed` — optional, 0 or more, default 0, passed to the pipeline: the same
  seed gives the same effect. The asset records the values used in `params`
  and the seed used in `seed`.

A piece that sets none of the last three generates exactly as it did
before they existed: the values above are the defaults, so the seed is
reproducible whenever one is pinned.

## Description anatomy

Material, action, setting — one scene in one sentence:

1. **material** — what the sound is made of (`rain`, `paper`, `wood`,
   `glass`, `a brass bell`);
2. **action** — the verb that sets it moving (`drumming`, `rustling`,
   `creaking`, `struck`);
3. **setting** — where it happens, which decides the room and the distance
   (`on a tin roof`, `in a quiet room`, `outdoors, far away`).

`rain drumming on a tin roof` has all three; `whoosh` has none. The
approved effects below all follow the shape, and the strongest ones name
the physical source instead of the abstract label: a bell struck, a button
pressed, a door pulled shut.

Two rules that follow from it:

- **One scene per effect.** Two scenes in one description give a blur
  rather than a transition; if the piece needs both sounds, use two pieces.
- **Never write a duration.** The pipeline prepends the duration tag the
  model was trained on, and a number in the prose competes with it.

## The five families

The model was trained across five kinds of sound, and they do not hit
equally:

| Family | Examples | Watch for |
| --- | --- | --- |
| Natural | rain, wind, fire, water, leaves | the room in the text decides the distance |
| Urban | streets, engines, doors, appliances | name the vehicle or appliance, not `city noise` |
| Animals and creatures | birds, insects, a large animal moving | species and size change the pitch |
| Human actions | footsteps, typing, page turns, cloth | the material under the action is the cue |
| Short musical or percussive | chimes, clicks, hits, single notes | weakest of the five: little material to model, so expect more seeds |

The last family still works — `bell-alert` and `ui-click` are approved — but
it is where a description needs the most help from the physical source and
where a second or third seed is the normal cost.

## Draft, then final

Render order for a new effect: draft at a low `steps` (30 to 50) until the
wording is right, then render the final at 100. The cost is about 40 s per
effect at 100 steps whatever the length, so a draft costs a fraction of a
final and the wording is what changes between tries. Once the wording is
settled, pin `seed` if the take must be reproducible.

## Approved: `coffee-morning`

Morning cafe ambience, approved by the person on 2026-10-13. Ships as
`examples/coffee-morning.toml` and `.wav`.

```toml
[inputs]
description = "Ambience of a quiet cafe in the morning, indistinct distant chatter, cups and saucers clinking, an espresso machine hissing"
name = "coffee-morning"
seconds = 12
```

## Approved: `bell-alert`

A rising two-tone notification chime, approved by the person on 2026-10-13.
Ships as `examples/bell-alert.toml` and `.wav`.

```toml
[inputs]
description = "A bright, pleasant notification chime, two short bell tones rising in pitch"
name = "bell-alert"
seconds = 2
```

## Approved: `ui-click`

A single soft UI click, approved by the person on 2026-10-13. Ships as
`examples/ui-click.toml` and `.wav`.

```toml
[inputs]
description = "A single soft, clean user interface click, short and subtle, like tapping a modern touchscreen button"
name = "ui-click"
seconds = 1
```

## Approved: `rain-window`

Steady rain on a window at night, approved by the person on 2026-10-13.
Ships as `examples/rain-window.toml` and `.wav`.

```toml
[inputs]
description = "Gentle steady rain falling on a window pane at night, soft drops on glass, distant rolling thunder, calm ambience"
name = "rain-window"
seconds = 12
```

## Approved: `page-turn`

Close-up page turns, approved by the person on 2026-10-13. The lab piece
omitted `seconds`, so it took the lab default of 3. Ships as
`examples/page-turn.toml` and `.wav`.

```toml
[inputs]
description = "Close-up sound of turning the pages of a paper book, crisp paper rustle, quiet room"
name = "page-turn"
seconds = 3
```

## Approved: `wood-steps`

Slow footsteps on old boards, approved by the person on 2026-10-13. Ships as
`examples/wood-steps.toml` and `.wav`.

```toml
[inputs]
description = "Slow footsteps of one person walking on an old wooden floor, boards creaking under the weight, indoors"
name = "wood-steps"
seconds = 6
```

## Approved: `whoosh-sweep`

A fast cinematic whoosh, approved by the person on 2026-10-13. Ships as
`examples/whoosh-sweep.toml` and `.wav`.

```toml
[inputs]
description = "A fast cinematic whoosh transition, a swish of air passing quickly from left to right, clean, no music"
name = "whoosh-sweep"
seconds = 2
```

