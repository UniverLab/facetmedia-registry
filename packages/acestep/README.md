# acestep

Instrumental background beds from one English caption, with ACE-Step 1.5
(MIT, commercial use allowed). `facet run acestep.bed` composes a WAV of at
most 30 s, normalises it to -16 LUFS, and `verify` checks its duration and
peak. It belongs to the **`audio`** facet and writes the `audio` kind, so its
beds show through the audio viewer.

The package is a port of the lab's `tools/musica.py`: one `.toml` is one
track, the runner renames the randomly-named output after the piece, and it
prints the volume and the peak. The caption is the whole style control.

## Caption rules

The caption is English and decides the style. Without guidance the model
loads bass and kick with about 60 % of the energy under 120 Hz, so ask for
acoustic instruments and end with:

```
No drums, no percussion, no bass beat, no synthesizers
```

There is no separate instrumental switch in a piece: the runner always sends
`lyrics = "[Instrumental]"` and `task_type = "text2music"`. Singing is
refused. The lab discarded sung music forever, and the runner rejects a
caption that names a voice, vocal, vocalist, sing, singer, singing, sung,
choir, lyrics, rap, chant or speech with a plain error — facet reports it as
`runner_failed` (exit 1). `invalid_input` is a facet-side piece/schema error
and never comes out of this refusal.

## Piece fields

`acestep.bed` — instrumental bed from an English caption:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `caption` | string | yes | English style caption; the runner refuses one asking for voice |
| `name` | string | yes | `[a-z0-9][a-z0-9-]*`, writes `<name>.wav` |
| `duration` | number | yes | seconds of music, at most 30 |
| `seed` | integer | no (default 0) | random seed, always sent with `use_random_seed = false`; a bed is reproducible from its seed |
| `steps` | integer | no (default 8) | denoising steps, sent as `inference_steps` |
| `guidance` | number | no (default 7.0) | guidance scale, sent as `guidance_scale` |
| `bpm` | integer | no | tempo, 30 to 300; unset sends nothing |
| `key` | string | no | musical key such as `C major`, sent as `key_scale`; unset sends nothing |
| `time-signature` | string | no | metre such as `4/4`, sent as `time_signature`; unset sends nothing |

## Timings and verification

About **50 s per 30 s track** on the reference GPU. `run` polls the server
every 2 s until the job finishes, downloads the WAV and normalises it to
-16 LUFS with the registry's `lib/audiopreview.py`, capping the gain so the
sample peak stays at or below -1.0 dBFS. The record carries `duration_s`,
`sample_rate_hz`, `lufs` and `peak_dbfs`.

`verify` passes a bed when its duration is within **1.0 s** of `duration` and
its peak sits above **-40 dBFS** (silence never passes), reporting both under
`verifier = "audiopreview"`. The preview (`<name>.wav.preview.json`) carries
the waveform, the integrated and momentary loudness with `target_lufs =
-16.0`, the silences longer than 1 s and the clipped samples.

## Loudness under voice

The bed is mixed into the landed narrado assembly. That is HyperFrames'
`narrado` contract, not a separate number: the voice files go through ffmpeg
`normalize` with `target-lufs = -16.0` and `true-peak-db = -1.5`, then ffmpeg
`mix` lays the voice layers (`role = "voice"`, `gain-db = 0.0`) over the bed
(`role = "bed"`) with `ducking = true`, `duck-db = -12.0` and `target-lufs =
-16.0`. The bed's own -16 LUFS is the level the mix starts from; the ducking
does the rest.

## Approved tracks and the sung-music verdict

The lab's approved beds are `clasica-alegre.wav` (Vivaldi-style allegro, 30 s)
and `clasica-melancolica.wav` (solo piano and string quartet, 30 s): both
acoustic, no percussion, and 2.5-16 % of their energy below 120 Hz. Both ship
as pieces in `examples/`, each with its WAV.

**Sung music is rejected forever.** The lab's verdict stands: this package
composes instrumental beds only, and a caption asking for voice fails before
the server is touched.

## Machine and doctor

`[requirements]`: **GPU**, **16 GB RAM**, **24 GB disk**, `exclusive = true`
(one heavy job at a time) on `linux`. The checkpoints are backend-owned:
ACE-Step fetches them into the checkout's `checkpoints/` on first start, and
the manifest declares them without a source or byte size.

`facet doctor acestep` runs `gpu`, `vram`, `gpu_free`, `imports` (`numpy`,
`pyloudnorm`, `soundfile`), `checkout` (`acestep/api_server.py`) and `models`
(`checkpoints/acestep-v15-turbo`, `checkpoints/vae`) at `quick` depth, plus
`server` (`/health`) at `full`. The `models` check is always ok: absent
folders are reported pending because ACE-Step downloads them into the
checkout's `checkpoints/` on the first run (about 11 GB; the first run needs
network). Only the `checkout` check names `facet pull acestep` as its fix.

## Licences

The tool is ACE-Step 1.5 (**MIT**), commercial use allowed. The runner's own
dependencies include PyTorch (**BSD-3-Clause**) and soundfile
(**BSD-3-Clause**). Both manifest models are backend-owned and MIT.

## Example

`examples/clasica-alegre.toml`:

```toml
[inputs]
caption = "Lively, joyful Baroque chamber orchestra piece in the style of a Vivaldi allegro. Bright strings playing fast staccato and spiccato runs, harpsichord continuo, playful solo violin and flute melodies. Energetic, festive and elegant. Acoustic instruments only. No drums, no percussion, no bass beat, no synthesizers, no electronic sounds."
name = "clasica-alegre"
duration = 30
```

Run it with `scripts/try-package.sh acestep acestep.bed
packages/acestep/examples/clasica-alegre.toml`.
