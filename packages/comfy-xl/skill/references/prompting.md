# Prompting the flows

The rules `SKILL.md` states, with the full skeletons behind them.

## Order

Every generative prompt runs the same order, because the model weighs the
start most:

1. **Subject** — what the picture is of.
2. **Action or style** — what it does, or the medium and palette.
3. **Context** — where it sits: interior, landscape, backdrop.
4. **Lighting** — one named source and its quality.
5. **Camera** — one lens and depth of field, if the shot has one.

Lighting is the heaviest lever on quality; a single named light beats a pile
of adjectives. One named lens is enough to fix the spatial feel; more than one
contradicts itself.

## Stills on `z-image`

25 steps at CFG 4 with `res_multistep` and `simple`. Guidance at 4 is real,
but the still entry exposes no negative input, so an "avoid X" clause has
nowhere to go: write the positive form of every avoidance. Realism cues that
work are `natural skin texture, visible pores`, one named light, and one named
lens such as `85mm, shallow depth of field`.

Explore cheaply: lock the seed, change exactly one dial — steps, CFG, or one
prompt clause — and compare. Run three seeds of the winner and keep the best.

## Edits on `qwen-image-edit`

Three parts, in one instruction:

- **Target** — the thing to change, named plainly.
- **Change** — the new state, with a concrete material or colour.
- **Preservation** — what must survive: cut, folds, lighting, position,
  background, camera framing.

Example: "Replace the jacket's colour with deep indigo. Preserve its cut,
folds, lighting and position. Keep the face, background and camera framing
unchanged."

One operation per run. If the first edit shifted something unrelated, restart
from the original reference; editing the damaged output compounds the drift.
The same rule applies to a sequence of entries: each starts from the piece's
`source`, never from another entry's result.

The flow runs 40 steps at CFG 4, `euler` with `simple` and shift 3.1, on a
latent derived from the scaled source. An edit inherits its geometry from the
reference; when you author your own edit graph, keep that property — an empty
latent at another size silently resynthesises a plastic-looking image instead
of failing.

facet refuses lettering anywhere in a prompt on purpose, so public advice
about quoting brand words and specifying `#RRGGBB` colours for typography does
not apply: the frames carry no type at all.

## Clips

The first frame already decides what appears; the prompt decides only how it
moves. Write: subject → motion → camera → scene.

- Name the movement with concrete verbs and a direction: "spins clockwise
  continuously", "steam rises in slow curls", "fog drifts left to right".
- One scene per clip. A second subject or a second action splits attention.
- Animate only what is visible in the uploaded frame; a transformation the
  frame cannot support (day into night, a new object appearing) fails.
- Keep the camera static unless the shot itself moves. A camera move belongs
  to HyperFrames with GSAP first — it is reproducible and takes seconds.
- Keep "static, still image, frozen, motionless, no movement" in a custom
  negative so the model does not invent motion elsewhere.
- On `wan22-i2v-14b-fast`, CFG 1 makes the negative inert: it is a draft for
  trying a movement, not evidence that the prompt was followed.
- `length` must be `4n+1` (49 ≈ 2 s, 121 ≈ 5 s); the Wan latent keeps one
  frame plus groups of four.
- Stay on the trained geometry: 1280 × 704 is where Wan was trained, and an
  off-distribution size samples recognisable subjects wrapped in artefacts
  instead of failing.
