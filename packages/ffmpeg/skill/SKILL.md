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
name = "voz-a-16"
audio = "voz.flac"
```

Lay the voice over a pink-noise ambience bed, the bed ducked 12 dB while
the voice sounds (`examples/mix.toml`):

```toml
[inputs]
name = "voz-sobre-fondo"
ducking = true
duck-db = -12.0
target-lufs = -16.0

[[inputs.layer]]
audio = "voz.flac"
role = "voice"
start-s = 2.0

[[inputs.layer]]
audio = "fondo.flac"
role = "bed"
```

Cut the first 5 seconds to Ogg Opus (`examples/convert.toml`):

```toml
[inputs]
audio = "voz.flac"
name = "voz-ogg"
format = "ogg"
start-s = 0.0
end-s = 5.0
bitrate-kbps = 128
```

Run any of them with `facet run ffmpeg.mix <piece.toml> --out build/`; the
asset lands as `<name>.wav` (or `<name>.<ext>` for convert) with its record.

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
