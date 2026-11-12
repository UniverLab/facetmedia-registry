"""The moss package runner: described sound effects with MOSS-SoundEffect v2.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` generates one effect from an English
description and normalises it to ``target-lufs``, ``verify`` measures each
WAV's loudness against that target, ``preview`` writes the audio preview
file, ``doctor`` checks the machine (an NVIDIA GPU, the RAM the CPU stage
needs) plus the package (imports, the pinned source checkout, the model files).

The pipeline code is the ``moss_soundeffect_v2`` package inside the
facet-managed MOSS-TTS source checkout ``[engine.source]`` pins, passed to
the runner as ``FACET_SOURCE_DIR``; there is no ``[engine.server]`` — the
checkout ships no HTTP server, so the runner puts the checkout on
``sys.path`` and drives ``MossSoundEffectPipeline`` in-process. Its
third-party dependencies are ordinary pip packages. ``MOSS_DIR`` remains
only for a manual run outside facet.

Memory rule: a full GPU load of this model needs ~9 GB and spills into
shared memory on the 8 GB card, so ``run`` never does one. The pipeline
loads on the CPU and only the active stage moves to the GPU
(``vram_management_enabled``); before loading, the runner estimates that
staged peak and refuses with a plain error when it cannot fit the card.

Heavy imports go through ``importlib`` inside the functions, so a broken
environment still lets the doctor report *which* import fails.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

from facet_runner_sdk import Request, Runner

#: torch.compile's first call takes minutes; the lab's efectos.py disables it.
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

runner = Runner()

#: The one capability this package serves.
CAPABILITY = "moss.sfx"
#: The manifest model id and the pipeline's HF repo id.
MODEL = "moss-soundeffect-v2"
MODEL_REPO = "OpenMOSS-Team/MOSS-SoundEffect-v2.0"
#: ``[engine.source]`` pins this; a manual MOSS_DIR checkout must match it.
CODE_REV = "934d6826b084c46a0d033402174d5f8ac4ed2519"
#: The loudness an effect is normalised to under voice; hits pass a louder one.
TARGET_LUFS = -23.0
#: What verify measures with, named for the record.
VERIFIER = "audiopreview"
#: The loudness a WAV may miss ``target-lufs`` by (manifest threshold).
LUFS_TOL = 1.0
#: The card the staged path is built for, in GiB.
GPU_BUDGET_GB = 8.0
GIB = 1024**3
#: What a naive full-GPU load of the pinned model costs, measured on the
#: reference card: ~9 GB, over its 8 GB — the reason the staged path exists.
FULL_LOAD_GB = 9.0
#: The largest single stage the engine moves to the GPU at once: the bf16
#: Qwen3-1.7B text encoder (~3.4 GB) plus attention/workspace headroom.
STAGE_PEAK_GB = 4.0
#: The CPU side of the staged path holds the whole model (~9 GB of weights).
CPU_STAGE_GB = 10.0
#: Generation defaults, the ones the lab's efectos.py uses.
SECONDS_MAX = 30.0
INFERENCE_STEPS = 100
CFG_SCALE = 4.0
SEED = 0
#: The fix every failing package check names.
PULL_FIX = "facet pull moss"
#: Imports the doctor proves, with the distribution each comes from.
DOCTOR_IMPORTS = (
    ("torch", "torch"),
    ("moss_soundeffect_v2", "moss-soundeffect-v2"),
    ("soundfile", "soundfile"),
    ("numpy", "numpy"),
    ("pyloudnorm", "pyloudnorm"),
)
NVIDIA_SMI_TIMEOUT_S = 4.0
MEMINFO_PATH = Path("/proc/meminfo")
#: The pipeline is asked for mono; a stereo answer is mixed down.
MONO_CHANNELS = 1
#: ndarray ndim of a (channels, samples) waveform.
CHANNELS_NDIM = 2


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    """The manifest's tool identity, so records name the real tool."""
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _audio() -> Any:
    """The registry's audio helpers, imported only when a verb needs them."""
    return importlib.import_module("facet_lib.audiopreview")


def _params(inputs: dict[str, Any]) -> dict[str, Any]:
    """The effect's fields with the manifest defaults resolved."""
    return {
        "description": str(inputs["description"]),
        "seconds": float(inputs["seconds"]),
        "name": str(inputs["name"]),
        "target-lufs": float(inputs.get("target-lufs", TARGET_LUFS)),
        "steps": int(inputs.get("steps", INFERENCE_STEPS)),
        "guidance": float(inputs.get("guidance", CFG_SCALE)),
        "seed": int(inputs.get("seed", SEED)),
    }


def _check_memory() -> None:
    """Refuse what the staged CPU/GPU path cannot hold on this card.

    A full GPU load is ~9 GB — over the 8 GB budget — so the runner never
    attempts one; it refuses only when even the largest staged stage does
    not fit the GPU the request would run on.
    """
    torch = importlib.import_module("torch")
    if not torch.cuda.is_available():
        raise RuntimeError(
            "memory rule: moss.sfx needs an NVIDIA GPU — the model loads on "
            "CPU and only the active stage moves to the card; there is no CPU path"
        )
    _free, total = torch.cuda.mem_get_info()
    total_gb = total / GIB
    if total_gb < STAGE_PEAK_GB:
        raise RuntimeError(
            f"memory rule: the staged path peaks at ~{STAGE_PEAK_GB:.0f} GB on the "
            f"GPU (a full load would need ~{FULL_LOAD_GB:.0f} GB, over the "
            f"{GPU_BUDGET_GB:.0f} GB budget) but the card has {total_gb:.1f} GB"
        )


def _moss_dir() -> Path:
    """The facet-managed MOSS-TTS checkout, or a manual ``MOSS_DIR`` one."""
    facet_dir = os.environ.get("FACET_SOURCE_DIR")
    if facet_dir:
        return Path(facet_dir)
    manual = os.environ.get("MOSS_DIR")
    if manual:
        return Path(manual).expanduser()
    raise RuntimeError(
        f"no MOSS-TTS source: run through facet ({PULL_FIX}), or set MOSS_DIR "
        f"to a MOSS-TTS checkout at {CODE_REV[:12]}"
    )


def _ensure_moss_path() -> None:
    """Put the pinned checkout on ``sys.path`` when the package is not installed.

    A pulled environment has no ``moss_soundeffect_v2`` distribution: the
    code lives in the facet-managed source checkout.
    """
    if importlib.util.find_spec("moss_soundeffect_v2") is not None:
        return
    source = _moss_dir()
    if not (source / "moss_soundeffect_v2").is_dir():
        raise RuntimeError(
            f"the MOSS-TTS source at {source} has no moss_soundeffect_v2: run {PULL_FIX}"
        )
    sys.path.insert(0, str(source))


def _load_pipeline(req: Request) -> Any:
    """MOSS-SoundEffect loaded on CPU; only the active stage reaches the GPU."""
    _ensure_moss_path()
    moss = importlib.import_module("moss_soundeffect_v2")
    torch = importlib.import_module("torch")
    pipe = moss.MossSoundEffectPipeline.from_pretrained(
        str(req.model_path(MODEL)),
        torch_dtype=torch.bfloat16,
        device="cpu",
    )
    for tensor in [*pipe.engine.dit.parameters(), *pipe.engine.dit.buffers()]:
        if tensor.is_floating_point():  # Module.to(dtype) would break the complex RoPE buffer
            tensor.data = tensor.data.to(torch.bfloat16)
    pipe.engine.device = "cuda"
    pipe.engine.vram_management_enabled = True
    return pipe


def _samples(audio: Any) -> Any:
    """The generated tensor as a 1-D float numpy waveform."""
    numpy = importlib.import_module("numpy")
    wave = audio[0].detach().float().cpu().numpy()
    if wave.ndim == CHANNELS_NDIM:
        wave = wave[0] if wave.shape[0] == MONO_CHANNELS else wave.mean(axis=0)
    return numpy.asarray(wave, dtype=numpy.float64).reshape(-1)


def _effect(pipe: Any, params: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """One effect: generate 30 s, the pipeline trims to ``seconds``, normalise."""
    audio = _audio()
    started = time.monotonic()
    generated = pipe(
        prompt=params["description"],
        seconds=params["seconds"],
        seed=params["seed"],
        num_inference_steps=params["steps"],
        cfg_scale=params["guidance"],
        negative_prompt="",
        progress_bar_cmd=lambda iterable, **_: iterable,
    )
    rate = int(pipe.sample_rate)
    samples = audio.normalize(_samples(generated), rate, params["target-lufs"])
    path = out_dir / f"{params['name']}.wav"
    audio.write_wav(path, samples, rate)
    lufs = audio.integrated_lufs(samples, rate)
    peak = audio.peak_dbfs(samples)
    properties = {
        "duration_s": round(audio.duration_s(samples, rate), 3),
        "sample_rate_hz": rate,
        "lufs": round(lufs, 2),
        "peak_dbfs": round(peak, 2),
        "peak_limited": _is_peak_limited(lufs, peak, params["target-lufs"], audio.PEAK_CAP_DBFS),
    }
    print(
        f"{path.name} ok ({properties['duration_s']:.1f} s in "
        f"{time.monotonic() - started:.1f} s; {properties['lufs']:.1f} LUFS, "
        f"peak {properties['peak_dbfs']:.1f} dBFS)",
        flush=True,
    )
    return {
        "file": path.name,
        "name": params["name"],
        "kind": "audio",
        "mime": "audio/wav",
        "properties": properties,
        "params": params,
        "seed": params["seed"],
        "inputs": [],
    }


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    if req.capability != CAPABILITY:
        raise ValueError(f"unknown capability: {req.capability}")
    params = _params(dict(req.inputs))
    seconds = params["seconds"]
    if not 0.0 < seconds <= SECONDS_MAX:
        raise ValueError(f"seconds must be in (0, {SECONDS_MAX:.0f}], got {seconds}")
    _check_memory()
    pipe = _load_pipeline(req)
    return {"tool": _tool(), "assets": [_effect(pipe, params, req.out_dir)]}


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    params = _params(dict(req.inputs))
    clips = {params["name"]: params}
    audio = _audio()
    entries = []
    for path in req.assets:
        params = _clip_for(clips, path)
        entries.append(_verify_one(audio, path, params))
    return {"assets": entries}


def _clip_for(clips: dict[str, dict[str, Any]], path: Path) -> dict[str, Any]:
    """The effect that produced this asset; the stem is its ``name``."""
    clip = clips.get(path.stem)
    if clip is None:
        raise ValueError(f"{path.name}: no effect named {path.stem!r} in the piece")
    return clip


def _is_peak_limited(lufs: float, peak: float, target: float, cap: float) -> bool:
    """A transient-heavy effect the normaliser held at the peak ceiling."""
    return lufs < target - LUFS_TOL and peak >= cap - 0.1


def _verify_one(audio: Any, path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """One WAV passes within ``lufs_tol`` of target, or peak-limited below it."""
    cap = audio.PEAK_CAP_DBFS
    thresholds = {"lufs_tol": LUFS_TOL, "peak_cap_dbfs": cap}
    target = float(params["target-lufs"])
    try:
        samples, rate = audio.read_wav(path)
        lufs = audio.integrated_lufs(samples, rate)
        peak = audio.peak_dbfs(samples)
    except (OSError, ValueError, RuntimeError) as exc:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"error": str(exc)},
            "thresholds": thresholds,
            "verifier": VERIFIER,
        }
    peak_limited = _is_peak_limited(lufs, peak, target, cap)
    passed = abs(lufs - target) <= LUFS_TOL or peak_limited
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {
            "lufs": round(lufs, 2),
            "target_lufs": target,
            "peak_dbfs": round(peak, 2),
            "duration_s": round(audio.duration_s(samples, rate), 3),
            "peak_limited": peak_limited and passed,
        },
        "thresholds": thresholds,
        "verifier": VERIFIER,
    }


def _preview_data(audio: Any, path: Path, target_lufs: float) -> dict[str, Any]:
    """The audio schema's fields for one effect."""
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
            "target_lufs": target_lufs,
            "momentary": {
                "step_s": 0.1,
                "window_s": 0.4,
                "lufs": audio.momentary(samples, int(rate)),
            },
        },
        "silences": audio.silences(samples, int(rate)),
        "clipped_samples": audio.clipped_samples(samples),
    }


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = _params(dict(req.inputs))
    clips = {params["name"]: params}
    audio = _audio()
    entries: list[dict[str, Any]] = []
    for path in req.assets:
        clip = _clip_for(clips, path)
        preview_name = f"{path.name}.preview.json"
        data = _preview_data(audio, path, float(clip["target-lufs"]))
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


def _doctor_gpu() -> dict[str, Any]:
    """nvidia-smi sees an NVIDIA GPU with the VRAM the staged path needs."""
    done = _nvidia_smi("--query-gpu=name,memory.total", "--format=csv,noheader")
    if done is None:
        return _check("gpu", False, "nvidia-smi cannot run", "install the NVIDIA driver")
    rows = [row.strip() for row in done.stdout.splitlines() if row.strip()]
    if done.returncode != 0 or not rows:
        return _check("gpu", False, "nvidia-smi reports no GPU", "install the NVIDIA driver")
    vram_mib = _vram_mib(rows)
    need_mib = int(STAGE_PEAK_GB * 1024)
    if vram_mib is not None and vram_mib < need_mib:
        return _check(
            "gpu",
            False,
            f"{'; '.join(rows)} — the staged path peaks at ~{STAGE_PEAK_GB:.0f} GB",
            f"use a GPU with at least ~{STAGE_PEAK_GB:.0f} GB of VRAM",
        )
    return _check("gpu", True, "; ".join(rows))


def _vram_mib(rows: list[str]) -> int | None:
    """The largest ``memory.total`` the query reported, in MiB, if parsable."""
    totals = []
    for row in rows:
        name, _, memory = row.rpartition(",")
        value, _, unit = memory.strip().partition(" ")
        if name and value.isdigit() and unit.strip() == "MiB":
            totals.append(int(value))
    return max(totals) if totals else None


def _doctor_ram() -> dict[str, Any]:
    """The CPU stage needs ~10 GB free-ish RAM; the machine has 19 GB total."""
    try:
        values = {
            line.split(":", 1)[0]: int(line.split()[1]) * 1024
            for line in MEMINFO_PATH.read_text(encoding="utf-8").splitlines()
            if ":" in line
        }
    except (OSError, ValueError, IndexError):
        return _check("ram", False, f"cannot read {MEMINFO_PATH}", "check /proc/meminfo")
    available_gb = values.get("MemAvailable", 0) / GIB
    ok = available_gb >= CPU_STAGE_GB
    detail = f"{available_gb:.1f} GiB available (the CPU stage needs ~{CPU_STAGE_GB:.0f} GiB)"
    return _check("ram", ok, detail, "close other heavy jobs: one model at a time")


def _doctor_imports(depth: str) -> dict[str, Any]:
    """The imports the runner leans on, each with its version."""
    # The source check reports a missing checkout with its own fix.
    with contextlib.suppress(Exception):
        _ensure_moss_path()
    if depth != "full":
        return _doctor_imports_quick()
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


def _doctor_imports_quick() -> dict[str, Any]:
    """Presence and version of each import, without loading any of them.

    The quick contract is imports, files, versions in about ten seconds; a
    cold ``import torch`` alone costs more than that. A missing spec is
    reported as the import failure it would be, so the detail keeps its
    shape and the full depth remains the way to catch a broken module.
    """
    found: list[str] = []
    broken: list[str] = []
    for module_name, distribution in DOCTOR_IMPORTS:
        try:
            spec = importlib.util.find_spec(module_name)
            if spec is None:
                raise ModuleNotFoundError(f"No module named {module_name!r}")
            found.append(f"{module_name} {_version(distribution)}")
        except Exception as exc:  # catch-all: one broken import must not hide the rest
            broken.append(f"{module_name}: {exc}")
    detail = "; ".join(broken) if broken else ", ".join(found)
    return _check("imports", not broken, detail, PULL_FIX)


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _doctor_source() -> dict[str, Any]:
    """The facet-managed MOSS-TTS checkout, or a manual one at the pinned commit."""
    try:
        source = _moss_dir()
    except RuntimeError as exc:
        return _check("source", False, str(exc), PULL_FIX)
    if not (source / "moss_soundeffect_v2").is_dir():
        return _check("source", False, f"no moss_soundeffect_v2 under {source}", PULL_FIX)
    if os.environ.get("FACET_SOURCE_DIR"):
        return _check("source", True, f"MOSS-TTS at {CODE_REV[:12]} ({source})")
    return _check_head(source)


def _check_head(source: Path) -> dict[str, Any]:
    """A manual ``MOSS_DIR`` checkout is at the pinned commit."""
    fix = PULL_FIX
    try:
        done = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=NVIDIA_SMI_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _check("source", False, f"git cannot read {source}", fix)
    head = done.stdout.strip()
    ok = done.returncode == 0 and head == CODE_REV
    detail = (
        f"MOSS-TTS at {CODE_REV[:12]} ({source})"
        if ok
        else f"{source} is at {head[:12] or '?'}, pinned is {CODE_REV[:12]}"
    )
    return _check("source", ok, detail, fix)


def _doctor_model(req: Request) -> dict[str, Any]:
    """The model files exist where facet put them."""
    try:
        path = Path(req.model_path(MODEL))
    except KeyError:
        return _check("model", False, f"{MODEL}: not in this request", PULL_FIX)
    ok = (path / "model_index.json").is_file()
    detail = f"{MODEL} at {path}" if ok else f"{path}: no model_index.json"
    return _check("model", ok, detail, PULL_FIX)


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [
        _doctor_gpu(),
        _doctor_ram(),
        _doctor_imports(req.depth),
        _doctor_source(),
        _doctor_model(req),
    ]
    return {"checks": checks}


runner.main()
