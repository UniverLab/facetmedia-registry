---
name: voicestudio
description: Narrate Spanish through a facet-managed VoiceStudio backend on the voxcpm2 or omnivoice engine, verifying every clip by transcription and regenerating it over 5 % WER.
---
# VoiceStudio

Voice text to WAV clips through a VoiceStudio backend. Two engines speak
the `narradora` clone: `voxcpm2` (Apache-2.0, the default) and `omnivoice`
(CC-BY-NC, the approved narrator engine). `voicestudio.speak` writes the
`audio` kind; `voicestudio.clone` speaks a person's own local profile on the
`cosyvoice` engine (Apache-2.0). `voicestudio.profile` makes that local
profile from the person's own samples; its recipe lives in the package README.

## When to use

- When the lab's narrator voice is the point. `omnivoice` is the engine the
  lab picked for naturalness; `voxcpm2` is the commercial-safe default.
- When you need narration already verified: the runner transcribes every
  clip with faster-whisper and regenerates the bad ones with another seed.
- The backend is facet-managed: facet pulls and starts VoiceStudio for each
  run, with its data under `<FACET_HOME>/data/voicestudio/`. For CPU-only
  narration without a backend, use `kokoro.speak`.
- When a person's own clone is the point: `voicestudio.clone` takes a local
  profile id and `cosyvoice`, only with the owner's permission. Two voices are
  two pieces (narrator on `omnivoice`, person on `cosyvoice`).

## Engines

Three engines were compared on 2026-10-13 with the same reference and the
same texts:

| `model` | Words wrong | First second (ref ~244 Hz) | Rest | Per clip | VRAM | Licence |
| --- | --- | --- | --- | --- | --- | --- |
| `omnivoice` | 0 % | 285-345 Hz, sharp attack | 237-253 Hz | ~3 s | ~3.9 GB | CC-BY-NC |
| `voxcpm2` | 0 % | 236-262 Hz | 225-246 Hz | ~20 s | ~4.3 GB | Apache-2.0 |
| `cosyvoice` | 0-3 % | 245-274 Hz | 211-223 Hz, lower | ~15 s | ~1.7 GB | Apache-2.0 |

The verdict was OmniVoice for naturalness: it is the approved narrator
engine, and its first second is the sharpest. VoxCPM2 finishes nearly tied —
it starts robotic and then sounds natural — and CosyVoice sounds somewhat
Spanish-from-Spain with the narrator, so it is the second voice at most.
All three are kept. The `narradora` clone came from a
`female, middle-aged, low pitch` design; its first reference opened with
"Hola, ¿cómo vas?", which gave a sharp start (~370 Hz) and a skipped first
sentence in 2 of 3 takes, and cutting it to neutral speech fixed it.

The person's cloned voice was tested with the same texts on all three
engines: 0 % wrong words and the same pitch as the real voice (body of
135-144 Hz against 136-140 Hz). In rhythm, OmniVoice speaks 14 % faster,
VoxCPM2 19 % and CosyVoice 5 %. The person chose `cosyvoice` for their
voice; the narrator stays on `omnivoice`.

For a commercial piece, use `voxcpm2` or `cosyvoice` (Apache-2.0); OmniVoice
is CC-BY-NC and commercial use is forbidden. One `.toml`, one engine: two do
not fit together on the GPU. XTTS was discarded first and deleted: it
sounded Spanish-from-Spain and robotic.

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

Write proper nouns and brand names as they are pronounced in Spanish
(`fáset media`, not `facetMedia`): the verification transcribes the clip and a
name the engine reads letter by letter fails the word error rate, as
`facetMedia` -> `imedienta` did. Keep the real spelling for the subtitles.

The first clip on an engine installs it (about 8 GB for `voxcpm2`, 13 GB for
`cosyvoice`); `cosyvoice` needs `g++` on the machine to build.

Run a piece with `facet run voicestudio.speak <piece.toml> --out build/`;
every clip becomes `<name>.wav`. Each clip carries its own `seed` — it is
required, because the verification loop restarts a failed clip with `seed + 1`.

The `model` value is the manifest model id, and the core gates the piece on
it: only `omnivoice` pieces require the licence. The reference piece uses
`voice = "narradora"`, `model = "omnivoice"` and two clips.

## Cloning a voice

**Ask the owner first, always.** Cloning a person's voice needs their
permission: only clone from samples they gave you for it, and only with
their consent.

- The reference is 7-30 s of **neutral speech**. A reference that starts
  with a question or an exclamation contaminates the clone with a sharp
  attack and can skip the first sentence.
- To record it, read a script of neutral, declarative sentences (the
  original `guion-grabacion.md` is not shipped with this package).
- If a WAV arrives in stereo with one channel digitally silent, keep the
  live one (`ffmpeg -af "pan=mono|c0=c1"`); the profile runner repairs this
  case and prints the repair.
- The recipe for making the profile from local samples lives in the package
  README (`voicestudio.profile`).

Approved pieces to follow, by shape: a narrator piece
(`voice = "narradora"`, `model = "omnivoice"`) and a clone piece
(`voice = <profile id>`, `model = "cosyvoice"`). No sample bytes and no
profile id enter this package.

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
- **The backend is facet-managed.** `facet run` starts the managed server;
  its data lives in `<FACET_HOME>/data/voicestudio/` and survives update
  and remove. The first run that uses an engine installs it: about 8 GB for
  `voxcpm2`, about 13 GB for `cosyvoice` (`omnivoice` is in-process). The
  first step on a new machine is creating the voice profiles with
  `voicestudio.profile` from the person's own reference recordings.
- **The same `seed` does not repeat a clip.** The output varies a little
  between calls.
- **Cloned profiles live in the person's data dir** and are never bundled.
  A missing profile is created with `voicestudio.profile` from the person's
  own reference recordings; the doctor names the recipe.
- **Verification is always on.** There is no skip field in the piece format
  and no flag the runner would accept. A clip is heard back every time.
