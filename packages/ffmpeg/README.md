# ffmpeg

Normalise, mix and convert audio clips with FFmpeg: `facet run
ffmpeg.normalize` brings clips to a loudness target with a two-pass EBU
R128 normalisation, `facet run ffmpeg.mix` lays voice layers over a music
or ambience bed with the bed ducked under the voice, `facet run
ffmpeg.convert` cuts, resamples and encodes to another format. It belongs
to the **`audio`** facet and writes the `audio` kind, so its assets show
through the audio viewer. It runs the static FFmpeg binary bundled inside
the `imageio-ffmpeg` wheel — never a system ffmpeg — and measures every
result with soundfile and pyloudnorm (the binary ships no ffprobe). Light
package: **no models, no GPU, not exclusive**.

## Piece fields

The fields below are what `facet describe ffmpeg.<capability> --json`
reports for this manifest.

`ffmpeg.normalize` — bring clips to a loudness target (EBU R128,
two-pass) without clipping:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `clip` | array | yes | — | at least one clip: `name`, `audio` |
| `target-lufs` | number | no | −16.0 | −30 to −10, integrated loudness target |
| `true-peak-db` | number | no | −1.5 | −6 to 0, the peak ceiling in dBFS |
| `sample-rate-hz` | enum | no | `"48000"` | `"24000"`, `"44100"` or `"48000"` |

`ffmpeg.mix` — lay voice layers over a music or ambience bed, with the
bed ducked under the voice:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.wav` |
| `layer` | array | yes | — | at least one layer: `audio`, `role`, optional `gain-db` and `start-s` |
| `ducking` | boolean | no | `true` | duck the beds under the voices |
| `duck-db` | number | no | −12.0 | −30 to 0, how far the beds drop |
| `target-lufs` | number | no | — | normalise the finished mix when given |

`ffmpeg.convert` — convert, resample or cut a clip:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `audio` | path | yes | — | any format the bundled FFmpeg decodes |
| `name` | string | yes | — | `[a-z0-9][a-z0-9-]*`; writes `<name>.<ext>` |
| `format` | enum | no | `wav` | `wav`, `flac`, `mp3`, `ogg` |
| `sample-rate-hz` | integer | no | — | 8000 to 96000; the source's when omitted |
| `channels` | enum | no | — | `"1"` or `"2"`; the source's when omitted |
| `start-s` / `end-s` | number | no | — | cut: keep from / up to this second |
| `bitrate-kbps` | integer | no | 128 | 32 to 320, lossy formats only |

## How it runs

Every ffmpeg call is a subprocess in its own process group with
`-nostdin -hide_banner -y`; a non-zero exit reports its stderr tail as
the runner error. `normalize` is the standard two passes: pass 1 runs
`loudnorm … print_format=json` and parses the measured values, pass 2
applies them with `linear=true`, resampled to `sample-rate-hz`, and an
`alimiter` at the true-peak ceiling (loudnorm's own estimate lets about a
quarter of a dB through when its 192 kHz stream is decimated, and the
verification measures the decoded file). `mix` is one filtergraph: every
layer is delayed (`adelay`) and scaled (`volume`), the voices are summed
(`amix`, `normalize=0`), the beds are compressed with `sidechaincompress`
keyed on the padded voice sum so they drop by about `duck-db` while the
voice sounds, and the result passes `alimiter` at −1 dBFS. `convert` cuts
with `-ss`/`-to` and encodes with the format's own encoder
(`pcm_s16le`, `flac`, `libmp3lame`, `libopus`).

## Verification and doctor

`verify` re-measures each asset by decoding it to 32-bit float WAV with
the bundled binary and measuring with soundfile and pyloudnorm:

- `normalize`: integrated loudness within `lufs_tol = 1.0` LU of
  `target-lufs`, peak at or below `true-peak-db` + 0.1 dB, duration
  within 20 ms of the source's;
- `mix`: duration equals the longest `start-s` + layer length within
  50 ms, peak at or below −0.9 dBFS, and with `target-lufs` the loudness
  within 1.0 LU;
- `convert`: the decoded output has the requested sample rate and
  channels (ogg always decodes at 48 kHz, as libopus requires) and its
  duration is within 20 ms of `end-s − start-s` (or the source's).

Every verdict reports `lufs`, `peak_dbfs`, `duration_s` and
`duration_error_s` under `verifier = "ffmpeg 7.0.2-static loudnorm"`.

`facet doctor ffmpeg` runs the package's own checks:

- `binary` (quick): the bundled ffmpeg runs `-version`.
- `encoders` (quick): every encoder behind the `format` enum is listed
  (`pcm_s16le`, `flac`, `libmp3lame`, `libopus`).
- `imports` (quick): numpy, pyloudnorm and soundfile import, with versions.
- `roundtrip` (full): a 1 s 440 Hz sine generated with `lavfi` is
  normalised to −16 LUFS and must measure within 1 LU.

Every failing check names `facet pull ffmpeg` as its fix.

## Licences

The tool chain is imageio-ffmpeg (BSD-2-Clause), numpy (BSD-3-Clause),
pyloudnorm (MIT) and soundfile (BSD-3-Clause). The FFmpeg binary bundled
inside the imageio-ffmpeg wheel is **GPL-3.0-or-later**: its
`-version` configuration line carries `--enable-gpl` (it also enables
`--enable-version3` and static x264/x265/libopus/libmp3lame). It runs
isolated as a separate process of the runner — uv downloads the wheel
from PyPI, facet distributes nothing of it — and it does not license the
audio it processes; records list it, and `commercial_use` stays true. The
package has no models.

## Machine cost

`requirements` in the manifest: **no GPU**, **1 GB RAM**, **0.3 GB
disk** (the environment plus the 28 MB binary), `exclusive = false` on
`linux` — the examples run alongside other light work, but they are
short: each of the three examples runs in a few seconds.

## Examples

`examples/voz.flac` is the lab's reference voice clip (the same 16 kHz
mono FLAC whisper transcribes); `examples/fondo.flac` is a 15 s pink
noise bed, low-passed at 800 Hz and laid at −30 dBFS, generated once
with the bundled ffmpeg (`anoisesrc`), 117 KB.

`examples/normalize.toml` brings the voice to −16 LUFS; run it with
`scripts/try-package.sh ffmpeg normalize
packages/ffmpeg/examples/normalize.toml`. The record:

```json
{"bytes": 925584, "id": "sha256:cc150f5826d1dfd498fe32f5618ba026a4ec864bd3f592833316ee2065c65a14", "kind": "audio", "mime": "audio/wav", "name": "voz-a-16", "path": "voz-a-16.wav", "properties": {"channels": 1, "duration_s": 9.641, "lufs": -16.8, "peak_dbfs": -1.5, "sample_rate_hz": 48000}, "provenance": {"capability": "ffmpeg.normalize", "package": {"name": "ffmpeg", "version": "0.1.0"}, "seed": null, "tool": {"name": "ffmpeg", "version": "ffmpeg version 7.0.2-static https://johnvansickle.com/ffmpeg/  Copyright (c) 2000-2024 the FFmpeg developers"}}, "record": 1, "verification": {"metrics": {"duration_error_s": 0.0, "duration_s": 9.641, "lufs": -16.8, "peak_dbfs": -1.5}, "status": "passed", "thresholds": {"lufs_tol": 1.0}, "verifier": "ffmpeg 7.0.2-static loudnorm"}}
```

The loudness stopped at −16.8 rather than −16.0 because this clip's peak
already sits high: the true-peak ceiling engaged, which is the other half
of "without clipping".

`examples/mix.toml` lays the voice over the bed, the voice starting at
2 s, ducking on, `target-lufs = -16`:

```json
{"bytes": 2880078, "id": "sha256:8635d2de048be74cd1b88183ce8cf97df7181dd0155a921cd48f4c2a60cf698a", "kind": "audio", "mime": "audio/wav", "name": "voz-sobre-fondo", "path": "voz-sobre-fondo.wav", "properties": {"channels": 2, "duration_s": 15.0, "lufs": -16.21, "peak_dbfs": -1.5, "sample_rate_hz": 48000}, "provenance": {"capability": "ffmpeg.mix", "package": {"name": "ffmpeg", "version": "0.1.0"}, "seed": null, "tool": {"name": "ffmpeg", "version": "ffmpeg version 7.0.2-static https://johnvansickle.com/ffmpeg/  Copyright (c) 2000-2024 the FFmpeg developers"}}, "record": 1, "verification": {"metrics": {"duration_error_s": 0.0, "duration_s": 15.0, "lufs": -16.21, "peak_dbfs": -1.5}, "status": "passed", "thresholds": {"lufs_tol": 1.0}, "verifier": "ffmpeg 7.0.2-static loudnorm"}}
```

The mix lasts 15.0 s — the bed's own length — even though the voice ends
near 11.6 s, because the padded sidechain key keeps holding the bed down
after the voice stops. Its preview summarises it as `mix · 15.0 s ·
-16.2 LUFS · peak -1.5 dBFS · bed ducked -12 dB`, and the momentary
curve shows the bed alone at about −40 LUFS for the first 2 s, the whole
mix at about −17 LUFS while the voice speaks, and the ducked bed alone
again at the tail; `facet preview voz-sobre-fondo.wav` serves it in the
audio viewer.

`examples/convert.toml` cuts the first 5 s of the voice to Ogg Opus at
128 kbps:

```json
{"bytes": 88071, "id": "sha256:b6f356bb07a5a…", "kind": "audio", "mime": "audio/ogg", "name": "voz-ogg", "path": "voz-ogg.ogg", "properties": {"channels": 1, "duration_s": 5.0, "lufs": -26.0, "peak_dbfs": -6.33, "sample_rate_hz": 48000}, "record": 1, "verification": {"metrics": {"duration_error_s": 0.0, "duration_s": 5.0, "lufs": -26.0, "peak_dbfs": -6.33}, "status": "passed", "thresholds": {}, "verifier": "ffmpeg 7.0.2-static loudnorm"}}
```

The ogg decodes at 48 kHz whatever the source was (libopus always runs
at 48 kHz), which is what `verify` expects for this format. All three
runs (24 October 2026, the lab machine) took a few seconds each, the
first pull included, and `facet doctor ffmpeg --json` reports
`healthy: true` after them.
