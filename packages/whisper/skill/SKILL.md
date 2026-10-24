---
name: whisper
description: Transcripts and subtitles from audio on CPU, checked by the model's confidence or by the word error rate against reference text.
---
# Whisper

Transcribe an audio file on CPU with faster-whisper `small` and get three
assets back: the transcript (`<name>.txt`), the subtitles (`<name>.srt`) and
the timed segments (`<name>.json`). One capability, `whisper.transcribe`,
belonging to the `voice` facet and writing the `text` kind. CPU only: nothing
CUDA is ever imported.

## When to use

- Transcribing narration, interviews or class recordings into text and
  subtitles, on a machine without a GPU.
- Checking what a voice clip actually says — including a Kokoro clip, which
  is the other direction of the same `voice` facet.
- Not for making speech: that is `kokoro.speak`, same facet, other direction.
- Not for translation, diarisation or larger Whisper models: out of scope for
  v0.1.

## Pieces

The lab's reference clip, transcribed in Spanish with its text as the
reference (`examples/laboratorio.toml`):

```toml
[inputs]
audio = "laboratorio.flac"
language = "es"
name = "laboratorio"
expect-text = "En este laboratorio probamos una voz en español generada localmente. Queremos medir si se entiende bien, cuánto tarda y cómo suena frente a las voces que ya usamos."
```

An interview in an unknown language, without a reference text — the WER is
simply not measured:

```toml
[inputs]
audio = "entrevista.m4a"
language = "auto"
name = "entrevista"
```

Run a piece with `facet run whisper.transcribe <piece.toml> --out build/`;
without `--out` the three assets land in the piece's directory. The field is
spelled `expect-text` because the core's field names never carry an
underscore.

## Judging the result

`verify` reads the transcript with its sidecar and reports three things:

- `avg_logprob` — the mean of the segments' average log probability: how sure
  the model was of the words it chose. It must be at least `-1.0`; a value
  near zero is a clean transcription, a large negative one means the audio is
  noisy, quiet or in another language.
- `no_speech_share` — the share of segments the model judged non-speech. It
  must stay at or under `0.2`, so a clip of silence or music cannot pass as a
  transcript.
- `wer` — the word error rate against `expect-text`, at most `0.10`. It is
  `null` when the piece carries no reference text.

Give `expect-text` whenever the words are known: it is the only check that
compares the transcript with what was actually said. When it fails, read
`segments` in `<name>.json` — each has its `start_s`, `end_s`, `text`,
`avg_logprob`, `no_speech_prob` and its timed `words` — to find the stretch
that failed: a low `avg_logprob` or a high `no_speech_prob` names the exact
seconds to listen to, and the words show what the model substituted.

`facet preview <name>.txt` writes `<name>.txt.preview.json` (generic viewer)
with a summary like `9.6 s · es (0.99) · 28 words · WER 0 %` and the same
metrics as fields. The sidecar must sit beside the transcript.

## Pitfalls

- `language = "auto"` can pick the wrong language on short clips: a two-second
  clip has too little evidence. Name the language (`es`, `en`) when you know
  it.
- The package is `exclusive` (it uses every CPU core): `facet run` waits for
  the lock, so a queued run starts only when the previous one finishes.
- The first `facet pull whisper` downloads about 490 MB (the model and the
  environment); later runs are offline. Kokoro declares its own copy of the
  same model: the two packages share the size, not the files.
- Keep `<name>.json` beside `<name>.txt`: `verify` and `preview` read the
  confidence and the timed segments from it.
