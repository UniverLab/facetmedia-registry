"""The moss pull/run/verify/preview/doctor cycle, with no facetmedia import and no GPU.

The test stands in for the package environment: it runs ``runner.py`` as a
subprocess against a stub ``facet_runner_sdk``, a stub
``facet_lib.audiopreview`` (the same canned measurement the acestep cycle
uses), a stub ``torch`` whose CUDA answers are canned, and a stub
``moss_soundeffect_v2`` whose pipeline records how it was loaded and
returns a sine wave. A ``.dist-info`` on the same ``PYTHONPATH`` makes the
pinned-source doctor check pass.

The memory-guard test needs no model: the stub torch reports a card too
small for the staged peak, and the runner must exit nonzero naming the
memory rule — what facet reports as ``runner_failed``. No test touches a
real GPU.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "moss"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
SKILL = (PACKAGE / "skill" / "SKILL.md").read_text(encoding="utf-8")
PREVIEW_SCHEMA: dict[str, Any] = json.loads(
    (ROOT / "schemas" / "preview" / "audio.schema.json").read_text(encoding="utf-8")
)

DESCRIPCION = "Soft rain on a window with distant thunder"
NAME = "lluvia-ventana"
SEGUNDOS = 2.0
TARGET_LUFS = -23.0
LUFS_TOL = 1.0
RATE_HZ = 48000
MODEL_ID = "moss-soundeffect-v2"
DURATION_TOL_S = 0.01
FLOAT_TOL = 0.05
INFERENCE_STEPS = 100
DEFAULT_GUIDANCE = 4.0
DEFAULT_SEED = 0
STEPS_MIN = 1
STEPS_MAX = 200
GUIDANCE_MIN = 0.0
GUIDANCE_MAX = 20.0
SEED_MIN = 0
#: Overrides a piece can set; guidance 0 is a valid value (no guidance).
OVERRIDE_STEPS = 50
OVERRIDE_GUIDANCE = 0.0
OVERRIDE_SEED = 7
RAM_GB = 19
MAX_SEGUNDOS = 30
DEFAULT_TARGET_LUFS = -23.0
TARGET_MIN_LUFS = -30.0
TARGET_MAX_LUFS = -10.0
DESCRIPTION_MIN = 20
DESCRIPTION_MAX = 200
PULL_FIX = "facet pull moss"
#: The waveform bins the audio preview schema fixes.
WAVEFORM_BINS = 1200
CODE_REV = "934d6826b084c46a0d033402174d5f8ac4ed2519"

#: The pull-time SDK surface the runner touches; the real one is copied in.
STUB_SDK = """
import json
import sys
from pathlib import Path


class Request:
    def __init__(self, data):
        self.verb = str(data.get("verb", ""))
        self.capability = str(data.get("capability", ""))
        self.depth = str(data.get("depth", "quick"))
        self.inputs = dict(data.get("inputs") or {})
        self.out_dir = Path(str(data.get("out_dir", "")))
        self.piece_dir = Path(str(data.get("piece_dir", "")))
        self.assets = [Path(str(item)) for item in data.get("assets") or []]
        self._models = {str(k): Path(str(v)) for k, v in (data.get("models") or {}).items()}

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def model_path(self, model_id):
        return self._models[model_id]


class Runner:
    def __init__(self):
        self._verbs = {}

    def verb(self, name):
        def register(function):
            self._verbs[name] = function
            return function

        return register

    def run(self, argv):
        verb, *rest = argv
        values = {rest[index]: rest[index + 1] for index in range(0, len(rest), 2)}
        result = self._verbs[verb](Request.from_file(values["--input"]))
        Path(values["--result"]).write_text(json.dumps(result))
        return 0

    def main(self):
        raise SystemExit(self.run(sys.argv[1:]))
"""

#: A stub facet_lib.audiopreview: the measurement the runner leans on, stdlib
#: plus numpy, so the cycle needs neither soundfile nor pyloudnorm installed.
STUB_AUDIO = """
import math
import wave

import numpy

PEAK_CAP_DBFS = -1.0


def read_wav(path):
    with wave.open(str(path), "rb") as reader:
        rate = reader.getframerate()
        count = reader.getnchannels()
        raw = reader.readframes(reader.getnframes())
    data = numpy.frombuffer(raw, dtype="<i2").astype(numpy.float64) / 32768.0
    if count > 1:
        data = data.reshape(-1, count)
    return data, rate


def write_wav(path, samples, rate):
    mono = samples if samples.ndim == 1 else samples.mean(axis=1)
    pcm = (numpy.clip(mono, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(int(rate))
        writer.writeframes(pcm.tobytes())


def duration_s(samples, rate):
    return len(samples) / rate if rate else 0.0


def _db(level):
    return 20.0 * math.log10(level) if level > 0 else -160.0


def integrated_lufs(samples, rate):
    mono = samples if samples.ndim == 1 else samples.mean(axis=1)
    return _db(float(numpy.sqrt(numpy.mean(numpy.square(mono))))) if len(mono) else -160.0


def peak_dbfs(samples):
    mono = samples if samples.ndim == 1 else samples.mean(axis=1)
    return _db(float(numpy.max(numpy.abs(mono)))) if len(mono) else -160.0


def normalize(samples, rate, target_lufs):
    gain_db = target_lufs - integrated_lufs(samples, rate)
    headroom_db = -1.0 - peak_dbfs(samples)
    applied = min(gain_db, headroom_db)
    return samples * (10.0 ** (applied / 20.0))


def channels(samples):
    return 1 if samples.ndim == 1 else int(samples.shape[1])


def waveform(samples):
    mono = samples if samples.ndim == 1 else samples.mean(axis=1)
    if len(mono) == 0:
        return {"bins": 1200, "min": [0.0] * 1200, "max": [0.0] * 1200}
    edges = numpy.linspace(0, len(mono), 1201).astype(int)
    mins = []
    maxs = []
    for index in range(1200):
        start = edges[index]
        chunk = mono[start:max(edges[index + 1], start + 1)]
        mins.append(round(float(numpy.min(chunk)), 6))
        maxs.append(round(float(numpy.max(chunk)), 6))
    return {"bins": 1200, "min": mins, "max": maxs}


def momentary(samples, rate):
    mono = samples if samples.ndim == 1 else samples.mean(axis=1)
    window = int(0.4 * rate)
    step = max(int(0.1 * rate), 1)
    curve = []
    for start in range(0, len(mono), step):
        value = integrated_lufs(mono[start:start + window], rate)
        curve.append(round(value, 2) if value > -70.0 else None)
    return curve


def silences(samples, rate):
    return []


def clipped_samples(samples):
    mono = samples if samples.ndim == 1 else samples.mean(axis=1)
    return int(numpy.count_nonzero(numpy.abs(mono) >= 10 ** (-0.1 / 20.0)))
"""

#: A stub torch: CUDA answers come from the environment so the memory-guard
#: test can shrink the card without a GPU.
STUB_TORCH = """
import os


class _Cuda:
    @staticmethod
    def is_available():
        return os.environ.get("STUB_CUDA", "1") == "1"

    @staticmethod
    def mem_get_info():
        total = int(float(os.environ.get("STUB_VRAM_GB", "8")) * 1024**3)
        return total // 2, total


cuda = _Cuda()
bfloat16 = "torch.bfloat16"
__version__ = "2.9.0"
"""

#: A stub moss_soundeffect_v2: records the load on STUB_LOG and answers a
#: sine wave shaped like the real pipeline's (B, C, T) output.
STUB_MOSS = """
import json
import os

import numpy


class _Wave:
    def __init__(self, data):
        self._data = data

    def __getitem__(self, index):
        return _Wave(self._data[index])

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._data


class _Dit:
    def parameters(self):
        return iter(())

    def buffers(self):
        return iter(())


class _Engine:
    def __init__(self):
        self.dit = _Dit()
        self.device = "cpu"
        self.vram_management_enabled = False


class MossSoundEffectPipeline:
    sample_rate = 48000

    def __init__(self):
        self.engine = _Engine()

    @classmethod
    def from_pretrained(cls, path, torch_dtype=None, device="cpu"):
        _record({"load": {"path": str(path), "dtype": str(torch_dtype), "device": device}})
        return cls()

    def __call__(self, prompt, seconds, seed, num_inference_steps, cfg_scale,
                 negative_prompt, progress_bar_cmd=None):
        _record({"call": {"prompt": prompt, "seconds": seconds, "seed": seed,
                          "steps": num_inference_steps, "cfg": cfg_scale,
                          "engine_device": self.engine.device,
                          "vram_management": self.engine.vram_management_enabled}})
        rate = self.sample_rate
        t = numpy.arange(int(rate * seconds)) / rate
        wave = 0.3 * numpy.sin(2 * numpy.pi * 220 * t)
        return _Wave(numpy.stack([wave]).astype("float32"))


def _record(entry):
    log = os.environ.get("STUB_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry) + "\\n")
"""

#: The two imports the doctor proves that the test environment lacks.
STUB_DIST = '"""Stub distribution the package environment provides."""\n\n__version__ = "0.0.0"\n'

#: A canned nvidia-smi answering the doctor's name/memory.total query.
FAKE_NVIDIA_SMI = """#!/bin/sh
case "$*" in
  *"memory.total"*) printf '%s\\n' "NVIDIA GeForce RTX 5060, ${FAKE_VRAM_MIB:-8151} MiB" ;;
  *"-L"*) printf '%s\\n' "GPU 0: NVIDIA GeForce RTX 5060" ;;
esac
"""

#: A canned git: ``rev-parse HEAD`` answers the pinned commit, anything else
#: delegates to the real binary.
FAKE_GIT = f"""#!/bin/sh
case "$*" in
  *rev-parse*) printf '%s\\n' "{CODE_REV}" ;;
  *) exec /usr/bin/git "$@" ;;
esac
"""

#: A canned git answering a drifted commit: the manual ``MOSS_DIR`` path
#: reports a HEAD far from the pinned one.
FAKE_GIT_DRIFT = """#!/bin/sh
case "$*" in
  *rev-parse*) printf '%s\\n' "0000000000000000000000000000000000000000" ;;
  *) exec /usr/bin/git "$@" ;;
esac
"""


def _stub_dir(tmp_path: Path) -> Path:
    """The PYTHONPATH stub: SDK, facet_lib.audiopreview, torch, moss, dists."""
    folder = tmp_path / "stub"
    folder.mkdir()
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    (folder / "torch.py").write_text(STUB_TORCH, encoding="utf-8")
    (folder / "moss_soundeffect_v2.py").write_text(STUB_MOSS, encoding="utf-8")
    (folder / "soundfile.py").write_text(STUB_DIST, encoding="utf-8")
    (folder / "pyloudnorm.py").write_text(STUB_DIST, encoding="utf-8")
    facet_lib = folder / "facet_lib"
    facet_lib.mkdir()
    (facet_lib / "__init__.py").write_text("", encoding="utf-8")
    (facet_lib / "audiopreview.py").write_text(STUB_AUDIO, encoding="utf-8")
    dist = folder / "moss_soundeffect_v2-0.1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: moss-soundeffect-v2\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (dist / "direct_url.json").write_text(
        json.dumps(
            {
                "url": "https://github.com/OpenMOSS/MOSS-TTS.git",
                "vcs_info": {"vcs": "git", "commit_id": CODE_REV},
            }
        ),
        encoding="utf-8",
    )
    return folder


def _clone_dir(tmp_path: Path) -> Path:
    """A fake MOSS-TTS clone: the package dir the runner and doctor look for."""
    clone = tmp_path / "moss-clone"
    package = clone / "moss_soundeffect_v2"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    return clone


def _model_dir(tmp_path: Path) -> Path:
    """A fake model checkout: the file the doctor looks for."""
    path = tmp_path / "model" / MODEL_ID
    path.mkdir(parents=True)
    (path / "model_index.json").write_text('{"_class_name": "MossSoundEffectPipeline"}')
    return path


def _environment(stub_dir: Path, home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "FACET_MODELS": str(home / "models" / "direct"),
    }
    if extra:
        env.update(extra)
    return env


def _request(
    verb: str,
    out: Path,
    piece: Path,
    inputs: dict[str, object],
    model: Path,
    assets: tuple[Path, ...] = (),
    depth: str = "quick",
) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "moss.sfx",
        "depth": depth,
        "inputs": dict(inputs),
        "out_dir": str(out),
        "piece_dir": str(piece),
        "models": {MODEL_ID: str(model)},
        "assets": [str(path) for path in assets],
    }


def _call(
    stub_dir: Path,
    verb: str,
    request: dict[str, object],
    tmp_path: Path,
    env: dict[str, str],
) -> tuple[dict[str, Any], str]:
    input_path = tmp_path / f"{verb}-request.json"
    result_path = tmp_path / f"{verb}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            verb,
            "--input",
            str(input_path),
            "--result",
            str(result_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(result_path.read_text(encoding="utf-8")), done.stdout


def _inputs(**overrides: object) -> dict[str, object]:
    inputs: dict[str, object] = {
        "description": DESCRIPCION,
        "seconds": SEGUNDOS,
        "name": NAME,
    }
    inputs.update(overrides)
    return inputs


def _run_cycle(
    tmp_path: Path, overrides: dict[str, object] | None = None
) -> tuple[dict[str, Any], str, Path, Path, Path]:
    """One run against the stubs: result, stdout, stub log, out dir, stub dir."""
    stub_dir = _stub_dir(tmp_path)
    home = tmp_path / "home"
    model = _model_dir(tmp_path)
    log = tmp_path / "stub.jsonl"
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(
        stub_dir, home, {"STUB_LOG": str(log), "STUB_VRAM_GB": "8", "STUB_CUDA": "1"}
    )
    result, printed = _call(
        stub_dir,
        "run",
        _request("run", out, tmp_path, _inputs(**(overrides or {})), model),
        tmp_path,
        env,
    )
    return result, printed, log, out, stub_dir


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _missing_required(data: object, schema: dict[str, Any], prefix: str = "") -> list[str]:
    """Every key a schema's ``required`` lists, missing from ``data``."""
    if not isinstance(data, dict):
        return [prefix or "<root>"]
    missing = [f"{prefix}{key}" for key in schema.get("required", []) if key not in data]
    for key, child in schema.get("properties", {}).items():
        if key in data and isinstance(child, dict) and "properties" in child:
            missing += _missing_required(data[key], child, f"{prefix}{key}.")
    return missing


def test_the_cycle_generates_normalises_and_records(tmp_path: Path) -> None:
    result, printed, log, out, _stub = _run_cycle(tmp_path)
    asset = result["assets"][0]
    assert asset["file"] == f"{NAME}.wav"
    assert (asset["kind"], asset["mime"]) == ("audio", "audio/wav")
    assert asset["params"] == {
        "description": DESCRIPCION,
        "seconds": SEGUNDOS,
        "name": NAME,
        "target-lufs": TARGET_LUFS,
        "steps": INFERENCE_STEPS,
        "guidance": DEFAULT_GUIDANCE,
        "seed": DEFAULT_SEED,
    }
    assert asset["seed"] == DEFAULT_SEED
    properties = asset["properties"]
    assert properties["sample_rate_hz"] == RATE_HZ
    assert abs(properties["duration_s"] - SEGUNDOS) <= DURATION_TOL_S
    assert abs(properties["lufs"] - TARGET_LUFS) <= FLOAT_TOL
    assert properties["peak_dbfs"] <= -1.0
    assert (out / f"{NAME}.wav").is_file()
    assert f"{NAME}.wav ok" in printed
    assert result["tool"]["name"] == "MOSS-SoundEffect v2"

    entries = _read_lines(log)
    load = next(entry["load"] for entry in entries if "load" in entry)
    call = next(entry["call"] for entry in entries if "call" in entry)
    # The staged path: loaded on the CPU, only the active stage on the GPU.
    assert load["device"] == "cpu"
    assert "bfloat16" in load["dtype"]
    assert call["engine_device"] == "cuda"
    assert call["vram_management"] is True
    assert call["prompt"] == DESCRIPCION
    assert call["seconds"] == SEGUNDOS
    assert call["steps"] == INFERENCE_STEPS
    assert call["cfg"] == DEFAULT_GUIDANCE
    assert call["seed"] == DEFAULT_SEED


def test_a_piece_can_set_its_steps_guidance_and_seed(tmp_path: Path) -> None:
    """An override reaches the pipeline and is recorded; guidance 0 is valid."""
    result, printed, log, _out, _stub = _run_cycle(
        tmp_path,
        {"steps": OVERRIDE_STEPS, "guidance": OVERRIDE_GUIDANCE, "seed": OVERRIDE_SEED},
    )
    asset = result["assets"][0]
    assert f"{NAME}.wav ok" in printed
    assert asset["params"]["steps"] == OVERRIDE_STEPS
    assert asset["params"]["guidance"] == OVERRIDE_GUIDANCE
    assert asset["params"]["seed"] == OVERRIDE_SEED
    assert asset["seed"] == OVERRIDE_SEED
    call = next(entry["call"] for entry in _read_lines(log) if "call" in entry)
    assert call["steps"] == OVERRIDE_STEPS
    assert call["cfg"] == OVERRIDE_GUIDANCE
    assert call["seed"] == OVERRIDE_SEED


def test_verify_and_preview_read_the_written_effect(tmp_path: Path) -> None:
    _result, _printed, _log, out, stub_dir = _run_cycle(tmp_path)
    home = tmp_path / "home"
    model = _model_dir(tmp_path / "second")
    env = _environment(stub_dir, home)
    clip = out / f"{NAME}.wav"

    verdict, _ = _call(
        stub_dir,
        "verify",
        _request("verify", out, tmp_path, _inputs(), model, (clip,)),
        tmp_path,
        env,
    )
    passed = verdict["assets"][0]
    assert passed["passed"] is True
    assert passed["thresholds"] == {"lufs_tol": LUFS_TOL, "peak_cap_dbfs": -1.0}
    assert passed["verifier"] == "audiopreview"
    assert abs(passed["metrics"]["lufs"] - TARGET_LUFS) <= FLOAT_TOL

    louder, _ = _call(
        stub_dir,
        "verify",
        _request("verify", out, tmp_path, _inputs(**{"target-lufs": -10.0}), model, (clip,)),
        tmp_path,
        env,
    )
    assert louder["assets"][0]["passed"] is False

    _call(
        stub_dir,
        "preview",
        _request("preview", out, tmp_path, _inputs(), model, (clip,)),
        tmp_path,
        env,
    )
    data = json.loads((out / f"{NAME}.wav.preview.json").read_text(encoding="utf-8"))
    assert _missing_required(data, PREVIEW_SCHEMA) == []
    assert set(data) == set(PREVIEW_SCHEMA["required"])
    assert data["kind"] == "audio"
    assert data["loudness"]["target_lufs"] == TARGET_LUFS
    assert len(data["waveform"]["max"]) == WAVEFORM_BINS


def test_a_card_too_small_for_the_staged_peak_is_refused(tmp_path: Path) -> None:
    """The memory rule: exit nonzero naming it, no WAV, no result file."""
    stub_dir = _stub_dir(tmp_path)
    home = tmp_path / "home"
    model = _model_dir(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(stub_dir, home, {"STUB_VRAM_GB": "2", "STUB_CUDA": "1"})
    request = _request("run", out, tmp_path, _inputs(), model)
    input_path = tmp_path / "refused-request.json"
    result_path = tmp_path / "refused-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            "run",
            "--input",
            str(input_path),
            "--result",
            str(result_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    output = done.stdout + done.stderr
    assert done.returncode != 0
    assert "memory rule" in output
    assert "8 GB" in output
    assert not result_path.exists()
    assert not (out / f"{NAME}.wav").exists()


def test_no_gpu_is_refused_with_the_same_rule(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    home = tmp_path / "home"
    model = _model_dir(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(stub_dir, home, {"STUB_CUDA": "0"})
    request = _request("run", out, tmp_path, _inputs(), model)
    input_path = tmp_path / "nogpu-request.json"
    result_path = tmp_path / "nogpu-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            "run",
            "--input",
            str(input_path),
            "--result",
            str(result_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    output = done.stdout + done.stderr
    assert done.returncode != 0
    assert "memory rule" in output
    assert not result_path.exists()


def _doctor(
    tmp_path: Path,
    stub_dir: Path,
    home: Path,
    model: Path,
    extra_env: dict[str, str] | None = None,
    git_stub: str = FAKE_GIT,
    depth: str = "full",
) -> dict[str, Any]:
    """The doctor verb on a canned nvidia-smi/git, the stubs, source and model."""
    machine = tmp_path / "fake-path"
    machine.mkdir(exist_ok=True)
    smi = machine / "nvidia-smi"
    smi.write_text(FAKE_NVIDIA_SMI, encoding="utf-8")
    smi.chmod(0o755)
    git = machine / "git"
    git.write_text(git_stub, encoding="utf-8")
    git.chmod(0o755)
    out = tmp_path / "doctor-out"
    out.mkdir(exist_ok=True)
    request = _request("doctor", out, tmp_path, {}, model, depth=depth)
    input_path = tmp_path / "doctor-request.json"
    result_path = tmp_path / "doctor-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "FACET_MODELS": str(home / "models" / "direct"),
        "FACET_SOURCE_DIR": str(_clone_dir(tmp_path)),
        "MOSS_DIR": "",
        "PATH": str(machine) + os.pathsep + os.environ["PATH"],
        **(extra_env or {}),
    }
    done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            "doctor",
            "--input",
            str(input_path),
            "--result",
            str(result_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(result_path.read_text(encoding="utf-8"))


def test_the_doctor_checks_machine_and_package(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    home = tmp_path / "home"
    model = _model_dir(tmp_path)
    result = _doctor(tmp_path, stub_dir, home, model)
    checks = {check["name"]: check for check in result["checks"]}
    assert set(checks) == {"gpu", "ram", "imports", "source", "model"}
    for name, check in checks.items():
        assert check["ok"] is True, f"{name}: {check['detail']}"

    (model / "model_index.json").unlink()
    broken = _doctor(tmp_path, stub_dir, home, model)
    model_check = {check["name"]: check for check in broken["checks"]}["model"]
    assert model_check["ok"] is False
    assert model_check["fix"] == PULL_FIX
    assert MODEL_ID in model_check["detail"]


def test_the_quick_doctor_imports_nothing(tmp_path: Path) -> None:
    """A module that explodes on import passes quick and fails full.

    The quick depth proves presence and version only, so a cold ``import
    torch`` no longer runs inside the ten second budget; the full depth still
    imports and catches the breakage.
    """
    stub_dir = _stub_dir(tmp_path)
    (stub_dir / "torch.py").write_text('raise RuntimeError("torch exploded")', encoding="utf-8")
    home = tmp_path / "home"
    model = _model_dir(tmp_path)
    quick = _doctor(tmp_path, stub_dir, home, model, depth="quick")
    imports = {check["name"]: check for check in quick["checks"]}["imports"]
    assert imports["ok"] is True, imports["detail"]
    assert imports["detail"].startswith("torch ")
    full = _doctor(tmp_path, stub_dir, home, model, depth="full")
    imports = {check["name"]: check for check in full["checks"]}["imports"]
    assert imports["ok"] is False
    assert "torch: torch exploded" in imports["detail"]


def test_the_doctor_refuses_a_card_too_small_for_the_staged_peak(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    home = tmp_path / "home"
    model = _model_dir(tmp_path)
    result = _doctor(tmp_path, stub_dir, home, model, {"FAKE_VRAM_MIB": "2048"})
    gpu = {check["name"]: check for check in result["checks"]}["gpu"]
    assert gpu["ok"] is False
    assert "staged path" in gpu["detail"]


def test_the_facet_source_dir_wins_over_moss_dir(tmp_path: Path) -> None:
    """Under facet the checkout wins even when ``MOSS_DIR`` points nowhere."""
    stub_dir = _stub_dir(tmp_path)
    home = tmp_path / "home"
    model = _model_dir(tmp_path)
    result = _doctor(tmp_path, stub_dir, home, model, {"MOSS_DIR": str(tmp_path / "missing")})
    source = {check["name"]: check for check in result["checks"]}["source"]
    assert source["ok"] is True
    assert "moss-clone" in source["detail"]


def test_the_facet_source_skips_the_git_check(tmp_path: Path) -> None:
    """Under facet a drifted git answer never reaches the source check."""
    stub_dir = _stub_dir(tmp_path)
    home = tmp_path / "home"
    model = _model_dir(tmp_path)
    result = _doctor(tmp_path, stub_dir, home, model, git_stub=FAKE_GIT_DRIFT)
    source = {check["name"]: check for check in result["checks"]}["source"]
    assert source["ok"] is True


def test_a_manual_checkout_is_pinned_by_git(tmp_path: Path) -> None:
    """Outside facet ``MOSS_DIR`` falls back to the git HEAD check."""
    stub_dir = _stub_dir(tmp_path)
    home = tmp_path / "home"
    model = _model_dir(tmp_path)
    clone = _clone_dir(tmp_path / "manual")
    env = {"FACET_SOURCE_DIR": "", "MOSS_DIR": str(clone)}
    result = _doctor(tmp_path, stub_dir, home, model, env)
    source = {check["name"]: check for check in result["checks"]}["source"]
    assert source["ok"] is True

    drifted = _doctor(tmp_path, stub_dir, home, model, env, git_stub=FAKE_GIT_DRIFT)
    drifted_source = {check["name"]: check for check in drifted["checks"]}["source"]
    assert drifted_source["ok"] is False
    assert f"pinned is {CODE_REV[:12]}" in drifted_source["detail"]


def test_no_source_at_all_names_the_pull(tmp_path: Path) -> None:
    """With neither variable the source check names the facet pull."""
    stub_dir = _stub_dir(tmp_path)
    home = tmp_path / "home"
    model = _model_dir(tmp_path)
    result = _doctor(tmp_path, stub_dir, home, model, {"FACET_SOURCE_DIR": "", "MOSS_DIR": ""})
    source = {check["name"]: check for check in result["checks"]}["source"]
    assert source["ok"] is False
    assert source["detail"] == (
        f"no MOSS-TTS source: run through facet ({PULL_FIX}), "
        f"or set MOSS_DIR to a MOSS-TTS checkout at {CODE_REV[:12]}"
    )
    assert source["fix"] == PULL_FIX


def test_the_manifest_declares_the_staged_in_process_package() -> None:
    assert MANIFEST["name"] == "moss"
    assert MANIFEST["facet"] == "audio"
    assert MANIFEST["uses"] == ["audiopreview"]
    engine = MANIFEST["engine"]
    assert engine["type"] == "python-env"
    assert engine["python"] == "3.12"
    assert engine["source"] == {
        "repo": "https://github.com/OpenMOSS/MOSS-TTS.git",
        "rev": CODE_REV,
    }
    assert "server" not in engine
    assert MANIFEST["transport"] == {"type": "cli", "entry": "runner.py"}
    requirements = MANIFEST["requirements"]
    assert requirements["gpu"] is True
    assert requirements["ram_gb"] == RAM_GB
    assert requirements["exclusive"] is True
    models = {model["id"]: model for model in MANIFEST["models"]}
    assert set(models) == {MODEL_ID}
    assert models[MODEL_ID]["hf_repo"] == "OpenMOSS-Team/MOSS-SoundEffect-v2.0"
    assert models[MODEL_ID]["spdx"] == "Apache-2.0"
    assert models[MODEL_ID]["commercial_use"] is True
    assert models[MODEL_ID]["requires_acceptance"] is False


def test_the_capability_inputs_and_thresholds() -> None:
    sfx = MANIFEST["capabilities"]["sfx"]
    assert sfx["kind"] == "audio"
    assert sfx["preview"]["viewer"] == "audio"
    inputs = sfx["inputs"]
    assert set(inputs) == {
        "description",
        "seconds",
        "name",
        "target-lufs",
        "steps",
        "guidance",
        "seed",
    }
    assert inputs["description"]["type"] == "string"
    assert inputs["description"]["required"] is True
    assert inputs["seconds"]["type"] == "number"
    assert inputs["seconds"]["required"] is True
    assert inputs["seconds"]["max"] == MAX_SEGUNDOS
    assert inputs["name"]["pattern"] == "^[a-z0-9][a-z0-9-]*$"
    assert inputs["target-lufs"]["default"] == DEFAULT_TARGET_LUFS
    assert inputs["target-lufs"]["min"] == TARGET_MIN_LUFS
    assert inputs["target-lufs"]["max"] == TARGET_MAX_LUFS
    assert inputs["steps"]["type"] == "integer"
    assert (inputs["steps"]["default"], inputs["steps"]["min"], inputs["steps"]["max"]) == (
        INFERENCE_STEPS,
        STEPS_MIN,
        STEPS_MAX,
    )
    assert inputs["guidance"]["type"] == "number"
    assert (
        inputs["guidance"]["default"],
        inputs["guidance"]["min"],
        inputs["guidance"]["max"],
    ) == (DEFAULT_GUIDANCE, GUIDANCE_MIN, GUIDANCE_MAX)
    assert inputs["seed"]["type"] == "integer"
    assert (inputs["seed"]["default"], inputs["seed"]["min"]) == (DEFAULT_SEED, SEED_MIN)
    assert sfx["verify"]["thresholds"] == {"lufs_tol": LUFS_TOL, "peak_cap_dbfs": -1.0}


def test_the_skill_has_the_front_matter_and_four_headings() -> None:
    first, second, *rest = SKILL.split("---", 2)
    assert first == "" and second.strip().startswith("name:")
    meta: dict[str, str] = {}
    for line in second.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    assert meta["name"] == "moss"
    assert DESCRIPTION_MIN <= len(meta["description"]) <= DESCRIPTION_MAX
    body = rest[0]
    required = ["## When to use", "## Pieces", "## Judging the result", "## Pitfalls"]
    positions = [body.index(heading) for heading in required]
    assert positions == sorted(positions)
    assert "moss.sfx" in body
    for name in ("description", "seconds", "name", "target-lufs"):
        assert name in body, name
