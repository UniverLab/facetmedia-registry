---
name: whisper-subs
description: Validated SRT and VTT subtitles from a whisper JSON sidecar — segments checked for monotonic non-overlapping times, no model, no transcription.
---
# whisper-subs

`whisper-subs.subtitles` converts a whisper JSON sidecar into a subtitle
file: `<source-stem>.srt` or `<source-stem>.vtt`, validated before any byte
is written. It does not transcribe and holds no model — the hearing stays
with `whisper.transcribe`; this package only turns its timed segments into
the file hyperframes.narrated burns into a narrated video.

## When to use

- A piece already has a whisper sidecar (`<name>.json`, written by
  `whisper.transcribe`) and needs a subtitle file from it — an SRT rerun or
  the WebVTT that whisper writes no `.vtt` for.
- Turning video into subtitles, extraction first: `ffmpeg.convert` the video
  to audio, `whisper.transcribe` it offline, then this package converts the
  sidecar.
- Not for hearing anything: no model is involved, and a sidecar with bad
  timing is rejected, not repaired.
- Not for narration itself: after this, hand the `.srt` to
  `hyperframes.narrated`, which reads whisper-written SRT as subtitles input.

## Pieces

```toml
[inputs]
source = "laboratory.json"
format = "srt"
```

`source` is the whisper sidecar, resolved relative to the piece file: a JSON
object whose `segments` each carry `start_s`, `end_s` and `text` — exactly
what `whisper.transcribe` writes. The runner validates the cues in order —
each `start_s` strictly below its `end_s`, each cue starting at or after the
previous cue ends (touching boundaries allowed, overlaps and regressions
rejected) — then writes `<source-stem>.<format>` beside the piece. Omit
`format` for `srt`; `vtt` writes the `WEBVTT` header and dot times
(`00:00:01,500` comma for srt, `00:00:01.500` dot for vtt).

Run a piece with `facet run whisper-subs.subtitles <piece.toml> --out
build/`; without `--out` the subtitle lands in the piece's directory. The
five readability limits below are optional inputs with the same defaults.

## Limits

Before writing, the runner shapes the cues from the segments' word timings
so they read at speed: long segments split at word boundaries, very short
contiguous cues merge, and text wraps at word boundaries. A segment without
word timings stays one cue and is judged like any other.

| Input | Default | What it means |
|-------|---------|---------------|
| `max-cps` | `20` | characters per second; faster cues split where speech allows |
| `max-line-chars` | `42` | longest line; cue text wraps at word boundaries |
| `max-lines` | `2` | most lines per cue; longer wraps split |
| `min-cue-seconds` | `0.8` | shortest cue; shorter contiguous cues merge |
| `max-cue-seconds` | `7` | longest cue; longer segments split |

These numbers are common subtitle practice for readability, not
transcription targets — only the ~20 characters-per-second flag follows the
voice research report's reading-speed note. Raise `max-cps` for fast
technical speech the audience already knows, rather than forcing splits
the speech cannot fit.

## Judging the result

`verify` re-parses the written file against the run's own five limits and
reports `worst-cps`, `longest-line-chars`, `most-lines`,
`shortest-cue-seconds`, `longest-cue-seconds` and `cues-over-limit`
(count of cues breaking any limit) besides `cues`, `duration_s` (the last
cue's end), `monotonic` and `header`. It fails only when more than one cue
breaks a limit and those cues are more than 5 % of all cues: a single
forced cue is reported, never failed, however short the piece. Because the
runner validated the sidecar before writing, a passing verdict means the
times were already monotonic at conversion.

`facet preview <source-stem>.<format>` writes
`<source-stem>.<format>.preview.json` (generic viewer) with a summary like
`2 cues · 2.2 s · srt` and the same three fields.

The cues are sentence segments, the readable-subtitle granularity — not
karaoke-style word timings, which stay in the sidecar's timed words. Spell
names right one step earlier, in the transcription: shaping fixes timing
and layout, never spelling. When conversion fails, re-run from the
sidecar; never hand-edit it.

## Pitfalls

- The sidecar is the input: keep `laboratory.json` where the piece names it,
  and read its `segments`, not its transcript — a missing or empty `segments`
  fails with "the sidecar carries no segments".
- Overlaps and regressions are rejected with the cue's index:
  `cue 2: starts before cue 1 ends`. whisper segments are monotonic, so a
  failure means the sidecar was hand-edited or truncated.
- The core's field names never carry an underscore; the input is `source`,
  the format `format`, the same voice-facet precedents as whisper.
- `hyperframes.narrated` declares its subtitles as SubRip: give it the `.srt`,
  not the `.vtt`.

The guidance above draws on public sources listed in
[references/sources.md](references/sources.md).
