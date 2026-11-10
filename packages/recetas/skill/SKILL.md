---
name: recetas
description: Complete-piece recipes that chain existing packages into ordered plans — narrated explainer video, architectural render with people, voiced material with music, and tool demo.
---
# recetas

`recetas.plan` turns a complete piece into an ordered plan: one step per
capability to run, with its handoff files and its verification. It chains
packages that already exist in this registry and writes
`<receta>.plan.json` beside the piece — run each step with `facet run
<capability> <piece.toml>` in the order the plan gives, carrying each
step's files into the next. The plan is data, not a model: the package is
stdlib only and never runs a tool itself.

## When to use

- You are building a whole piece, not one asset, and need to know which
  packages to combine and in what order: a narrated explainer video, an
  architectural render with people, voiced material with music, or a tool
  demo.
- You want the same knowledge as data for a script or an agent: `plan`
  answers with the ordered steps, the handoff files and what to verify.
- Not for a single asset: run that package's own capability directly.
- Not for a recipe that is not listed: the enum is closed, and a plan only
  chains capabilities that already exist.

## Pieces

```toml
[inputs]
receta = "video-explicativo"
```

The input is `receta`, one of the four names below. The runner reads the
in-package `recipes.json` and writes `<receta>.plan.json` beside the piece
(`--out` overrides the directory). Each step is `{ step, capability,
handoff, verify }`: the capability id to run, the files it hands over and
how to judge them.

### video-explicativo — the narrated explainer video

1. `voicestudio.speak` → `voz.wav`. Verify: transcribe the voice and
   measure the word error rate (`wer_max` 0.05). Kokoro is the documented
   voice alternative here: `kokoro.speak` → `voz.wav`, same verification.
2. `acestep.bed` → `cama.wav`. Verify: probe duration and peak.
3. `ffmpeg.normalize` → `voz-normalizada.wav`, from `voz.wav` with
   `target-lufs` -16.0 and `true-peak-db` -1.5. Verify: integrated loudness
   at -16 LUFS.
4. `ffmpeg.mix` → `mezcla.wav`, voice `voz-normalizada.wav` over bed
   `cama.wav` with `ducking` true, `duck-db` -12.0 and `target-lufs` -16.0.
   `mezcla.wav` is the stand-alone audio deliverable, for a podcast or
   audio-only use, and is not an input of step 7.
   Verify: integrated loudness at -16 LUFS.
5. `whisper.transcribe` → `guion.txt` + `guion.srt` + `guion.json`, from
   `voz-normalizada.wav`. Verify: confidence and no-speech share.
6. `whisper-subs.subtitulos` → `guion.srt`, from `origen` `guion.json`.
   Verify: at least one cue, monotonic and non-overlapping.
7. `hyperframes.narrado` → `narrado.mp4`, with composition `narrado/`,
   voice `voz-normalizada.wav`, music `cama.wav` and subtitles `guion.srt`.
   Step 7 places the voices over `cama.wav` at `volumen-musica`; `mezcla.wav`
   is not an input of this step.
   Verify: check the MP4 with an ffprobe probe.

### render-arq — the architectural render with people

1. `cad.solid` → `estudio.step` + `estudio.stl` + `estudio.svg` +
   `estudio.glb`, from a CadQuery `estudio.py`. Verify: volume and bounding
   box.
2. `blender.assets` → `estudio.assets.json`. Verify: the receipt's files
   are all present.
3. `blender.foto` → `estudio-foto.png`, from model `estudio.glb`, plus
   `personas-blend` + `personas` and `autos-blend` + `autos`. The people and
   cars are `blender.foto` INPUTS, never capabilities of their own. Verify:
   look at the PNG — pixel size and the people in frame.
4. `deck.pagina` → `render-arq.pdf` + `page-01.png`, from
   `render-arq.html`. Verify: one PDF page and its page-01 PNG.

### material-voz — voiced material with music

1. `kokoro.speak` → `voz.wav`. Verify: transcribe the voice and measure the
   word error rate.
2. `acestep.bed` → `cama.wav`. Verify: probe duration and peak.
3. `deck.slides` → `material-voz.pdf` + `page-01.png`, from
   `material-voz.html`. Verify: the page count and the page-01 PNG.

### demo-herramienta — the tool demo

1. `demostage.demo` → `demo.gif` + `demo.svg`, from the `demo.toml` score.
   Verify: the gif probe and the svg size.
2. `deck.slides` → `demo-herramienta.pdf` + `page-01.png`, from
   `demo-herramienta.html`. Verify: the page count and the page-01 PNG.

## Judging the result

The plan file itself is `verify`-able: it re-parses the JSON and reports
`steps`, `packages`, `ordered` (the step numbers run 1..n with no gaps) and
`complete` (every step carries a capability, a handoff and a verification).
It passes only when there is at least one step, the order is intact and no
step is missing a fact.

Each step's own `verify` is the real judgement: transcribe the voice, look
at the PNG, check the MP4. Run the capability's `verify` after its `run`;
a passing plan says the recipe is well formed, not that the piece is good.

`facet preview <receta>.plan.json` writes
`<receta>.plan.json.preview.json` (generic viewer) with a summary naming the
recipe and its step count and the fields `receta`, `steps` and `packages`.

## Pitfalls

- The plan is a route, not a run: no capability is executed here, and a
  step that is skipped leaves the next one without its handoff.
- The enum is closed. A piece that is not one of the four names fails with
  a plain error naming the allowed recipes; do not invent a name.
- The plans name existing capabilities by id, and a recipe naming a missing
  capability fails its own test. Do not hand-edit the data file to add a
  step.
- People and cars are `blender.foto` inputs (`personas`, `autos`), not
  capabilities; there is no `blender.personas` or `blender.autos` to run.
- `hyperframes.narrado` reads SubRip: hand it `guion.srt`, not the
  whisper `.json` or `.vtt`.
