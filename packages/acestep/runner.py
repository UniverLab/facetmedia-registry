"""The acestep package runner: instrumental background beds with ACE-Step 1.5.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull). ``run`` refuses a caption that asks for voice, POSTs
``/release_task`` with an instrumental request, polls ``/query_result`` until
the server reports the job done, downloads the WAV from ``/v1/audio`` and
normalises it to -16 LUFS; ``verify`` measures each WAV's duration against
the piece's ``duracion`` and its peak against silence; ``preview`` writes the
audio preview file; ``doctor`` checks the machine (an NVIDIA GPU, its VRAM
readable, no other model holding the GPU) plus the package (imports, the
pinned checkout, its checkpoints) at ``quick`` depth, and the server at
``full`` depth.

ACE-Step itself is an ``[engine.server]``: facet clones the pinned revision,
builds its venv and starts ``uvicorn acestep.api_server:app`` for the
duration of the verb, passing the free port and the base URL through
``{{port}}`` and ``FACET_SERVER_URL``. The checkpoints are backend-owned: the
server fetches them into the checkout's ``checkpoints/`` on first start.

Heavy imports go through ``importlib`` inside the functions, so a broken
environment still lets the doctor report *which* import fails.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import re
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from facet_runner_sdk import Request, Runner

runner = Runner()

#: The one capability this package serves.
CAPABILITY = "acestep.bed"
#: The engine model a piece composes with.
MODEL = "acestep-v15-turbo"
#: The loudness the bed is normalised to under narration.
TARGET_LUFS = -16.0
#: What verify measures with, named for the record.
VERIFIER = "audiopreview"
#: A bed whose peak sits at or below this is silence, not music (manifest threshold).
PEAK_DBFS_MIN = -40.0
#: The duration a WAV may miss ``duracion`` by (manifest threshold).
DURATION_TOLERANCE_S = 1.0
#: The caption words that ask for sung music; the lab discards it forever.
VOICE_WORDS = re.compile(
    r"\b(voice|vocal|vocalist|sing|singer|singing|sung|choir|lyrics|rap|chant|speech)\b",
    re.IGNORECASE,
)
#: The fix every failing doctor check names.
PULL_FIX = "facet pull acestep"
#: The server facet starts for the verb; the fallback is a port nothing owns.
DEFAULT_SERVER_URL = "http://127.0.0.1:8189"
HEALTH_TIMEOUT_S = 2.0
HEALTHY_STATUS = (200, 300)
#: Seconds one release/poll request gets, and how long a job may run.
REQUEST_TIMEOUT_S = 120.0
RESULT_TIMEOUT_S = 900.0
RESULT_POLL_S = 2.0
#: The status integers ``/query_result`` reports: 1 done, 2 failed.
STATUS_DONE = 1
STATUS_FAILED = 2
ERROR_TAIL_CHARS = 2000
NVIDIA_SMI_TIMEOUT_S = 4.0
MOMENTARY_STEP_S = 0.1
MOMENTARY_WINDOW_S = 0.4
#: Manifest model id -> the directory under the checkout's ``checkpoints/``.
CHECKPOINT_DIRS = {
    "acestep-v15-turbo": "acestep-v15-turbo",
    "acestep-vae": "vae",
}
#: Imports the doctor proves, with the distribution each comes from.
DOCTOR_IMPORTS = (
    ("numpy", "numpy"),
    ("pyloudnorm", "pyloudnorm"),
    ("soundfile", "soundfile"),
)


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity and the server pin."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    """The manifest's tool identity, so records name the real tool."""
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _audio() -> Any:
    """The registry's audio helpers, imported only when a verb needs them."""
    return importlib.import_module("facet_lib.audiopreview")


def _server_dir() -> Path:
    """The checkout ``facet pull`` made, under ``<home>/servers/<name>/<version>``.

    ``FACET_MODELS`` is ``<home>/models/direct``, so two parents reach the
    facet home; the checkout's own directory is named after the short rev.
    """
    home = Path(os.environ.get("FACET_MODELS", "")).parent.parent
    manifest = _manifest()
    rev = str(manifest["engine"]["server"]["rev"])
    return home / "servers" / str(manifest["name"]) / str(manifest["version"]) / rev[:12]


def _server_url() -> str:
    return os.environ.get("FACET_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")


def _require_instrumental(caption: str) -> None:
    """Refuse a caption that asks for voice: this lab's music is instrumental only."""
    match = VOICE_WORDS.search(caption)
    if match is None:
        return
    raise ValueError(
        f"caption asks for {match.group(0)!r}: music here is always instrumental, never sung; "
        "describe acoustic instruments and ask for "
        "'No drums, no percussion, no bass beat, no synthesizers'"
    )


def _post(path: str, payload: dict[str, Any], timeout: float = REQUEST_TIMEOUT_S) -> Any:
    """One JSON POST to the server, its decoded answer."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        _server_url() + path,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:ERROR_TAIL_CHARS]
        raise RuntimeError(f"ACE-Step answered {error.code} on {path}: {detail}") from None


def _data(answer: Any) -> Any:
    """The payload inside ACE-Step's ``{data, code, error, ...}`` envelope."""
    return answer.get("data") if isinstance(answer, dict) else None


def _submit(caption: str, duration: float) -> str:
    """Queue one instrumental track; the server answers the task id that owns it."""
    body = {
        "prompt": caption,
        "lyrics": "[Instrumental]",
        "audio_duration": duration,
        "audio_format": "wav",
        "model": MODEL,
        "task_type": "text2music",
        "thinking": False,
    }
    data = _data(_post("/release_task", body))
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if not isinstance(task_id, str) or not task_id:
        raise RuntimeError("ACE-Step answered no task id")
    return task_id


def _first_file(item: dict[str, Any]) -> str:
    """The first audio URL of a finished job's result, or a failure naming it."""
    raw = item.get("result")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        parsed = None
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        file = parsed[0].get("file")
        if isinstance(file, str) and file:
            return file
    raise RuntimeError(f"ACE-Step finished without an audio file: {str(raw)[:ERROR_TAIL_CHARS]}")


def _poll(task_id: str) -> str:
    """Poll ``/query_result`` every two seconds until status 1 (2 means failed)."""
    deadline = time.monotonic() + RESULT_TIMEOUT_S
    status: Any = "queued"
    while time.monotonic() < deadline:
        data = _data(_post("/query_result", {"task_id_list": [task_id]}))
        item = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
        if item is not None:
            status = item.get("status")
            if status == STATUS_DONE:
                return _first_file(item)
            if status == STATUS_FAILED:
                raise RuntimeError(f"{task_id}: ACE-Step failed: {item.get('result', '')}")
        time.sleep(RESULT_POLL_S)
    raise RuntimeError(f"{task_id}: ACE-Step did not finish within {RESULT_TIMEOUT_S:.0f} s")


def _download(url: str) -> bytes:
    """One GET of the served audio; the answer bytes are the WAV."""
    with urllib.request.urlopen(_server_url() + url, timeout=REQUEST_TIMEOUT_S) as response:
        return response.read()


def _properties(audio: Any, samples: Any, rate: int) -> dict[str, Any]:
    """The measured level record of one bed."""
    return {
        "duration_s": round(audio.duration_s(samples, rate), 3),
        "sample_rate_hz": int(rate),
        "lufs": round(audio.integrated_lufs(samples, rate), 2),
        "peak_dbfs": round(audio.peak_dbfs(samples), 2),
    }


def _asset(
    path: Path, caption: str, name: str, duration: float, properties: dict[str, Any]
) -> dict[str, Any]:
    """One bed's record: the written WAV, its level and its params."""
    return {
        "file": path.name,
        "name": name,
        "kind": "audio",
        "mime": "audio/wav",
        "properties": properties,
        "params": {"caption": caption, "name": name, "duracion": duration},
        "seed": None,
        "inputs": [],
    }


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    if req.capability != CAPABILITY:
        raise ValueError(f"unknown capability: {req.capability}")
    params = dict(req.inputs)
    caption = str(params["caption"])
    name = str(params["name"])
    duration = float(params["duracion"])
    _require_instrumental(caption)
    audio = _audio()
    path = req.out_dir / f"{name}.wav"
    path.write_bytes(_download_asset(caption, duration))
    samples, rate = audio.read_wav(path)
    samples = audio.normalize(samples, rate, TARGET_LUFS)
    audio.write_wav(path, samples, rate)
    properties = _properties(audio, samples, rate)
    print(
        f"{path.name} ok ({properties['duration_s']:.1f} s; "
        f"{properties['lufs']:.1f} LUFS, peak {properties['peak_dbfs']:.1f} dBFS)",
        flush=True,
    )
    return {"tool": _tool(), "assets": [_asset(path, caption, name, duration, properties)]}


def _download_asset(caption: str, duration: float) -> bytes:
    """Queue, wait and fetch one track's bytes."""
    return _download(_poll(_submit(caption, duration)))


def _verify_one(audio: Any, path: Path, expected: float) -> dict[str, Any]:
    """One WAV passes when its duration matches and it is louder than silence."""
    thresholds = {
        "duration_tolerance_s": DURATION_TOLERANCE_S,
        "peak_dbfs_min": PEAK_DBFS_MIN,
    }
    try:
        samples, rate = audio.read_wav(path)
        measured = audio.duration_s(samples, rate)
        peak = audio.peak_dbfs(samples)
    except (OSError, ValueError, RuntimeError) as exc:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"error": str(exc)},
            "thresholds": thresholds,
            "verifier": VERIFIER,
        }
    passed = abs(measured - expected) <= DURATION_TOLERANCE_S and peak > PEAK_DBFS_MIN
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {"duration_s": round(measured, 3), "peak_dbfs": round(peak, 2)},
        "thresholds": thresholds,
        "verifier": VERIFIER,
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    audio = _audio()
    expected = float(dict(req.inputs)["duracion"])
    return {"assets": [_verify_one(audio, path, expected) for path in req.assets]}


def _preview_data(audio: Any, path: Path) -> dict[str, Any]:
    """The audio schema's fields, normalised to the bed's target loudness."""
    samples, rate = audio.read_wav(path)
    duration = audio.duration_s(samples, rate)
    lufs = audio.integrated_lufs(samples, rate)
    peak = audio.peak_dbfs(samples)
    summary = f"{path.stem} · {duration:.1f} s · {lufs:.1f} LUFS · peak {peak:.1f} dBFS"
    return {
        "preview": 1,
        "kind": "audio",
        "summary": summary[:160],
        "duration_s": round(duration, 3),
        "sample_rate_hz": int(rate),
        "channels": audio.channels(samples),
        "waveform": audio.waveform(samples),
        "loudness": {
            "integrated_lufs": round(lufs, 2),
            "peak_dbfs": round(peak, 2),
            "target_lufs": TARGET_LUFS,
            "momentary": {
                "step_s": MOMENTARY_STEP_S,
                "window_s": MOMENTARY_WINDOW_S,
                "lufs": audio.momentary(samples, int(rate)),
            },
        },
        "silences": audio.silences(samples, int(rate)),
        "clipped_samples": audio.clipped_samples(samples),
    }


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    audio = _audio()
    entries: list[dict[str, Any]] = []
    for path in req.assets:
        preview_name = f"{path.name}.preview.json"
        data = _preview_data(audio, path)
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names what fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


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


def _healthy(url: str) -> bool:
    """True when ``url`` answers 2xx within the short health timeout."""
    try:
        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_S) as response:
            status: int = response.status
            return HEALTHY_STATUS[0] <= status < HEALTHY_STATUS[1]
    except (OSError, ValueError):
        return False


def _doctor_gpu() -> dict[str, Any]:
    """nvidia-smi sees an NVIDIA GPU."""
    done = _nvidia_smi("-L")
    if done is None:
        return _check("gpu", False, "nvidia-smi cannot run", "install the NVIDIA driver")
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    ok = done.returncode == 0 and bool(lines)
    detail = lines[0] if ok else f"nvidia-smi exited {done.returncode} with no GPU"
    return _check("gpu", ok, detail, "install the NVIDIA driver")


def _doctor_vram() -> dict[str, Any]:
    """The GPU's VRAM is readable; the detail names total and free per GPU."""
    done = _nvidia_smi("--query-gpu=memory.total,memory.free", "--format=csv,noheader")
    if done is None or done.returncode != 0:
        return _check("vram", False, "nvidia-smi cannot read VRAM", "install the NVIDIA driver")
    rows = [row.strip() for row in done.stdout.splitlines() if row.strip()]
    if not rows:
        return _check("vram", False, "nvidia-smi reports no VRAM", "check nvidia-smi")
    return _check("vram", True, "; ".join(rows))


def _doctor_gpu_free() -> dict[str, Any]:
    """No other process holds GPU memory: one model at a time."""
    if _healthy(_server_url() + "/health"):
        return _check("gpu_free", True, "the server facet started owns the GPU")
    done = _nvidia_smi("--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader")
    if done is None:
        return _check("gpu_free", False, "nvidia-smi cannot list compute apps", "check nvidia-smi")
    users = [line for line in done.stdout.splitlines() if line.strip()]
    ok = done.returncode == 0 and not users
    detail = "no other process holds GPU memory" if ok else "; ".join(users[:3])
    return _check("gpu_free", ok, detail, "stop the other GPU job: one model at a time")


def _doctor_imports() -> dict[str, Any]:
    """The imports the runner leans on, each with its version."""
    found: list[str] = []
    broken: list[str] = []
    for module_name, distribution in DOCTOR_IMPORTS:
        try:
            module = importlib.import_module(module_name)
            found.append(f"{module_name} {getattr(module, '__version__', _version(distribution))}")
        except Exception as exc:  # catch-all: one broken import must not hide the rest
            broken.append(f"{module_name}: {exc}")
    detail = "; ".join(broken) if broken else ", ".join(found)
    return _check("imports", not broken, detail, PULL_FIX)


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _doctor_checkout() -> dict[str, Any]:
    """The pinned checkout exists with its ``acestep/api_server.py``."""
    checkout = _server_dir()
    ok = (checkout / "acestep" / "api_server.py").is_file()
    detail = f"ACE-Step checkout at {checkout}" if ok else f"{checkout}: no acestep/api_server.py"
    return _check("checkout", ok, detail, PULL_FIX)


def _doctor_models() -> dict[str, Any]:
    """The server's checkpoints are present: ACE-Step owns those weights."""
    root = _server_dir() / "checkpoints"
    present: list[str] = []
    problems: list[str] = []
    for model_id, folder in CHECKPOINT_DIRS.items():
        path = root / folder
        if path.is_dir():
            present.append(model_id)
        else:
            problems.append(f"{model_id}: missing at {path}")
    detail = f"checkpoints for {', '.join(present)}" if not problems else "; ".join(problems)
    return _check("models", not problems, detail, PULL_FIX)


def _doctor_server() -> dict[str, Any]:
    """Full depth: the server facet started for the doctor answers /health."""
    url = _server_url() + "/health"
    ok = _healthy(url)
    detail = f"{url} answers" if ok else f"{url} does not answer"
    return _check("server", ok, detail, "run a piece so facet starts ACE-Step; check its log")


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [
        _doctor_gpu(),
        _doctor_vram(),
        _doctor_gpu_free(),
        _doctor_imports(),
        _doctor_checkout(),
        _doctor_models(),
    ]
    if req.depth == "full":
        checks.append(_doctor_server())
    return {"checks": checks}


runner.main()
