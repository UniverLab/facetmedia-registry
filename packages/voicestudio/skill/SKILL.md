---
name: voicestudio
description: Narration in Spanish through a started VoiceStudio backend with the engine voxcpm2, every clip transcribed back and regenerated while its WER passes 5 %.
---
# VoiceStudio

Voice text to WAV clips through a VoiceStudio backend (omnivoice) —
the `narradora` clone on the `voxcpm2` engine, Apache-licensed and
commercial-safe. One capability, `voicestudio.speak`, writing the
`audio` kind.

## When to use

- When the lab's commercial-safe voice is the point: the default engine
  `voxcpm2` is Apache-2.0 and the default voice is the `narradora` clone.
- When you need narration already verified: the runner transcribes every
  clip with faster-whisper and regenerates the bad ones with another seed.
- Needs a backend that is already running (its start command lives in the
  package README). For CPU-only narration without a backend, use `kokoro.speak`.

## Pieces

Two clips, the piece defaults once:

```toml
[inputs]
voice = "narradora"
model = "voxcpm2"
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

## Judging the result

The runner itself verifies: after synthesis it transcribes each clip with
faster-whisper `small` and measures the word error rate against the text.
A clip over `wer_max = 0.05` prints `REGENERATE` and is rewritten with
`seed + 1` (three tries per clip, the last attempt kept). The record
reports the final `seed` and the number of attempts, so a clip that kept
its first seed passed on first hearing.

## Pitfalls

- Exactly one engine per piece: the piece-level `model` is the only model
  field, and an entry cannot override it — two voices belong in two files
  that interleave later in HyperFrames. Two engines also do not fit in 8 GB.
- The backend is user-started for now: `facet run` waits for a backend at
  `http://127.0.0.1:3900` (or `$VOICESTUDIO_URL`), and it does not start
  one. `facet doctor voicestudio --json --full` prints the start command.
- Cloned profiles live on the person's machine (the backend's omnivoice
  store) and are never bundled by the registry. A missing `narradora`
  profile is recreated from the host with `POST /profiles`; the doctor
  names the recipe.
- Verification is always on: there is no skip field in the piece format
  and no flag the runner would accept. A clip is heard back every time.
