---
name: kokoro
description: CPU narration in Spanish or English with Kokoro-82M, checked by transcribing each clip back and measuring WER.
---
# Kokoro

Narrate text to WAV clips on CPU with Kokoro-82M (ONNX), normalise their
loudness, and verify every clip by transcribing it with faster-whisper
`small` and measuring the word error rate. One capability, `kokoro.speak`,
writing the `audio` kind.

## When to use

- When you need narration and the machine has no GPU voice installed: this
  package runs on CPU alone and never imports anything CUDA.
- When a clip must be *judged*, not just heard: `verify` transcribes it and
  the run only passes while the word error rate stays under the threshold.
- It is **not** the lab's main voice; that arrives later with a VoiceStudio
  package. Kokoro is the CPU voice behind the v0.1 metric.
- To transcribe existing audio (an interview, a recording) do **not** use
  this package — use `whisper.transcribe`, which lives in the same `voice`
  facet.

## Pieces

The lab's reference text, one clip (`examples/laboratorio.toml`):

```toml
[inputs]
voice = "ef_dora"
language = "es"

[[inputs.clip]]
name = "laboratorio"
text = "En este laboratorio probamos una voz en español generada localmente. Queremos medir si se entiende bien, cuánto tarda y cómo suena frente a las voces que ya usamos."
```

Two clips mixing a per-clip `voice` and `speed` over the piece defaults:

```toml
[inputs]
voice = "ef_dora"
language = "es"
speed = 1.0

[[inputs.clip]]
name = "intro"
text = "Bienvenido al laboratorio."

[[inputs.clip]]
name = "rapido"
text = "Esta frase se dice más deprisa."
voice = "em_alex"
speed = 1.3
```

Run a piece with `facet run kokoro.speak <piece.toml> --out build/`; every
clip becomes `<name>.wav` beside the others, with its record. Without
`--out` the clips land in the piece's directory.

## Judging the result

`verify` transcribes each clip with faster-whisper `small` (CPU, int8) and
reports `wer`, the word error rate against the text. A clip passes while
`wer` stays at or under `wer_max = 0.05` (one wrong word in twenty) **and**
its peak sits above −40 dBFS, so silence can never pass as narration. The
loudness target (`target-lufs`, default −16.0) is what `run` normalises to,
capped so the peak never exceeds −1.0 dBFS; the record reports the `lufs`
actually measured after normalisation.

`facet preview <clip>.wav --json` writes `<clip>.wav.preview.json`. To fix
a failed clip, read `speech.alignment`: one row per word with `ref` (the
text), `hyp` (what whisper heard) and `op` (`ok`, `sub`, `del`, `ins`).
Then, in order of preference:

- a number Whisper wrote as digits → spell it out in the text;
- an acronym or symbol it mangled (`&`, `%`, units) → write it as words;
- one long sentence splitting into `del`/`ins` at its tail → cut it into two
  clips or lower the per-clip `speed`;
- re-run **only that clip**: edit the piece, keep the other clips' names,
  and re-run the piece — verified clips are re-synthesised, so shorten the
  piece to just the failing clip when the rest already passed.

## Pitfalls

- The voice's first letter must match `language`: `e` → `es`, `a` →
  `en-us`, `b` → `en-gb` (`ef_dora` is Spanish, `af_alloy` is American
  English, `bf_emma` is British English). The run rejects a mismatch and
  names both values.
- The package is `exclusive` (it uses every CPU core): `facet run` waits
  for the lock, so a queued run starts only when the previous one finishes.
- The first `facet pull kokoro` downloads about 840 MB (the 325 MB model,
  28 MB of voices, the 486 MB whisper model and the environment); later runs
  are offline.
- The package environment carries GPL components (phonemizer, espeak-ng).
  They run isolated as libraries of the runner and do not license the audio
  they produce.
