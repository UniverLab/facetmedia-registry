---
name: voicestudio
description: Narrate Spanish through a started VoiceStudio backend on the voxcpm2 or omnivoice engine, verifying every clip by transcription and regenerating it over 5 % WER.
---
# VoiceStudio

Voice text to WAV clips through a VoiceStudio backend. Two engines speak
the `narradora` clone: `voxcpm2` (Apache-2.0, the default) and `omnivoice`
(CC-BY-NC, the approved narrator engine). `voicestudio.speak` writes the
`audio` kind; `voicestudio.clone` speaks a person's own local profile on the
`cosyvoice` engine (Apache-2.0).

## When to use

- When the lab's narrator voice is the point. `omnivoice` is the engine the
  lab picked for naturalness; `voxcpm2` is the commercial-safe default.
- When you need narration already verified: the runner transcribes every
  clip with faster-whisper and regenerates the bad ones with another seed.
- Needs a backend that is already running (its start command lives in the
  package README). For CPU-only narration without a backend, use `kokoro.speak`.
- When a person's own clone is the point: `voicestudio.clone` takes a local
  profile id and `cosyvoice`, only with the owner's permission. Two voices are
  two pieces (narrator on `omnivoice`, person on `cosyvoice`).

## Pieces

Two clips, the piece defaults once:

```toml
[inputs]
voice = "narradora"
model = "omnivoice"
language = "es"

[[inputs.clip]]
name = "intro"
text = "En este laboratorio probamos una voz en español."
seed = 7

[[inputs.clip]]
name = "cierre"
text = "La hipótesis quedó verificada."
seed = 11
```

Run a piece with `facet run voicestudio.speak <piece.toml> --out build/`;
every clip becomes `<name>.wav`. Each clip carries its own `seed` — it is
required, because the verification loop restarts a failed clip with `seed + 1`.

The `model` value is the manifest model id, and the core gates the piece on
it: only `omnivoice` pieces require the licence. The lab's original tool
runs the same pattern: `python3 tools/voz.py <pieza>.toml`, with
`projects/prueba-voz/narradora/voz.toml` as the reference piece
(`voice = "narradora"`, `model = "omnivoice"`, two clips). This package is
that invocation ported to a facet capability.

## The `omnivoice` licence

The OmniVoice weights are **CC-BY-NC** and **commercial use is forbidden**.
Record the acceptance once before the first `omnivoice` piece:

```sh
facet license accept omnivoice
```

An `omnivoice` piece with no acceptance fails in the core with
`license_not_accepted` (exit 4) and that hint; a `voxcpm2` piece runs with
nothing accepted. The runner never re-checks the licence. Accepting makes
the person who runs facet responsible for complying with the terms.

## Judging the result

The runner itself verifies: after synthesis it transcribes each clip with
faster-whisper `small` and measures the word error rate against the text.
A clip over `wer_max = 0.05` prints `REGENERATE` and is rewritten with
`seed + 1` (three tries per clip, the last attempt kept). The record
reports the final `seed` and the number of attempts, so a clip that kept
its first seed passed on first hearing.

## Pitfalls

- **The first second can sound robotic.** OmniVoice (and voxcpm2) sometimes
  start sharp or robotic on the opening second. Listen to the clip; a
  re-render with another seed usually settles it. No measured flags exist
  for this — judge it by ear.
- **`/health` is not readiness.** The backend answers `/health` ok while it
  is still importing the engine in the background; a first request in that
  window fails with `omnivoice package missing: cannot import name …`. The
  runner waits for `/model/status` to say `ready` before the first clip.
- **One engine per piece.** The piece-level `model` is the only model field
  and an entry cannot override it — two voices belong in two files that
  interleave later in HyperFrames. Two engines also do not fit in 8 GB.
- **The backend is user-started for now.** `facet run` waits for a backend
  at `http://127.0.0.1:3900` (or `$VOICESTUDIO_URL`) and does not start
  one. `facet doctor voicestudio --json --full` prints the start command.
- **Cloned profiles live on the person's machine** (the backend's omnivoice
  store) and are never bundled. A missing `narradora` profile is recreated
  from the host with `POST /profiles`; the doctor names the recipe.
- **Verification is always on.** There is no skip field in the piece format
  and no flag the runner would accept. A clip is heard back every time.
