# kokoro

Narration from text on CPU, checked by transcription: `facet run
kokoro.speak` writes WAV clips with Kokoro-82M (ONNX, CPU), normalises
their loudness, and verifies every clip by transcribing it back with
faster-whisper `small` on CPU and measuring the word error rate against
the text (threshold 5 %). It belongs to the **`voice`** facet and writes
the `audio` kind, so its clips show through the audio viewer. CPU only —
the runner never imports anything CUDA. It is the package behind the v0.1
success metric: a verified voice clip from one command, in under 5
minutes, without a GPU.

## Piece fields

The fields below are what `facet describe kokoro.speak --json` reports
for this manifest.

`kokoro.speak` — narration from text on CPU (Spanish and English),
checked by transcription:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `voice` | enum | no | `ef_dora` | 31 Kokoro voices; first letter must match `language` |
| `language` | enum | no | `es` | `es`, `en-us`, `en-gb` |
| `speed` | number | no | 1.0 | 0.5 to 2.0, speaking rate |
| `target-lufs` | number | no | −16.0 | −30 to −10, normalisation target |
| `clip` | array | yes | — | at least one clip: `name`, `text`, optional per-clip `voice` and `speed` |

Each clip's `name` matches `[a-z0-9][a-z0-9-]*` and becomes `<name>.wav`.
A clip may override the piece's `voice` and `speed`; `language` and
`target-lufs` apply to every clip in the piece. The runner rejects a
voice whose first letter does not match the language (`e` → `es`, `a` →
`en-us`, `b` → `en-gb`) with a message naming both.

## Verification and doctor

`verify` loads faster-whisper `small` (CPU, int8) once and transcribes
each clip with `beam_size=5` and a VAD filter. The word error rate is
word-level Levenshtein over normalised tokens: lowercase, accents
stripped, thousands dots dropped, and — for Spanish only — numbers
spelled into words, because Whisper writes "2026" where the text says
"dos mil veintiséis". A clip passes while `wer ≤ 0.05` and its peak sits
above −40 dBFS (silence can never pass), reporting `wer`, `words`,
`words_per_minute`, `lufs`, `peak_dbfs` and `transcript` under
`verifier = "faster-whisper-small@536b0662"`.

`run` normalises each clip with pyloudnorm (ITU-R BS.1770) to
`target-lufs`, capping the gain so the sample peak stays at or below
−1.0 dBFS, and writes PCM 16-bit at 24 kHz.

The preview (`<name>.wav.preview.json`) carries the waveform (1200
bins), the integrated and momentary loudness (400 ms windows every 100
ms, `null` below −70 LUFS), the silences longer than 1 s below −50 dBFS,
the clipped samples and, under `speech`, the text, transcript, WER and
the word alignment that tells you which word to fix.

`facet doctor kokoro` runs the package's own checks:

- `imports` (quick): `kokoro_onnx`, `faster_whisper`, `pyloudnorm`,
  `soundfile` and `av` import, with versions.
- `espeak` (quick): the espeak-ng library bundled by espeakng-loader
  loads; phonemizer needs it to phonemise.
- `models` (quick): the three model files exist with the byte sizes the
  manifest claims (325 505 369 + 28 214 398 + 486 212 372 bytes).
- `synth` (full): the word "facet" synthesises into a non-empty 24 kHz
  WAV in a temporary directory, timed in the detail.
- `transcribe` (full): faster-whisper small loads on CPU int8 and
  transcribes that clip, timed in the detail.

Every failing check names `facet pull kokoro` as its fix.

## Licences

The tool chain is kokoro-onnx (MIT), onnxruntime (MIT), faster-whisper
(MIT), ctranslate2 (MIT), soundfile (BSD-3-Clause), pyloudnorm (MIT),
pillow (MIT-CMU) and numpy (BSD-3-Clause). Two components inside the
package environment are **GPL-3.0-or-later**: phonemizer and the
espeak-ng bundled by espeakng-loader (espeakng-loader itself is MIT).
They run isolated in the package environment as libraries of the runner —
uv downloads them from PyPI, facet distributes nothing of them — and they
do not license the audio they produce; records list them, and
`commercial_use` stays true.

The models: Kokoro-82M and its voice pack are **Apache-2.0** (hexgrad),
faster-whisper `small` is **MIT** (Systran); all three allow commercial
use and need no acceptance step.

## Machine cost

`requirements` in the manifest: **no GPU**, **4 GB RAM**, **1.5 GB
disk** (models plus the environment), `exclusive = true` — the runner
uses every CPU core, so `facet run` waits for the lock — on `linux`.
The first `facet pull kokoro` downloads about 840 MB (the two Kokoro
files and the 486 MB whisper model); later runs are offline.

## Example

`examples/laboratorio.toml` narrates the lab's reference text as one
clip:

```toml
[inputs]
voice = "ef_dora"
language = "es"

[[inputs.clip]]
name = "laboratorio"
text = "En este laboratorio probamos una voz en español generada localmente. Queremos medir si se entiende bien, cuánto tarda y cómo suena frente a las voces que ya usamos."
```

Run it with `scripts/try-package.sh kokoro kokoro.speak
packages/kokoro/examples/laboratorio.toml`; the run's record lands beside
the clip as `laboratorio.wav.facet.json` and carries the asset's
properties (`duration_s`, `sample_rate_hz`, `lufs`, `peak_dbfs`,
`voice`, `language`), the params, and the verification verdict
(`wer`, `words_per_minute`, `transcript`, `verifier`).

The lab run (24 October 2026, 12 cores, no GPU) took **33.7 s** wall for
the whole command, including the first pull, and its record reads:

```json
{"assets": [{"kind": "audio", "mime": "audio/wav",
  "properties": {"duration_s": 9.641, "sample_rate_hz": 24000,
                 "lufs": -20.72, "peak_dbfs": -1.0,
                 "voice": "ef_dora", "language": "es"},
  "tool": {"name": "kokoro-onnx", "version": "0.6.1"}}],
 "verification": {"status": "passed",
  "metrics": {"wer": 0.0, "words": 28, "words_per_minute": 174,
              "transcript": "En este laboratorio probamos una voz en español generada localmente. Queremos medir si se entiende bien, cuánto tarda y cómo suena frente a las voces que ya usamos."},
  "verifier": "faster-whisper-small@536b0662"}}
```

The transcript is the text word for word, so the WER is 0. The loudness
stopped at −20.7 LUFS rather than −16 because Kokoro's own peak already
sat near full scale: the −1.0 dBFS cap engaged, which is the other half
of the acceptance rule. `facet doctor kokoro --json` reports `healthy:
true` after that pull (< 4 s, full depth).
