# whisper

Transcripts, subtitles and timed words from an audio file on CPU: `facet run
whisper.transcribe` writes `<name>.txt`, `<name>.srt` and `<name>.json` with
faster-whisper `small` (CTranslate2, int8) and verifies the transcript by the
model's own confidence and, when the piece carries the text that was said, by
the word error rate against it. It belongs to the **`voice`** facet — Kokoro
speaks, this listens — and writes the **`text`** kind, so its transcript shows
through the generic viewer. It is the first capability whose facet and kind
differ, which is what the two-axis model exists for. CPU only: the runner
never imports anything CUDA.

## Piece fields

The fields below are what `facet describe whisper.transcribe --json` reports
for this manifest.

`whisper.transcribe` — transcript, subtitles and timed words from an audio
file on CPU, checked by confidence and optional reference text:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `audio` | path | yes | — | any format the bundled FFmpeg decodes: WAV, FLAC, MP3, OGG, M4A |
| `language` | enum | no | `auto` | `auto`, `es`, `en`; `auto` lets the model detect it |
| `name` | string | yes | — | matches `[a-z0-9][a-z0-9-]*`; writes `<name>.txt`, `<name>.srt`, `<name>.json` |
| `expect-text` | string | no | — | what was said, when known; enables the WER check |

The core's field names never carry an underscore (`manifest._NAME_RE`), so the
piece spells the reference text `expect-text`, exactly as Kokoro spells
`target-lufs`.

## Assets

One run writes three assets, each with its own record:

- `<name>.txt` — the transcript, one segment per line. It is the asset that
  carries the verification, and its properties are `language`,
  `language_probability`, `duration_s`, `segments` (how many) and `words`
  (timed words). `inputs = [audio]`, so the audio's hash enters the record;
  `seed = null`; `tool = {"name": "faster-whisper", "version": "1.2.1"}`.
- `<name>.srt` — one cue per segment, `HH:MM:SS,mmm`, `application/x-subrip`.
- `<name>.json` — `language`, `language_probability`, `duration_s` and
  `segments` (`start_s`, `end_s`, `text`, `avg_logprob`, `no_speech_prob`,
  and `words` with `start_s`, `end_s`, `word`, `probability`),
  `application/json`. This is where the timed data lives.

The subtitles and the sidecar are derived: `verify` passes them when they
parse to at least one cue or segment.

## Verification and doctor

`verify` reads the transcript with its sidecar: the run already measured the
segments' confidence, so verify loads no model. The transcript passes when all
of the following hold:

- it is not empty;
- the mean `avg_logprob` over its segments is at least `min_avg_logprob =
  -1.0`;
- the share of segments with `no_speech_prob > 0.6` is at most
  `max_no_speech_share = 0.2`;
- when `expect-text` is given, the word error rate against it is at most
  `wer_max = 0.10`.

The metrics are `language`, `language_probability`, `avg_logprob`,
`no_speech_share`, `words`, `words_per_minute` and `wer` (null without a
reference), under `verifier = "faster-whisper-small@536b0662"`. The word error
rate normalises exactly as Kokoro does — lowercase, accents stripped,
thousands dots dropped, Spanish numbers spelled into words, with the piece's
`language` when it is named and the detected one under `auto` — because the
normalisation and the WER come from the registry's `lib/textnorm.py`, copied
into the environment as `facet_lib.textnorm` (the `uses = ["textnorm"]` entry
in the manifest).

`run` calls the model with `language` (`None` for `auto`), `beam_size=5`,
`vad_filter=True` and `word_timestamps=True`; it writes the transcript, the
cues and the sidecar.

`facet preview <name>.txt` writes `<name>.txt.preview.json` (the generic
schema) with a one-line `summary` such as
`10.6 s · en (1.00) · 32 words · WER 0 %` and `fields` holding the properties
and the metrics. The timed segments stay in `<name>.json`; the preview never
copies them. The sidecar must sit beside the transcript for the preview to
read it.

`facet doctor whisper` runs the package's own checks:

- `imports` (quick): `faster_whisper`, `ctranslate2` and `av` import, with
  versions.
- `models` (quick): the `faster-whisper-small-transcribe` directory exists
  with the byte size the manifest claims (486 212 372 bytes).
- `transcribe` (full): the model loads on CPU int8 and transcribes a generated
  1 s silent WAV in a temporary directory without error, timed in the detail.

Every failing check names `facet pull whisper` as its fix.

## Licences

The tool chain is faster-whisper (MIT), ctranslate2 (MIT), onnxruntime (MIT,
also the Silero VAD), av (BSD-3-Clause), the FFmpeg bundled in the av wheels
(LGPL-2.1-or-later), soundfile (BSD-3-Clause) and numpy (BSD-3-Clause). FFmpeg
runs isolated in the package environment as a library of the runner — uv
downloads it from PyPI, facet distributes nothing of it — and it does not
license the audio it decodes.

The model, faster-whisper `small` (Systran), is **MIT**: commercial use
allowed, no acceptance step. It is the same snapshot Kokoro declares, under
the id `faster-whisper-small-transcribe`: model ids are unique across the
whole registry, and each package declares its own copy.

## Machine cost

`requirements` in the manifest: **no GPU**, **3 GB RAM**, **1 GB disk**
(model plus the environment), `exclusive = true` — the runner uses every CPU
core, so `facet run` waits for the lock — on `linux`. The first `facet pull
whisper` downloads about 490 MB (the model and the environment); later runs
are offline. Kokoro declares its own copy of the same model, so the two
packages download the same files twice: sharing one download between packages
is a core concern for later.

## Example

`examples/laboratory.flac` is a 10.56 s English voice clip converted to
16 kHz mono FLAC (175 KB), and `examples/laboratory.toml` transcribes it in
English with the reference text:

```toml
[inputs]
audio = "laboratory.flac"
language = "en"
name = "laboratory"
expect-text = "In this laboratory we test a locally generated English voice. We want to measure how clear it sounds, how long it takes, and how it compares with the voices we already use."
```

Run it with `scripts/try-package.sh whisper whisper.transcribe
packages/whisper/examples/laboratory.toml`; the script prints the run, the
preview, the doctor report and the skill. The records land beside the assets
as `laboratory.txt.facet.json` and its two siblings.

The English re-take was transcribed on CPU (model already pulled), and its
transcript record reads (abridged: the file also carries the creation time, the registry
and lock provenance, the params digest, the facet version and the licence
section):

```json
{"bytes": 174, "id": "sha256:9859ae8e513c7cf5da39057ff05a19b0c4425d4fac99bc7b2af6e7bdc08a6292", "kind": "text", "mime": "text/plain", "name": "laboratory", "path": "laboratory.txt", "properties": {"duration_s": 10.558, "language": "en", "language_probability": 1.0, "segments": 3, "words": 32}, "provenance": {"capability": "whisper.transcribe", "inputs": [{"id": "sha256:98d2be06053d939ae0c073b0cca870cd05b2a92ad2cffeed05e2cf29e05415c"}], "models": [{"bytes": 486212372, "hf_repo": "Systran/faster-whisper-small", "id": "faster-whisper-small-transcribe", "revision": "536b0662742c02347bc0e980a01041f333bce120"}], "package": {"lock_sha256": "ba9716018f0a3aac1c7ca3d3294f73a64352cfa9c75ffca33551c59041acb9bc", "name": "whisper", "version": "0.1.4"}, "params": {"audio": "laboratory.flac", "expect-text": "In this laboratory we test a locally generated English voice. We want to measure how clear it sounds, how long it takes, and how it compares with the voices we already use.", "language": "en", "name": "laboratory"}, "seed": null, "tool": {"name": "faster-whisper", "version": "1.2.1"}}, "record": 1, "verification": {"metrics": {"avg_logprob": -0.1871, "language": "en", "language_probability": 1.0, "no_speech_share": 0.0, "wer": 0.0, "words": 32, "words_per_minute": 182}, "status": "passed", "thresholds": {"max_no_speech_share": 0.2, "min_avg_logprob": -1.0, "wer_max": 0.1}, "verifier": "faster-whisper-small@536b0662"}}
```

The transcript is the reference text word for word (WER 0), split into three
segments, with mean `avg_logprob` −0.1871 and no segment the model thought
was non-speech. The `.srt` carries those three cues (00:00:00,000 →
00:00:04,200; 00:00:04,200 → 00:00:07,640; 00:00:07,640 → 00:00:10,360), and
the preview summarises the transcript as `10.6 s · en (1.00) · 32 words ·
WER 0 %`. `facet doctor whisper --json` reports `healthy: true` after that
pull (2.4 s, all three checks, the full-depth one included).

## Bundled examples

`facet example <capability> --run` copies the capability's example, with
every file it names, into a fresh folder and runs it there:

- `whisper.transcribe` — `examples/laboratory.toml`: `facet example whisper.transcribe --run`

The first run pulls the transcription model; CPU only.
