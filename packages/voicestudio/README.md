# voicestudio

Narrates text through a [VoiceStudio](https://github.com/debpalash/VoiceStudio)
backend (omnivoice): the `narradora` clone on the `voxcpm2` engine
(Apache-2.0), in Spanish, at roughly 20 s per clip. Every clip is verified
by transcribing it back with faster-whisper `small` and measuring the word
error rate — a clip that misses by more than 5 % of its words is
regenerated with another seed, always, with no flag to turn it off.

## The piece format

```toml
[inputs]
voice = "narradora"      # the cloned profile registered in the backend
model = "voxcpm2"        # the engine; the piece's only model field
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

## The backend is user-started (for now)

The runner is a pure client: it never starts, stops or holds anything —
facet owns server lifecycle, and the runner only reads URLs. The
transitional architecture (this version of the package ships no
`[engine.server]` table) is because the core's server provisioning only
runs `uv pip install -r <requirements-in-tree>` today, while the lab-tested
VoiceStudio tree ships no requirements.txt — its canonical install is a
project-dir `uv pip install --constraint deploy/torch-constraints.txt .`.
Once the core accepts that install shape, the backend becomes a managed
server started by `facet` itself; this package then graduates per that
follow-up spec.

Until then, start the backend once, from the clone, exactly like the lab
runs it:

```sh
cd ~/Projects/open-source/VoiceStudio
python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 3900
```

`facet doctor voicestudio --json` also runs the machine checks itself: an
NVIDIA GPU, its VRAM readable, and no model but the backend's holding GPU
memory (one at a time). With `--full` it prints the start command above
whenever the backend is not answering.

A run against a backend that is not answering fails naming that command
too, so a forgotten `uvicorn` is one line of output, not a stack trace.

## Base URL

The runner resolves the backend URL in this order:

1. `$FACET_SERVER_URL` — where facet's managed server will sit later;
2. `$VOICESTUDIO_URL` — the person's own choice (the lab's default port
   is 3900);
3. `http://127.0.0.1:3900` — the lab recipe.

The environment `facet run` hands the runner includes the person's own
variables untouched, so `VOICESTUDIO_URL` works without extra config.

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
`facet pull voicestudio`). After each synthesis the runner transcribes the
clip back, folds tildes (NFKD: `hipótesis` → `hipotesis`) and spells
numbers below a million in words (Whisper writes `2026` where the text
says `dos mil veintiséis`), then compares word sequences. Over 5 % of
words wrong → `REGENERATE` printed and `seed + 1` tried. The piece format
has no skip field and the CLI flag cannot reach the runner, so the loop
always runs.

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
`facet pull voicestudio`), plus the VoiceStudio clone at
`~/Projects/open-source/VoiceStudio` and its backend.
With `--full` it also probes `GET /model/status` and the default voice
profile: `narradora` (id `a082932b`). Profiles are local to the person's
machine and are NEVER bundled with the package; a missing `narradora`
profile is recreated from the host with
`POST /profiles multipart name=narradora kind=clone language=es` and its
`ref_audio` plus the `ref_text` from the lab piece
(`projects/prueba-voz/narradora/voz.toml`) — the doctor's report names this
recipe as a host hint.

## Licences

The VoiceStudio backend is AGPL-3.0-only and runs on the person's machine
as their tool; the runner talks to it over HTTP and licenses nothing of it.
The verification model (faster-whisper, ctranslate2) is MIT, and the
`voxcpm2` engine is Apache-2.0.
