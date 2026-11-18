# voicestudio

User-facing notes for the `voicestudio` package: `voicestudio.speak` (narrator engines) and `voicestudio.clone` (a person's local clone).

## Inputs

`voicestudio.speak` accepts optional inputs that tune generation and caching:

| Input | Type | Bounds / values | Default when omitted |
| --- | --- | --- | --- |
| `num-step` | integer | 1 to 128 | the engine default (`voxcpm2`: 10, `omnivoice`: 16) |
| `guidance-scale` | number | above 0, up to 20 | the engine default (2.0 on both engines) |
| `cache` | boolean | `true` or `false` | `true` (reuse a verified cached clip) |

When a piece does not set `num-step` or `guidance-scale` they are omitted from the request, so each engine keeps its own default.

- Raise `num-step` for quality, lower it for speed.
- Raise `guidance-scale` when the voice drifts from the text.
- Set `cache` to `false` to bypass the verified-clip cache and force synthesis.

The clone engine (`cosyvoice`, used by `voicestudio.clone`) reads neither `num-step` nor `guidance-scale`; `voicestudio.clone` does accept `cache` (default `true`).

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

The length gate and a silence check join the existing word-error loop. An attempt fails if any check fails:

- word error rate over `wer_max` (0.05),
- duration outside 0.5×–2.0× of the expected duration, or
- a run of digital silence (all-zero samples) longer than 200 ms between the clip's first and last non-silent sample (a dropout, not a pause).

On failure the clip is regenerated with `seed + 1`, up to 3 attempts total, using the same seed sequence as before. The last attempt is kept. A regenerate message names which check failed.

`verify` reports failing duration, word error, or dropout with `passed: false` and records the longest interior digital-silence run as `metrics.digital_silence_run_ms`; the run does not raise on a verification failure of this kind.

## Record

The run record keeps, for each clip as produced by the runner:

- the parameters used (including `num-step` and `guidance-scale` as sent, and the effective seed),
- the expected and actual durations,
- the transcript and word error rate,
- the attempt count, and
- `properties.cached` indicating whether the clip came from the verified-clip cache.

When a piece omits `num-step` or `guidance-scale`, the request omits them so the engine uses its own default; the backend does not report the engine's effective default back.

## Clip cache

Identical synthesis attempts reuse a verified clip from `<FACET_HOME|~/.facet>/data/voicestudio/clip-cache` (keyed by engine/model version, voice, text, language, generation parameters, and seed) instead of synthesizing again. Only a clip that passed verification when it was made is cached. Verification still runs on every clip, cached or not.

The cache is capped at 1 GiB per package, evicting the oldest entries first. Set `cache` to `false` on a `speak` or `clone` piece to bypass it, or delete the cache directory by hand to clear it.
