# voicestudio

Narrates text through a [VoiceStudio](https://github.com/debpalash/VoiceStudio)
backend with the `narradora` clone, in Spanish, and verifies every clip by
transcribing it back with faster-whisper `small` — a clip that misses by
more than 5 % of its words is regenerated with another seed, always, with
no flag to turn it off.

Two engines speak that voice:

| `model` | Licence | Weights |
| --- | --- | --- |
| `voxcpm2` (default) | Apache-2.0 | the backend's |
| `omnivoice` | CC-BY-NC, no commercial use | the backend's, terms accepted once with `facet license accept omnivoice` |

`omnivoice` is the approved narrator engine: the `narradora` profile on the
`omnivoice` backend voice. A `voxcpm2` piece asks for nothing; an
`omnivoice` piece is gated per piece on its recorded acceptance.

A third engine, `cosyvoice` (Apache-2.0), speaks a person's own clone through
`voicestudio.clone`: see [Cloned voices](#cloned-voices-cosyvoice).

## The piece format

```toml
[inputs]
voice = "narradora"      # the cloned profile registered in the backend
model = "voxcpm2"        # omnivoice for the approved narrator engine
language = "es"          # the piece's language

[[inputs.clip]]
name = "intro"
text = "En este laboratorio probamos una voz en español."
seed = 7
```

Each clip requires a `seed`; the verification loop retries a failing clip
with `seed + 1` (three tries per clip, the last attempt kept — the record
reports the final `seed` and the `attempts` count). The entries carry
exactly `name`, `text` and `seed`: the piece-level `model` is the only
model field anywhere in the format, so a mixed-engine piece is not
representable by construction.

## One engine per piece

One `.toml`, one engine. Two engines do not fit in 8 GB of VRAM, and two
voices belong in two files that interleave later in HyperFrames. The
manifest cannot say this twice — the entry list simply has no `model` key.
The piece-level `model` is the manifest model id the core gates on: an
`omnivoice` piece needs its acceptance, a `voxcpm2` one needs nothing.

## The backend is facet-managed

Facet pulls VoiceStudio at the pinned revision from its own `uv.lock`,
builds its server venv and starts it for each run: no clone, no start
command. Its data lives in `<FACET_HOME>/data/voicestudio/` (the backend's
`OMNIVOICE_DATA_DIR`) and survives update and remove.

The first run that uses an engine installs it through the backend's own
loopback API: about 8 GB for `voxcpm2`, about 13 GB for `cosyvoice`.
`cosyvoice` compiles pyworld from source on install, so it needs a C++
compiler (`sudo apt install build-essential`); the server runs with
`CC=gcc` and `CXX=g++` because facet's managed Python names clang, and the
doctor and the run refuse the install up front when `g++` is missing.
`omnivoice` is in-process and installs nothing. The first step on a new
machine is creating the voice profiles with `voicestudio.profile` from the
person's own reference recordings (see
[Making a profile](#making-a-profile-voicestudioprofile)).

`facet doctor voicestudio --json` also runs the machine checks itself: an
NVIDIA GPU, its VRAM readable, and no model but the backend's holding GPU
memory (one at a time). With `--full` it also probes the backend status,
the default voice profile and each sidecar engine's install state.

A run against a backend that is not answering fails naming the managed
server, so a missing backend is one line of output, not a stack trace.

## Base URL

The runner resolves the backend URL in this order:

1. `$FACET_SERVER_URL` — the managed server facet starts for each run;
2. `$VOICESTUDIO_URL` — the person's own choice (the default port
   is 3900);
3. `http://127.0.0.1:3900` — the managed server's default port.

The environment `facet run` hands the runner includes the person's own
variables untouched, so `VOICESTUDIO_URL` works without extra config.

## The `omnivoice` licence (CC-BY-NC)

The OmniVoice weights are **CC-BY-NC**: the upstream card states
"the pre-trained model is licensed under the CC-BY-NC", and the licensor
states no version. Commercial use is not allowed. The manifest records the
spdx exactly as `CC-BY-NC`, because the core matches an acceptance record
by that exact string.

The backend owns those weights, so the model entry in `package.toml` is
`backend = true` and `facet pull` skips it (`backend-owned, skipped`).
Before the first `omnivoice` piece, record the acceptance once:

```sh
facet license accept omnivoice
```

`facet run` then gates per piece: a piece whose `model` is `omnivoice` with
no recorded acceptance fails with `license_not_accepted` (exit 4) and the
hint above; a `voxcpm2` piece runs with nothing accepted. The runner never
re-implements that check. Accepting makes the person who runs facet
responsible for complying with the terms.

## Cloned voices (cosyvoice)

`voicestudio.clone` speaks a person's own clone on the `cosyvoice` engine
(Apache-2.0, about 15 s per clip). It is the engine closest to the owner's
rhythm in the lab comparison: about 5 % faster than the real voice, against
14 % for `omnivoice` and 19 % for `voxcpm2`, with a pitch band of
135–144 Hz against the real 136–140 Hz. With the narrator it sounded
somewhat Spanish-from-Spain, so the clone is the second voice at most,
never the lead.

```toml
[inputs]
voice = "d4e9ee57"       # the local profile id; profiles are never bundled
model = "cosyvoice"      # the clone engine, the only one this piece may name
language = "es"

[[inputs.clip]]
name = "mi-voz"
text = "En este laboratorio probamos una voz en español."
seed = 7
```

The voice is a local-only profile id, not a name from a fixed list. The
runner asks the backend for its profiles and refuses an id that is not
installed here. Profiles are created by the `voicestudio.profile` capability
from the person's local samples and are never vendored: see
[Making a profile](#making-a-profile-voicestudioprofile). The approved
pattern lives at
`projects/prueba-voz/mi-voz/clon/cosyvoice/voz.toml`.

Two voices are two pieces: the narrator in one file (`narradora` on
`omnivoice`) and the person in another (`voice = <profile id>` on
`cosyvoice`), interleaved later in HyperFrames. One `.toml` carries one
engine only; a two-engine piece fails `invalid_input` before synthesis, and
the runner refuses a clone piece naming any engine but `cosyvoice`.

Clone only with the owner's permission (`AGENTS.md:259`). The runner never uploads
a sample anywhere: it sends text to the local backend and reads the WAV back.

## Making a profile (`voicestudio.profile`)

**Ask the owner first, always.** A cloned voice is that person's voice: only
make a profile from samples they gave you for it, and only with their
permission (`AGENTS.md:259`).

`voicestudio.profile` turns a local reference recording into a clone profile
the backend keeps on this machine. The sample never enters the registry and
no profile is ever vendored.

```toml
[inputs]
name = "mi-voz"
ref-audio = "samples/mi-voz.wav"   # relative to this piece file
instruct = "male, low pitch"       # optional: the backend's design vocabulary
language = "es"
```

```sh
facet run voicestudio.profile mi-voz.toml
```

The reference is 7–30 s of neutral speech, recorded from
`projects/prueba-voz/guion-grabacion.md`. A questioning or exclamatory start
contaminates the clone with a sharp attack and skips the first sentences, so
the runner refuses a take outside that window instead of posting it. It also
repairs the laptop stereo case: when one channel is digitally silent and the
other carries the voice, it keeps the live channel (what
`ffmpeg -af pan=mono|c0=c1` does manually) and prints the repair. Finally it
takes the reference to −20 LUFS, as the approved reference was, with the
sample peak capped at −1 dBFS.

`ref-audio` is a `path` input resolved relative to the piece file. The runner
validates the take, then POSTs it once as the backend's `ref_audio` multipart
field with `kind=clone`, `name`, `language` and `instruct` (leaving `ref_text`
empty so the backend transcribes the reference at save time). An empty name
is refused before any POST, and a backend 4xx/5xx fails the run.

The backend persists the audio under its own app-data `VOICES_DIR`; the run
writes only `<name>.profile.json` beside the piece, a receipt with the
returned profile `id`, `name` and `language`. Nothing else is written, and no
sample or profile enters the registry. `facet run` verifies by default: the
receipt passes while its id is still in the backend's `GET /profiles`
listing. `voicestudio.profile` is the one capability that declares
`verify_uses_server = true`, so `facet check <name>.profile.json` starts the
managed backend to re-read that listing; the other capabilities verify
without it. `facet preview` writes `<name>.profile.json.preview.json` for the
`generic` viewer (the receipt's id, name and language).

## Ready versus health

`/health` answers `ok` while the backend's background import is still
running, so a first request races it and can fail with `omnivoice package
missing`. The runner therefore never trusts `/health` alone: connect, then
poll `GET /model/status` until

- `ready` — an engine is preloaded; synthesis starts at once;
- `idle` that **stays** idle for 30 s — nothing preloaded: the **first**
  synthesis call loads the engine, so the request carries the lab's long
  timeout (900 s). An idle that turns into `loading` is a preload already
  on its way, and the runner waits for it rather than racing it;
- `error` — the run fails, naming the state and the error the backend
  reported (a failed load travels in the payload's `error` field while
  `status` stays `idle` or `loading`).

## The verification loop

The package embeds faster-whisper-small (MIT-licensed, id
`faster-whisper-small-verify`, fetched once by
`facet pull voicestudio`). The `omnivoice` entry is backend-owned, carries
no bytes and no source, and the doctor reports it as
`backend-owned: omnivoice` instead of checking a byte size. After each
synthesis the runner transcribes the
clip back, folds tildes (NFKD: `hipótesis` → `hipotesis`) and spells
numbers below a million in words (Whisper writes `2026` where the text
says `dos mil veintiséis`), then compares word sequences. Over 5 % of
words wrong → `REGENERATE` printed and `seed + 1` tried, at most three
attempts per clip. A clip still over the threshold after those attempts is
not dropped: the runner keeps the last attempt's WAV, seed and transcript,
and the `verify` verb reports that asset with `passed: false`, its `wer`
and the `wer_max` threshold. The core turns that verdict into the record's
failed verification status and `facet run` exits 3 (`verification_failed`).

There is no piece-level skip: the piece inputs stay voice, model, language
and clip. The only opt-out is the core's `facet run --no-verify` flag,
which skips the verify verb; it never skips this run-time loop.

## Preview

Each clip lands beside the piece file as `<name>.wav`, previewed by facet's
`audio` viewer: the preview JSON (waveform, duration, loudness, silences and
the speech check with its word alignment) is what an agent reads, and the
viewer draws the inline player with the waveform and the momentary loudness
for the person. The backend renders as it likes, so `loudness.target_lufs`
is `null`: nothing in this package normalises the clip. The lab-approved
reference narration lives outside the package, at
`projects/prueba-voz/narradora/a-narracion-aprobada.wav`.

## Doctor

`facet doctor voicestudio --json` first checks the machine: an NVIDIA GPU
(the manifest declares `gpu = true`), its VRAM (total and free, per GPU),
and no other model loaded on it — a backend answering `ready` or `loading`
owns the GPU, an `idle` one has nothing loaded (the VRAM rows say what is
free), and when none answers, any compute process on the GPU fails the
check (`stop the other GPU job: one model at a time`).
Then the runner's imports and the embedded whisper model (missing files:
`facet pull voicestudio`).
With `--full` it also probes `GET /model/status`, the default voice
profile `narradora`, and each sidecar engine's install state. Profiles are
local to the person's data dir and are NEVER bundled with the package; a
missing `narradora` profile is created with
`facet run voicestudio.profile <piece>` with `name = "narradora"` — the
doctor's report names this recipe.

## Licences

The VoiceStudio backend is AGPL-3.0-only and runs on the person's machine
as their tool; the runner talks to it over HTTP and licenses nothing of it.
The verification model (faster-whisper, ctranslate2) is MIT, the `voxcpm2`
and `cosyvoice` engines are Apache-2.0, and the `omnivoice` engine's weights
are CC-BY-NC (non-commercial): see
[the licence section](#the-omnivoice-licence-cc-by-nc).
