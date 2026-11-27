---
name: video-ops
description: Transcode video to H.264/AAC MP4, mux replacement audio without re-encoding video, and extract still frames on CPU with bundled FFmpeg.
---
# Video Ops

Post-process existing video clips deterministically on CPU using the static
FFmpeg binary bundled by `imageio-ffmpeg`: `video-ops.transcode` encodes
web-ready H.264/AAC MP4 (`libx264`, `yuv420p`, `aac`) with `+faststart`, optional downscaling, frame-rate
capping, and trimming; `video-ops.mux-audio` swaps in a cleaned audio track
without re-encoding the video stream; and `video-ops.frame` extracts a PNG or
JPG thumbnail frame at a chosen timestamp.

## When to use

- When a **rendered or recorded video** needs web-compatible H.264/AAC MP4
  encoding, smaller dimensions (`max-width`), lower frame rate (`fps`), or
  trimming (`start-s` / `end-s`): use `video-ops.transcode`.
- When you already have a **good video stream and a cleaned voice/mix audio
  clip** (for example from `ffmpeg.clean` or `ffmpeg.mix`) and want to combine
  them without losing video quality or spending CPU re-encoding video: use
  `video-ops.mux-audio`.
- When you need a **thumbnail or still frame** from a video at a specific
  timestamp: use `video-ops.frame`.
- It **does not generate video or clean audio**: use `comfy`, `hyperframes`,
  `demostage`, or `ffmpeg` for those steps first.

## Pieces

Transcode a clip to H.264/AAC MP4 with CRF 24 and `+faststart`
(`examples/transcode.toml`):

```toml
capability = "video-ops.transcode"

[inputs]
video = "fixture.mp4"
name = "fixture-transcoded"
crf = 24
audio-bitrate-kbps = 128
```

Replace a video's audio track without re-encoding video
(`examples/mux-audio.toml`):

```toml
capability = "video-ops.mux-audio"

[inputs]
video = "fixture.mp4"
audio = "fixture.wav"
name = "fixture-muxed"
audio-bitrate-kbps = 128
```

Extract a PNG frame at 0.5 s (`examples/frame.toml`):

```toml
capability = "video-ops.frame"

[inputs]
video = "fixture.mp4"
name = "fixture-frame"
at-s = 0.5
format = "png"
```

Note that `max-width` in `video-ops.transcode` only downscales sources wider
than `max-width` (`scale='min(iw,<w>)':-2`); narrower sources keep their
original width, and `-2` keeps height divisible by 2 for `yuv420p`. `start-s`
and `end-s` are absolute timestamps (`-ss` / `-to`), not durations.

## Judging the result

`verify` checks each output according to its capability:

- `video-ops.transcode`: non-zero file size, probed `duration_s > 0`, and
  positive `width` and `height`.
- `video-ops.mux-audio`: non-zero file size, probed `duration_s > 0`, positive
  `width` and `height`, and a present `audio_codec` stream.
- `video-ops.frame`: non-zero file size and a valid Pillow-readable image with
  positive `width` and `height`.

Previews write `<asset>.preview.json` matching the `video` schema for MP4
outputs (`length` and `fps` derived from the probed stream) and the `image`
schema for extracted frames.

## Pitfalls

- `imageio-ffmpeg` ships no `ffprobe` binary; stream metadata is parsed from
  `ffmpeg -i` stderr, which exits with code 1 by design when no output is given.
- `mux-audio` uses `-c:v copy` and `-shortest`: if the replacement audio is
  shorter than the video, the output ends when the shorter stream ends.
- Always run `facet doctor video-ops` if a run fails; `facet pull video-ops`
  restores the bundled binary and Pillow environment.

See [references/sources.md](references/sources.md) for upstream references.
