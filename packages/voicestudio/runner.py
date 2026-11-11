"""The voicestudio package runner: the facet voice on a VoiceStudio backend.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` narrates the clips through the backend (the
piece's voice and engine — ``narradora`` on ``voxcpm2``, or on ``omnivoice``
when the piece selects the approved narrator engine) and verifies each clip
by transcribing it with faster-whisper ``small`` — a clip whose word error
rate exceeds the threshold is regenerated with ``seed + 1`` (at most three
tries per clip, the last attempt kept), ``verify`` transcribes existing
assets, ``preview`` writes the audio preview file, ``doctor`` checks the
machine (an NVIDIA GPU, its VRAM readable, no model but the backend's
holding GPU memory) plus the package (imports, models) at ``quick``
depth, and, at ``full`` depth, the backend status, the default profile and
each sidecar engine's install state.

The runner never reimplements the licence gate: an ``omnivoice`` piece whose
CC-BY-NC terms are not recorded fails in the core with
``license_not_accepted`` (exit 4), before the runner starts.

This runner is a client of a facet-managed server: facet pulls VoiceStudio
from its pinned ``uv.lock`` and starts it for each run, with its state
under ``<FACET_HOME>/data/voicestudio/``. The base URL is
``FACET_SERVER_URL`` (the managed server), else ``VOICESTUDIO_URL``, else
``http://127.0.0.1:3900`` — the environment that ``facet run`` sets up
reaches the runner untouched.

Heavy imports go through ``importlib`` inside the functions: the verification
side (``textnorm``) is stdlib-only, so a broken environment still lets the
doctor report *which* import fails instead of dying on a top-level import.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from facet_lib import textnorm  # noqa: E402  (path insert must run first)
from facet_runner_sdk import Request, Runner  # noqa: E402

runner = Runner()

#: The word error rate a clip must stay at or under (manifest threshold).
WER_MAX = 0.05
#: What verification measures with, named for the record.
VERIFIER = "faster-whisper-small@536b0662"
#: The transcriber the package itself embeds (its manifest model id; the
#: registry pins unique ids, and kokoro already declares the bare name).
WHISPER_MODEL = "faster-whisper-small-verify"
#: The engine a piece gets when it names none. Any other manifest engine
#: (``omnivoice``) reaches the backend by the piece's own ``model`` value.
ENGINE = "voxcpm2"
#: The tool that produced a run: the pinned VoiceStudio clone the lab tested
#: (a git revision, recorded as the tool's version).
TOOL = {"name": "VoiceStudio", "version": "c2ef998"}
#: The base URL when neither facet nor the person named one.
DEFAULT_BASE_URL = "http://127.0.0.1:3900"
#: Endpoint paths of the VoiceStudio backend this runner talks to.
STATUS_PATH = "/model/status"
SPEAK_PATH = "/v1/audio/speech"
PROFILES_PATH = "/profiles"
#: Seconds a connection gets and a readiness wait may take in total.
CONNECT_TIMEOUT_S = 10.0
READY_TIMEOUT_S = 600.0
READY_POLL_S = 1.0
#: How long ``idle`` must persist before the runner treats it as "nothing
#: preloaded" and proceeds: the lab's 30 s, so a preload that starts right
#: after the backend did (idle → loading → ready) is never raced.
READY_IDLE_GRACE_S = 30.0
#: Seconds the doctor's health peek gets and an nvidia-smi call may take.
HEALTH_TIMEOUT_S = 2.0
NVIDIA_SMI_TIMEOUT_S = 4.0
#: The lab's synthesis timeout: a fresh clip can take ~20 s, the first one
#: includes loading the engine, so the request budget stays generous.
SPEAK_TIMEOUT_S = 900.0
#: Attempts per clip: the piece's seed, then ``seed + 1`` while over the WER.
MAX_TRIES = 3
#: The default cloned voice profile (registered locally with POST /profiles).
DEFAULT_VOICE = "narradora"
#: The capability that speaks a local clone profile, and the one engine it uses.
CLONE_CAPABILITY = "voicestudio.clone"
CLONE_ENGINE = "cosyvoice"
#: The capability that turns a local reference into a clone profile.
PROFILE_CAPABILITY = "voicestudio.profile"
#: The receipt a profile run writes beside the piece (the sample never is).
PROFILE_SUFFIX = ".profile.json"
#: What verify reports as the profile receipt's verifier.
PROFILE_VERIFIER = "voicestudio-profiles"
#: Where the missing-profile refusal sends the person: profile creation is its own verb.
CLONE_PROFILE_SPEC = "facet run voicestudio.profile <piece> with the person's own name"
#: The recreate recipe for a missing default profile, as the person runs it.
PROFILE_RECIPE = 'facet run voicestudio.profile <piece> with name = "narradora"'
#: Imports the doctor proves, with the distribution each comes from.
DOCTOR_IMPORTS = (
    ("faster_whisper", "faster-whisper"),
    ("soundfile", "soundfile"),
    ("numpy", "numpy"),
    ("pyloudnorm", "pyloudnorm"),
)


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the doctor's model byte sizes."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _base_url() -> str:
    """The backend URL: facet's server, else the person's, else the default."""
    facet_url = str(os.environ.get("FACET_SERVER_URL") or "").strip()
    voice_url = str(os.environ.get("VOICESTUDIO_URL") or "").strip()
    return facet_url or voice_url or DEFAULT_BASE_URL


def _fetch_json(base_url: str, path: str, timeout_s: float) -> Any:
    """One GET decoded as JSON; the caller decides what a failure means."""
    request = urllib.request.Request(f"{base_url}{path}", method="GET")
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_speak(base_url: str, name: str, body: dict[str, Any]) -> bytes:
    """One synthesis request; the answer bytes are a WAV clip."""
    request = urllib.request.Request(
        f"{base_url}{SPEAK_PATH}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=SPEAK_TIMEOUT_S) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"{name}: VoiceStudio answered {exc.code}: {detail}") from None
    except OSError as exc:
        raise RuntimeError(f"{name}: no VoiceStudio backend at {base_url}: {exc}") from None


def _status(base_url: str) -> dict[str, Any]:
    """GET /model/status; facet starts the backend for each run."""
    try:
        payload = _fetch_json(base_url, STATUS_PATH, CONNECT_TIMEOUT_S)
    except ValueError as exc:
        raise RuntimeError(f"{base_url}{STATUS_PATH} answered no JSON: {exc}") from None
    except OSError as exc:
        raise RuntimeError(
            f"no VoiceStudio backend at {base_url} ({exc}); "
            "facet starts it for each run — see facet doctor voicestudio"
        ) from None
    if not isinstance(payload, dict):
        raise RuntimeError(f"{base_url}{STATUS_PATH} answered no JSON object")
    return payload


def _state(payload: Any) -> str:
    """The backend's reported state, whichever key the response uses."""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("state") or payload.get("status") or "").lower()


def _idle_since(state: str, idle_since: float | None, now: float) -> float | None:
    """When the current idle stretch began; any other state resets it."""
    if state != "idle":
        return None
    return now if idle_since is None else idle_since


def _ready_detail(state: str, payload: dict[str, Any]) -> str:
    """What the readiness wait reports back to the run."""
    return f"{state}: {json.dumps(payload)[:120]}"


def _wait_ready(base_url: str) -> str:
    """Poll GET /model/status until the backend is ready to synthesise.

    ``ready`` returns at once; ``idle`` returns only after it *stays* idle for
    ``READY_IDLE_GRACE_S`` — a backend that is still starting reports idle
    first and loading right after, so proceeding on the first idle would race
    the preload. A report carrying ``error`` (the backend's shape: status
    stays idle/loading and the failure travels in that field) fails naming it;
    /health alone is never trusted, because it answers ok while the background
    import is still running.
    """
    started = time.monotonic()
    idle_since: float | None = None
    while True:
        payload = _status(base_url)
        state = _state(payload)
        now = time.monotonic()
        if state == "ready":
            return _ready_detail(state, payload)
        if state == "error" or payload.get("error"):
            raise RuntimeError(f"backend state error: {json.dumps(payload)[:200]}")
        idle_since = _idle_since(state, idle_since, now)
        if idle_since is not None and now - idle_since >= READY_IDLE_GRACE_S:
            return _ready_detail(state, payload)
        if now - started > READY_TIMEOUT_S:
            raise RuntimeError(f"backend not ready after {READY_TIMEOUT_S:.0f} s (state {state!r})")
        time.sleep(READY_POLL_S)


def _whisper(req: Request) -> Any:
    """faster-whisper small on CPU int8, loaded once per run."""
    faster_whisper = importlib.import_module("faster_whisper")
    return faster_whisper.WhisperModel(
        str(req.model_path(WHISPER_MODEL)), device="cpu", compute_type="int8"
    )


def _transcribe(model: Any, path: Path, language: str) -> str:
    """The clip's transcript: beam 5 with VAD, one space-joined string."""
    segments, _info = model.transcribe(str(path), language=language, beam_size=5, vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()


def _clip(word: dict[str, Any], piece: dict[str, str]) -> dict[str, Any]:
    """One clip with the piece defaults resolved into its own fields.

    The piece carries exactly one piece-level ``model`` and no entry carries
    one: a mixed-engine piece is unrepresentable by construction (one .toml,
    one engine — two voices go in two files).
    """
    return {
        "name": str(word["name"]),
        "text": str(word["text"]),
        "seed": int(word["seed"]),
        **piece,
    }


def _clips(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Every clip, with voice/model/language read once at piece level."""
    piece = {
        "voice": str(params.get("voice", DEFAULT_VOICE)),
        "model": str(params.get("model", ENGINE)),
        "language": str(params.get("language", "es")),
    }
    return [_clip(word, piece) for word in params.get("clip", [])]


def _speak_body(clip: dict[str, Any], seed: int) -> dict[str, Any]:
    """The lab ``speak()`` request body, one clip and one seed."""
    return {
        "model": clip["model"],
        "input": clip["text"],
        "voice": clip["voice"],
        "language": clip["language"],
        "response_format": "wav",
        "seed": seed,
    }


def _params(clip: dict[str, Any], seed: int) -> dict[str, Any]:
    """The clip's effective fields, under their manifest names."""
    return {
        "name": clip["name"],
        "text": clip["text"],
        "seed": seed,
        "voice": clip["voice"],
        "model": clip["model"],
        "language": clip["language"],
    }


def _wav_shape(path: Path) -> tuple[float, int]:
    """The recorded clip's duration and rate, straight from the WAV header."""
    with wave.open(str(path), "rb") as reader:
        rate = reader.getframerate()
        frames = reader.getnframes()
    return frames / rate if rate else 0.0, rate


def _asset(
    clip: dict[str, Any], path: Path, seed: int, score: float, transcript: str, tries: int
) -> dict[str, Any]:
    """One clip's record: the written WAV, its engine details and its seed."""
    duration, rate = _wav_shape(path)
    return {
        "file": path.name,
        "name": clip["name"],
        "kind": "audio",
        "mime": "audio/wav",
        "properties": {
            "duration_s": round(duration, 3),
            "sample_rate_hz": rate,
            "voice": clip["voice"],
            "model": clip["model"],
            "language": clip["language"],
            "transcript": transcript,
            "wer": round(score, 4),
            "attempts": tries,
        },
        "params": _params(clip, seed),
        "seed": seed,
        "inputs": [],
    }


def _score(clip: dict[str, Any], transcript: str) -> tuple[float, list[str]]:
    """The WER of the transcript against the text, tildes and digits folded."""
    reference = textnorm.words(clip["text"], clip["language"])
    heard = textnorm.words(transcript, clip["language"])
    return textnorm.wer(reference, heard), reference


def _try_clip(
    whisper: Any, base_url: str, clip: dict[str, Any], seed: int, out_dir: Path
) -> tuple[str, float]:
    """One synthesis attempt: speak, transcribe the clip back, score it."""
    data = _post_speak(base_url, clip["name"], _speak_body(clip, seed))
    path = out_dir / f"{clip['name']}.wav"
    path.write_bytes(data)
    transcript = _transcribe(whisper, path, clip["language"])
    score, _reference = _score(clip, transcript)
    return transcript, score


def _narrate(whisper: Any, base_url: str, clip: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """One clip, verified; a clip over the WER regenerates with seed + 1."""
    seed = clip["seed"]
    path = out_dir / f"{clip['name']}.wav"
    transcript = ""
    score = 1.0
    tries = 0
    while True:
        tries += 1
        transcript, score = _try_clip(whisper, base_url, clip, seed, out_dir)
        if score <= WER_MAX:
            break
        if tries >= MAX_TRIES:
            print(
                f"REGENERATE {clip['name']}: still wer {score:.3f} > {WER_MAX:.2f} "
                f"after {tries} attempts, keeping seed {seed}",
                flush=True,
            )
            break
        seed += 1
        print(
            f"REGENERATE {clip['name']}: wer {score:.3f} > {WER_MAX:.2f}, "
            f"retrying with seed {seed}",
            flush=True,
        )
    return _asset(clip, path, seed, score, transcript, tries)


def _profile_module() -> Any:
    """The profile helpers, imported only when a profile verb needs them."""
    return importlib.import_module("profile")


def _engines() -> Any:
    """The sidecar provisioning helpers, imported only when a verb needs them."""
    return importlib.import_module("engines")


def _run_profile(req: Request) -> dict[str, Any]:
    """Validate the reference, POST one clone profile, write its receipt."""
    params = dict(req.inputs)
    name = str(params.get("name", "")).strip()
    ref = str(params.get("ref-audio") or "")
    if not ref:
        raise ValueError("the piece names no ref-audio (the person's reference recording)")
    path = Path(ref)
    if not path.is_absolute():
        path = req.piece_dir / path
    if not path.is_file():
        raise ValueError(f"{path}: the reference audio does not exist")
    if Path(name).name != name:
        raise ValueError(f"profile name {name!r} must be a bare file stem")
    library = _profile_module()
    audio, repairs = library.validate_ref(path)
    for repair in repairs:
        print(f"REPAIRED {path.name}: {repair}", flush=True)
    language = str(params.get("language", "es"))
    record = library.post_profile(
        _base_url(),
        name,
        audio,
        instruct=str(params.get("instruct", "")),
        language=language,
    )
    profile_id = str(record.get("id", ""))
    if not profile_id:
        raise RuntimeError("the backend returned no profile id")
    receipt = {
        "id": profile_id,
        "name": str(record.get("name") or name),
        "language": str(record.get("language") or language),
    }
    file_name = f"{name}{PROFILE_SUFFIX}"
    (req.out_dir / file_name).write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "tool": dict(TOOL),
        "assets": [
            {
                "file": file_name,
                "name": name,
                "kind": "text",
                "mime": "application/json",
                "properties": {
                    "profile_id": profile_id,
                    "name": receipt["name"],
                    "language": receipt["language"],
                    "target_lufs": library.TARGET_LUFS,
                    "repairs": repairs,
                },
                "params": {"name": name, "ref-audio": ref, "language": language},
                "seed": 0,
                "inputs": [],
            }
        ],
    }


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    """Connect, wait for readiness, then voice and verify every clip."""
    if req.capability == PROFILE_CAPABILITY:
        return _run_profile(req)
    clips = _clips(dict(req.inputs))
    if not clips:
        raise ValueError("the piece has no clips")
    clone = req.capability == CLONE_CAPABILITY
    if clone:
        _check_clone_engine(clips)
    base_url = _base_url()
    _wait_ready(base_url)
    if clone:
        _check_clone_voice(base_url, clips[0]["voice"])
    engine = clips[0]["model"]
    if engine in _engines().SIDECAR_ENGINES:
        _engines()._ensure_engine(base_url, engine)
    whisper = _whisper(req)
    assets = [_narrate(whisper, base_url, clip, req.out_dir) for clip in clips]
    return {"tool": dict(TOOL), "assets": assets}


def _read_receipt(path: Path) -> dict[str, Any]:
    """The receipt's JSON object, named by the file when it does not parse."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{path.name}: cannot read the receipt ({exc})") from None
    except ValueError as exc:
        raise ValueError(f"{path.name}: the receipt is not JSON ({exc})") from None
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name}: the receipt is not a JSON object")
    return loaded


def _verify_profile(path: Path) -> dict[str, Any]:
    """One receipt passes when its id is still in the backend's profiles."""
    receipt = _read_receipt(path)
    profile_id = str(receipt.get("id", ""))
    if not profile_id:
        raise ValueError(f"{path.name}: the receipt names no profile id")
    try:
        rows = _profile_rows(_base_url())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"GET {PROFILES_PATH} failed: {exc}") from None
    ids = {str(entry.get("id", "")) for entry in rows}
    return {
        "file": path.name,
        "passed": profile_id in ids,
        "metrics": {"profile_id": profile_id, "profiles": len(rows)},
        "thresholds": {},
        "verifier": PROFILE_VERIFIER,
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    """Transcribe each asset and measure it against its clip's text."""
    if req.capability == PROFILE_CAPABILITY:
        return {"assets": [_verify_profile(path) for path in req.assets]}
    params = dict(req.inputs)
    clips = {clip["name"]: clip for clip in _clips(params)}
    whisper = _whisper(req)
    entries = []
    for path in req.assets:
        clip = clips.get(path.stem)
        if clip is None:
            raise ValueError(f"{path.name}: no clip named {path.stem!r} in the piece")
        transcript = _transcribe(whisper, path, clip["language"])
        score, reference = _score(clip, transcript)
        entries.append(
            {
                "file": path.name,
                "passed": score <= WER_MAX,
                "metrics": {
                    "wer": round(score, 4),
                    "words": len(reference),
                    "transcript": transcript,
                },
                "thresholds": {"wer_max": WER_MAX},
                "verifier": VERIFIER,
            }
        )
    return {"assets": entries}


def _audio() -> Any:
    """The package's audio helpers, imported only when a verb needs them."""
    return importlib.import_module("facet_lib.audiopreview")


def _preview_profile(req: Request, path: Path) -> dict[str, Any]:
    """The generic viewer's preview file for a profile receipt."""
    receipt = _read_receipt(path)
    profile_id = str(receipt.get("id", ""))
    name = str(receipt.get("name", ""))
    language = str(receipt.get("language", ""))
    data = {
        "preview": 1,
        "kind": "text",
        "summary": f"profile {name[:80]} · {language} · {profile_id}",
        "fields": {"id": profile_id, "name": name, "language": language},
    }
    preview_name = f"{path.name}.preview.json"
    (req.out_dir / preview_name).write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"file": path.name, "preview": preview_name, "images": []}


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    """The audio preview file: waveform, loudness, and the speech check."""
    if req.capability == PROFILE_CAPABILITY:
        return {"assets": [_preview_profile(req, path) for path in req.assets]}
    params = dict(req.inputs)
    clips = {clip["name"]: clip for clip in _clips(params)}
    whisper = _whisper(req)
    audio = _audio()
    entries = []
    for path in req.assets:
        clip = clips.get(path.stem)
        if clip is None:
            raise ValueError(f"{path.name}: no clip named {path.stem!r} in the piece")
        preview_name = f"{path.name}.preview.json"
        (req.out_dir / preview_name).write_text(
            json.dumps(
                _preview_data(whisper, audio, path, clip), ensure_ascii=False, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
        entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _preview_data(whisper: Any, audio: Any, path: Path, clip: dict[str, Any]) -> dict[str, Any]:
    """Everything the audio viewer serves for one narrated clip."""
    samples, rate = audio.read_wav(path)
    duration = audio.duration_s(samples, rate)
    transcript = _transcribe(whisper, path, clip["language"])
    reference = textnorm.words(clip["text"], clip["language"])
    heard = textnorm.words(transcript, clip["language"])
    score = textnorm.wer(reference, heard)
    return {
        "preview": 1,
        "kind": "audio",
        "summary": (
            f"{duration:.1f} s · {clip['voice']} · {clip['model']} · WER {score * 100:.0f} %"
        ),
        "duration_s": round(duration, 3),
        "sample_rate_hz": int(rate),
        "channels": 1 if samples.ndim == 1 else int(samples.shape[1]),
        "waveform": audio.waveform(samples),
        "loudness": {
            "integrated_lufs": round(audio.integrated_lufs(samples, int(rate)), 2),
            "peak_dbfs": round(audio.peak_dbfs(samples), 2),
            # The backend renders as it likes; the runner never normalises.
            "target_lufs": None,
            "momentary": {
                "step_s": 0.1,
                "window_s": 0.4,
                "lufs": audio.momentary(samples, int(rate)),
            },
        },
        "silences": audio.silences(samples, int(rate)),
        "clipped_samples": audio.clipped_samples(samples),
        "speech": {
            "text": clip["text"],
            "transcript": transcript,
            "wer": round(score, 4),
            "alignment": textnorm.align(reference, heard),
        },
    }


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    """The package doctor: machine, imports and models, plus (full) the backend."""
    checks = [
        _doctor_gpu(),
        _doctor_vram(),
        _doctor_gpu_free(_base_url()),
        _doctor_imports(),
        _doctor_models(req),
    ]
    if req.depth == "full":
        base_url = _base_url()
        backend = _doctor_backend(base_url)
        checks.append(backend)
        if backend["ok"]:
            checks.append(_doctor_profile(base_url))
            for engine in _engines().SIDECAR_ENGINES:
                checks.append(_doctor_engine(base_url, engine))
    return {"checks": checks}


def _nvidia_smi(*args: str) -> subprocess.CompletedProcess[str] | None:
    """One nvidia-smi query, or ``None`` when the command cannot run."""
    try:
        return subprocess.run(
            ["nvidia-smi", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=NVIDIA_SMI_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _doctor_gpu() -> dict[str, Any]:
    """nvidia-smi sees an NVIDIA GPU: the manifest declares ``gpu = true``."""
    done = _nvidia_smi("-L")
    if done is None or done.returncode != 0:
        return _verdict("gpu", False, "nvidia-smi cannot run", "install the NVIDIA driver")
    lines = [line.rstrip() for line in done.stdout.splitlines() if line.strip()]
    if not lines:
        return _verdict("gpu", False, "nvidia-smi exited 0 but lists no GPU", "check nvidia-smi")
    return _verdict("gpu", True, lines[0])


def _doctor_vram() -> dict[str, Any]:
    """The GPU's VRAM is readable; the detail names total and free per GPU."""
    done = _nvidia_smi("--query-gpu=memory.total,memory.free", "--format=csv,noheader")
    if done is None or done.returncode != 0:
        return _verdict("vram", False, "nvidia-smi cannot read VRAM", "install the NVIDIA driver")
    rows = [row.strip() for row in done.stdout.splitlines() if row.strip()]
    if not rows:
        return _verdict("vram", False, "nvidia-smi reports no VRAM", "check nvidia-smi")
    return _verdict("vram", True, "; ".join(rows))


def _doctor_gpu_free(base_url: str) -> dict[str, Any]:
    """No model but the backend's holds GPU memory: one model at a time."""
    try:
        payload = _fetch_json(base_url, STATUS_PATH, HEALTH_TIMEOUT_S)
        state = _state(payload)
        if state in ("ready", "loading"):
            return _verdict(
                "gpu_free", True, f"the VoiceStudio backend at {base_url} owns the GPU ({state})"
            )
        if state == "idle":
            return _verdict(
                "gpu_free",
                True,
                f"the VoiceStudio backend at {base_url} answers idle: nothing loaded there "
                "(the VRAM rows above say what is free)",
            )
    except (urllib.error.URLError, OSError, ValueError):
        pass  # the backend is not answering: then nothing facet serves may hold the GPU
    done = _nvidia_smi("--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader")
    if done is None:
        return _verdict(
            "gpu_free", False, "nvidia-smi cannot list compute apps", "check nvidia-smi"
        )
    users = [line for line in done.stdout.splitlines() if line.strip()]
    ok = done.returncode == 0 and not users
    detail = "; ".join(users[:3]) if users else "no other process holds GPU memory"
    return _verdict("gpu_free", ok, detail, "stop the other GPU job: one model at a time")


def _verdict(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; a failure carries the fix that settles it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_imports() -> dict[str, Any]:
    """The four imports the runner leans on, each with its version."""
    found: list[str] = []
    broken: list[str] = []
    for module_name, distribution in DOCTOR_IMPORTS:
        try:
            module = importlib.import_module(module_name)
            found.append(f"{module_name} {getattr(module, '__version__', _version(distribution))}")
        except Exception as exc:  # catch-all: one broken import must not hide the rest
            broken.append(f"{module_name}: {exc}")
    detail = "; ".join(broken) if broken else ", ".join(found)
    return _verdict("imports", not broken, detail, "facet pull voicestudio")


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _doctor_models(req: Request) -> dict[str, Any]:
    """The embedded transcriber exists with the byte size the manifest claims.

    A backend-owned entry (``backend = true``, e.g. ``omnivoice``) declares no
    bytes and no source: the backend holds those weights, so the doctor skips
    its byte check and reports it as ``backend-owned: <id>``, mirroring the
    core doctor.
    """
    entries = _manifest().get("models", [])
    owned = [str(m["id"]) for m in entries if m.get("backend") is True]
    expected = {str(m["id"]): int(m["bytes"]) for m in entries if m.get("backend") is not True}
    problems: list[str] = []
    found: list[str] = [f"backend-owned: {model_id}" for model_id in sorted(owned)]
    for model_id, want in sorted(expected.items()):
        try:
            path = req.model_path(model_id)
        except KeyError:
            problems.append(f"{model_id}: not in this request")
            continue
        actual = _tree_bytes(path)
        if actual is None:
            problems.append(f"{model_id}: missing at {path}")
        elif actual != want:
            problems.append(f"{model_id}: {actual} bytes, manifest says {want}")
        else:
            found.append(f"{model_id} {actual} B")
    detail = "; ".join(problems) if problems else ", ".join(found)
    return _verdict("models", not problems, detail, "facet pull voicestudio")


def _tree_bytes(path: Path) -> int | None:
    """A file's size, a directory's summed sizes, or ``None`` when absent."""
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    return None


def _doctor_backend(base_url: str) -> dict[str, Any]:
    """The backend answers /model/status; facet starts it for each run."""
    try:
        payload = _fetch_json(base_url, STATUS_PATH, CONNECT_TIMEOUT_S)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return _verdict(
            "backend",
            False,
            f"not answering at {base_url}: {exc} — facet starts it for each run",
            "facet doctor voicestudio",
        )
    state = _state(payload)
    if state == "error":
        return _verdict(
            "backend",
            False,
            f"state error at {base_url}: {json.dumps(payload)[:200]}",
            "facet doctor voicestudio",
        )
    return _verdict("backend", True, f"{state}: {json.dumps(payload)[:120]}")


def _doctor_engine(base_url: str, engine: str) -> dict[str, Any]:
    """One sidecar engine's install status, read only: the doctor never POSTs."""
    try:
        status = _engines().engine_status(base_url, engine)
    except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
        return _verdict(f"engines-{engine}", False, f"GET install status failed: {exc}")
    if bool(status.get("installed")):
        return _verdict(
            f"engines-{engine}", True, f"{engine} installed at {status.get('install_dir')}"
        )
    size = _engines().ENGINE_SIZES_GB[engine]
    return _verdict(
        f"engines-{engine}",
        True,
        f"{engine} not installed yet; the first run that uses it installs it (~{size} GB)",
    )


def _profile_rows(base_url: str) -> list[dict[str, Any]]:
    """The backend's local voice profiles, unwrapped from the response body."""
    payload = _fetch_json(base_url, PROFILES_PATH, CONNECT_TIMEOUT_S)
    profiles = payload.get("profiles", payload) if isinstance(payload, dict) else payload
    if not isinstance(profiles, list):
        raise ValueError(f"{PROFILES_PATH} answered an unexpected body")
    return [entry for entry in profiles if isinstance(entry, dict)]


def _check_clone_engine(clips: list[dict[str, Any]]) -> None:
    """A clone piece speaks with cosyvoice only: one engine per piece."""
    if any(clip["model"] != CLONE_ENGINE for clip in clips):
        raise ValueError("one engine per piece: voicestudio.clone speaks with cosyvoice only")


def _check_clone_voice(base_url: str, voice: str) -> None:
    """A clone piece speaks only with a profile installed on this machine."""
    try:
        profiles = _profile_rows(base_url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"GET {PROFILES_PATH} failed: {exc}") from None
    ids = {str(entry.get("id", "")) for entry in profiles}
    if voice not in ids:
        raise ValueError(
            f"clone voice {voice} is not installed in this backend; {CLONE_PROFILE_SPEC}"
        )


def _doctor_profile(base_url: str) -> dict[str, Any]:
    """The default cloned voice exists, or the doctor names the recipe."""
    try:
        profiles = _profile_rows(base_url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return _verdict("profile", False, f"GET {PROFILES_PATH} failed: {exc}")
    names = {str(entry.get("name", "")) for entry in profiles}
    if DEFAULT_VOICE in names:
        return _verdict("profile", True, f"{DEFAULT_VOICE} registered")
    return _verdict(
        "profile",
        False,
        f"no {DEFAULT_VOICE} in {PROFILES_PATH} — create it with: {PROFILE_RECIPE}",
        PROFILE_RECIPE,
    )


runner.main()
