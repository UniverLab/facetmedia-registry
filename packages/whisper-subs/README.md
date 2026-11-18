# whisper-subs

Validated SRT and VTT subtitles from a whisper JSON sidecar: `facet run
whisper-subs.subtitles` converts the timed segments whisper already wrote
into the missing `.vtt` export or a normalized `.srt` rewrite, and checks
both for monotonic non-overlapping times. No model, no transcription, nothing
heavy — the whole package is stdlib, like the registry's other tool-free
packages. Hearing stays with `whisper.transcribe`; this is the last mile it
does not cover.

## Piece fields

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `source` | path | yes | — | a whisper `<name>.json` sidecar with `segments` carrying `start_s`, `end_s` and `text`, resolved relative to the piece |
| `format` | enum | no | `srt` | `srt` or `vtt` |
| `max-cps` | number | no | `20` | reading speed limit in characters per second; raise it for fast technical speech |
| `max-line-chars` | number | no | `42` | longest wrapped line in characters |
| `max-lines` | number | no | `2` | most lines per cue |
| `min-cue-seconds` | number | no | `0.8` | shortest cue in seconds; shorter contiguous cues merge |
| `max-cue-seconds` | number | no | `7` | longest cue in seconds; longer segments split |

## The sidecar contract

`source` is a JSON object whose `segments` is a non-empty list, one object
per cue:

```json
{
  "segments": [
    { "start_s": 0.0, "end_s": 1.5, "text": "Hola." },
    { "start_s": 1.5, "end_s": 3.25, "text": "Mundo." }
  ]
}
```

This is exactly what `whisper.transcribe` writes as `<name>.json` beside its
transcript — the runner reads the sidecar, never re-transcribes. whisper
always writes word timings (`words` with `start_s`/`end_s`/`word` per word);
the runner shapes the cues from them, and a segment without any stays one
cue. The cues are validated in order:

- each cue's `start_s` must be strictly below its `end_s`;
- each cue must start at or after the previous cue's end — cue boundaries
  that touch are allowed; overlaps and regressions are rejected with a plain
  error naming the 1-based cue (`cue 2: starts before cue 1 ends`), which
  facet reports as `runner_failed` with exit 1.

## The subtitle files

One run writes one asset named after the sidecar's stem, beside the piece
(`--out` overrides the directory):

- `<source-stem>.srt` — SubRip: a numbered cue per segment, timestamps
  `HH:MM:SS,mmm`, blank line between cues, `application/x-subrip`.
- `<source-stem>.vtt` — WebVTT: the `WEBVTT` header line, unnumbered cues
  with timestamps `HH:MM:SS.mmm`, `text/vtt`.

Before writing, the runner shapes the cues from the word timings so they
read at speed: segments over the duration or reading-speed limits split at
word boundaries, very short contiguous cues merge (never across a silence
gap), and every cue's text wraps at word boundaries. The limits are common
subtitle practice — about 20 characters per second, lines of about 42
characters with at most two per cue, cues between about a second and about
seven — adjustable through the five inputs above.

`verify` re-parses the file against the run's own limits and reports
`worst-cps`, `longest-line-chars`, `most-lines`, `shortest-cue-seconds`,
`longest-cue-seconds` and `cues-over-limit` besides `cues`, `duration_s`
(the last cue's end), `monotonic` and `header`, with the manifest's
threshold `cues_min = 1`: it passes only when there is at least one cue,
every cue starts at or after the previous one ends, the file opens in its
format's header shape, and no more than one cue — or more than 5 % of the
cues — breaks a readability limit. A single forced cue is reported, never
failed. The monotonic order was already enforced by the runner before the
bytes were written, so a passing verdict repeats a checked fact, not a
hope. `preview` writes the generic viewer's fields (`cues`, `duration_s`,
`format`) with a summary like `2 cues · 2.2 s · srt`.

## The extraction-first workflow for video sources

A video cannot be subtitled from the video file itself — whisper hears audio:

1. `ffmpeg.convert` the video to a plain audio format (`name` it, pick the
   format).
2. `whisper.transcribe` the audio offline: it writes `<name>.txt`,
   `<name>.srt` and `<name>.json` (the sidecar) into the piece directory.
3. `whisper-subs.subtitles` converts that sidecar: pick `srt` for a
   normalized rewrite of whisper's SRT or `vtt` for the export whisper does
   not write.

## The narrated-video handoff

`hyperframes.narrated` assembles a narrated piece from voice clips, a music
bed and whisper subtitles, and declares its `subtitles` input as SubRip
written offline: give it the converted `<source-stem>.srt`, not the `.vtt`.
The converted file has been validated for monotonic, non-overlapping cue
times — so the burn-in parser downstream only ever sees a well-ordered track.

## Bundled examples

`facet example <capability> --run` copies the capability's example, with
every file it names, into a fresh folder and runs it there:

- `whisper-subs.subtitles` — `examples/subtitles.toml`: `facet example whisper-subs.subtitles --run`
