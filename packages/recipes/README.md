# recipes

Complete-piece recipes that chain packages that already exist: `facet run
recipes.plan` reads the in-package `recipes.json` and writes an ordered plan
beside the piece, one step per capability to run, with its handoff files and
its verification. It runs no tool and holds no model — the whole package is
stdlib. The skill teaches the same recipes as prose; this capability answers
the same knowledge as data.

## When to use a recipe

A **complete piece** is more than one asset: a video needs a voice, a music
bed, a mix, a transcript, subtitles and a composition; an architectural
render needs a solid, assets, a photo and a deck. A recipe names the packages
to combine, the order to run them and what to check after each step. Use one
when you are building a whole piece; run a single package's own capability
when you need one asset.

## The four recipes

| Recipe | What it builds | Steps |
|--------|----------------|-------|
| `explainer-video` | A narrated explainer video: voice, music bed, normalize and mix, transcript, subtitles, HyperFrames composition | `voicestudio.speak` · `acestep.bed` · `ffmpeg.normalize` · `ffmpeg.mix` · `whisper.transcribe` · `whisper-subs.subtitles` · `hyperframes.narrated` |
| `architecture-render` | An architectural render with people: a CAD solid, Poly Haven assets, a daylight photo with people and cars, a one-page deck | `cad.solid` · `blender.assets` · `blender.photo` · `deck.page` |
| `voice-material` | Voiced material with music: narration, a music bed, a slide deck | `kokoro.speak` · `acestep.bed` · `deck.slides` |
| `tool-demo` | A tool demo: a recorded terminal demo and a slide deck | `demostage.demo` · `deck.slides` |

`kokoro.speak` is the documented voice alternative inside
`explainer-video`; the plan data names exactly one id per step.

## Piece fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `recipe` | enum | yes | `explainer-video`, `architecture-render`, `voice-material` or `tool-demo` |

The runner writes `<recipe>.plan.json` beside the piece (`--out` overrides
the directory):

```json
{
  "recipe": "voice-material",
  "summary": "Voiced material with music: narration from text, a music bed, and a slide deck.",
  "steps": [
    {
      "step": 1,
      "capability": "kokoro.speak",
      "handoff": "voz.wav (clip, voice ef_dora, language es)",
      "verify": "Transcribe the voice: verify measures the word error rate (wer_max 0.05)."
    }
  ]
}
```

## Judging the result

`verify` re-parses the plan and reports `steps`, `packages`, `ordered` (step
numbers run 1..n) and `complete` (every step carries a capability, a handoff
and a verification); the manifest threshold is `steps_min = 1`. That judges
the plan's shape, not the piece: each step's own `verify` — transcribe the
voice, look at the PNG, check the MP4 — is the real judgement after the run.

`preview` writes the generic viewer's fields (`recipe`, `steps`,
`packages`) with a summary naming the recipe and its step count. The runner
is stdlib and receives no registry path, so it never resolves capability ids
against the registry; the repository tests do that.
