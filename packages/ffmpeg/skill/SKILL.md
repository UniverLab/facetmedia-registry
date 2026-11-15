---
name: ffmpeg
description: Normalise, mix and convert audio clips with FFmpeg, with verified loudness and duration.
---
# FFmpeg

Turn an existing audio clip into the clip the platform wants: bring it to a
loudness target with a two-pass EBU R128 normalisation, lay it over a music
or ambience bed with the bed ducked under the voice, or convert, resample
and cut it. Three capabilities — `ffmpeg.normalize`, `ffmpeg.mix` and
`ffmpeg.convert` — all writing the `audio` kind with the static FFmpeg
binary bundled by imageio-ffmpeg. Light package: no models, no GPU, not
exclusive.

## When to use

- After a **voice clip exists** (from the `voice` facet) and it must meet a
  loudness target: `ffmpeg.normalize` brings it to −16 LUFS without clipping.
- When the clip must sit **over music or ambience**: `ffmpeg.mix` lays voice
  layers over bed layers and ducks the beds under the voice automatically.
- When a platform wants **another format, rate or length**: `ffmpeg.convert`
  cuts with `start-s`/`end-s`, resamples and encodes wav, flac, mp3 or ogg.
- It **does not make sound**: narration and effects generation belong to the
  `voice` and `audio` facets' other packages.

## Pieces

Normalise the lab's voice clip to the web/podcast target
(`examples/normalize.toml`):

```toml
[inputs]
target-lufs = -16.0
true-peak-db = -1.5
sample-rate-hz = "48000"

[[inputs.clip]]
name = "voice-at-16"
audio = "voice.flac"
```

Lay the voice over a pink-noise ambience bed, the bed ducked 12 dB while
the voice sounds (`examples/mix.toml`):

```toml
[inputs]
name = "voice-over-bed"
ducking = true
duck-db = -12.0
target-lufs = -16.0

[[inputs.layer]]
audio = "voice.flac"
role = "voice"
start-s = 2.0

[[inputs.layer]]
audio = "bed.flac"
role = "bed"
```

Cut the first 5 seconds to Ogg Opus (`examples/convert.toml`):

```toml
[inputs]
audio = "voice.flac"
name = "voice-ogg"
format = "ogg"
start-s = 0.0
end-s = 5.0
bitrate-kbps = 128
```

Run any of them with `facet run ffmpeg.mix <piece.toml> --out build/`; the
asset lands as `<name>.wav` (or `<name>.<ext>` for convert) with its record.

## Before you normalise

Normalise in two passes, never one: the first measures the clip through the
same compressor the second applies, the second applies the gain in linear
mode. A single pass pumps and drifts, and the destination level is only
right on average.

Normalised is not unclipped. Raising quiet material raises its peaks with
it, so read the true peak **after** the gain change: `verify` re-meters
every asset and fails a `normalize` whose peak goes over `true-peak-db` +
0.1 dB. A clip that cannot reach the target without crossing the ceiling
wants a lower `target-lufs`, not a higher `true-peak-db`: a pass that
clipped is never shipped.

Never raise deep ambience to a speech target. A bed sitting around -40 LUFS
or quieter is doing its job, and pushing it to -16 turns wind into a hiss
laid over the voice. Normalise the voice, mix the bed under it, and let the
mix's loudness be the loudness that matters.

Loudness is the last step of a chain and it comes **before** any lossy
encode: colour, cut, join and silence the clip first, normalise it second,
encode mp3 or ogg last. A lossy re-encode moves loudness slightly, so
normalising after it measures the wrong thing.

Pick the target by destination: about -14 LUFS for streaming platforms,
-16 for web and podcasts, -23 for EBU broadcast, -24 for Japanese broadcast.
The runner pins the loudness range at 11 LU in both passes and exposes no
input for it: no piece can widen or narrow that band.

A mix already ends in a limiter set to -1 dBFS, and `verify` wants the peak
at or below -0.9 dBFS. When a mix lands over the ceiling, the fix is the
bed, not the limiter: lower that layer's `gain-db` or deepen `duck-db` and
re-run.

Divergence: facet's default target is -16 LUFS rather than the streaming
-14, because the clip here is a voice under narration with a bed beneath
it, not a song in a player.

## Judging the result

`verify` re-measures every asset by decoding it with the bundled binary and
measuring with soundfile and pyloudnorm (the binary ships no ffprobe):

- `normalize`: the integrated loudness within `lufs_tol = 1.0` LU of
  `target-lufs`, the peak at or below `true-peak-db` + 0.1 dB, and the
  duration within 20 ms of the source's.
- `mix`: the duration equals the longest `start-s` + layer length within
  50 ms, the peak stays at or below −0.9 dBFS, and with `target-lufs` the
  loudness is within 1.0 LU.
- `convert`: the decoded output has the requested sample rate and channels,
  and its duration is within 20 ms of `end-s − start-s` (or the source's).

Each verdict reports `lufs`, `peak_dbfs`, `duration_s` and
`duration_error_s`.

To judge whether a **mix sounds right**, read the preview
(`facet preview <name>.wav`): `loudness.momentary` plots the loudness every
100 ms, so the bed dipping under the voice shows as the curve falling while
the voice speaks; `silences` lists the stretches below −50 dBFS. If the bed
still buries the voice, lower the bed layer's `gain-db` or deepen `duck-db`
and re-run; if the bed vanishes, raise them.

## Pitfalls

- −16 LUFS suits web and podcasts; −23 LUFS suits broadcast. Pick the
  target for the destination, not by ear.
- Lossy formats (mp3, ogg) change loudness slightly when they re-encode:
  normalise **before** converting, and judge the wav, not the mp3.
- The `wav`, `flac`, `mp3` and `ogg` formats are exactly those the bundled
  FFmpeg build can encode; `facet doctor ffmpeg` lists the encoders, and a
  pull (`facet pull ffmpeg`) is the fix for a broken binary.
- The bundled binary runs as a separate process with its own licence (see
  the package README); it never touches a system ffmpeg.

The guidance above draws on public sources listed in
[references/sources.md](references/sources.md).
