# voicestudio

User-facing notes for the `voicestudio` package: `voicestudio.speak` (narrator engines) and `voicestudio.clone` (a person's local clone).

## Generation parameters (`voicestudio.speak` only)

`voicestudio.speak` accepts two optional inputs that tune generation:

| Input | Type | Bounds | Default when omitted |
| --- | --- | --- | --- |
| `num-step` | integer | 1 to 128 | the engine default (`voxcpm2`: 10, `omnivoice`: 16) |
| `guidance-scale` | number | above 0, up to 20 | the engine default (2.0 on both engines) |

When a piece does not set them they are omitted from the request, so each engine keeps its own default.

- Raise `num-step` for quality, lower it for speed.
- Raise `guidance-scale` when the voice drifts from the text.

The clone engine (`cosyvoice`, used by `voicestudio.clone`) reads neither parameter.

Example piece fragment:

```toml
[inputs]
voice = "narradora"
model = "voxcpm2"
language = "es"
num-step = 12
guidance-scale = 2.5

[[inputs.clip]]
name = "intro"
text = "In this laboratory we test an English voice."
seed = 7
```

## Length gate

Each attempt's duration is compared with the duration expected from its text:

- **Expected duration:** character count (Python codepoints of the full text) divided by the language's characters per second.
- **Rates:** copied into the package thresholds from the pinned backend's `services/speech_rate.py` table (Spanish `es`: 15.5 cps). The source file is named in the manifest thresholds.
- **Abnormal:** under 0.5× or over 2.0× the expected duration. Both ratios are declared thresholds in the manifest (`duration_min_ratio`, `duration_max_ratio`).

The length gate catches gross failures — a stuck loop, trailing noise, or swallowed words — not pacing. A clone's pace follows its reference speaker, so judge rhythm by ear.

## Verification and retries

The length gate joins the existing word-error loop. An attempt fails if either check fails:

- word error rate over `wer_max` (0.05), or
- duration outside 0.5×–2.0× of the expected duration.

On failure the clip is regenerated with `seed + 1`, up to 3 attempts total, using the same seed sequence as before. The last attempt is kept. A regenerate message names which check failed.

`verify` reports failing durations or word error with `passed: false`; the run does not raise on a verification failure of this kind.

## Record

The record keeps, for each clip/attempt context as produced by the runner:

- the parameters used (including `num-step` and `guidance-scale` as sent),
- the expected and actual durations,
- the attempt count.

When a piece omits `num-step` or `guidance-scale`, the request omits them so the engine uses its own default; the backend does not report the engine's effective default back.
