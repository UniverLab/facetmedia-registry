"""The acestep pull/start/run/stop cycle, with no facetmedia import and no GPU.

The test stands in for the core where it can: it clones the manifest's repo
through a scratch git remote (``git url.<base>.insteadOf``), builds the
checkout at ``<home>/servers/acestep/<version>/<rev[:12]>`` with its
``acestep/api_server.py`` and a stub ``uvicorn`` package, substitutes the free
port into the manifest's own launch argv and starts that argv, then runs the
package's runner as a subprocess against a stub ``facet_runner_sdk`` and a
stub ``facet_lib.audiopreview`` on ``PYTHONPATH``. The stub ACE-Step answers
``/health``, ``/release_task``, ``/query_result`` and ``/v1/audio`` with a
canned 30 s WAV and records every posted body, so the test can prove the
instrumental request, the status poll and the downloaded file.

The refusal test needs no server: the caption is rejected before any request.
The doctor test sees a canned ``nvidia-smi`` and the checkout's checkpoints.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "acestep"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
SERVER = MANIFEST["engine"]["server"]
PREVIEW_SCHEMA: dict[str, Any] = json.loads(
    (ROOT / "schemas" / "preview" / "audio.schema.json").read_text(encoding="utf-8")
)

CAPTION = (
    "Lively Baroque chamber orchestra, bright strings and harpsichord, "
    "acoustic instruments only. No drums, no percussion, no bass beat, "
    "no synthesizers."
)
NAME = "cama-clasica"
DURATION = 30.0
RATE_HZ = 16000
TARGET_LUFS = -16.0
DURATION_TOLERANCE_S = 1.0
PEAK_DBFS_MIN = -40.0
#: The waveform bins the audio preview schema fixes.
WAVEFORM_BINS = 1200
#: The caption that asks for the sung music the lab discarded forever.
VOICE_CAPTION = "A warm female singer ballad with piano and soft strings."
PULL_FIX = "facet pull acestep"
START_TIMEOUT_S = 15.0
OK = 200

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

#: The checkout's api_server: the stub uvicorn only proves it imports ``app``.
STUB_API_SERVER = '"""Stub ACE-Step API app."""\n\napp = object()\n'

#: The checkout's stub uvicorn: the endpoints the runner uses, one 30 s WAV.
STUB_UVICORN = """
import json
import math
import os
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import acestep.api_server

LOG = Path(os.environ["STUB_LOG"])
WAV = Path(os.environ["STUB_WAV"])
SECONDS = int(os.environ.get("STUB_SECONDS", "30"))
RATE = int(os.environ.get("STUB_RATE", "16000"))
TASK_ID = "stub-task"


def _write_wav():
    if WAV.exists():
        return
    one = bytearray()
    for index in range(RATE):
        value = int(0.4 * math.sin(2 * math.pi * 220 * index / RATE) * 32767)
        one += value.to_bytes(2, "little", signed=True)
    with wave.open(str(WAV), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        writer.writeframes(bytes(one) * SECONDS)


def _append(body):
    with open(LOG, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(body) + "\\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return None

    def send_body(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/v1/audio"):
            self.send_body(WAV.read_bytes(), "audio/wav")
            return
        if self.path == "/health":
            self.send_body(b'{"data": {"status": "ok"}}', "application/json")
            return
        self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        _append(json.loads(self.rfile.read(length).decode()))
        if self.path == "/release_task":
            answer = {"data": {"task_id": TASK_ID, "status": "queued"}}
            self.send_body(json.dumps(answer).encode(), "application/json")
            return
        result = json.dumps([{"file": "/v1/audio?path=stub.wav", "status": 1}])
        answer = {"data": [{"task_id": TASK_ID, "status": 1, "result": result}]}
        self.send_body(json.dumps(answer).encode(), "application/json")


def main():
    LOG.touch()
    _write_wav()
    assert acestep.api_server.app is not None
    argv = sys.argv[1:]
    port = 8189
    for flag, value in zip(argv, argv[1:]):
        if flag == "--port":
            port = int(value)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
"""

#: A stub facet_lib.audiopreview: the measurement the runner leans on, stdlib
#: plus numpy, so the cycle needs neither soundfile nor pyloudnorm installed.
STUB_AUDIO = """
import math
import wave

import numpy


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

#: The two imports the doctor proves that the test environment lacks.
STUB_DIST = '"""Stub distribution the package environment provides."""\n\n__version__ = "0.0.0"\n'

#: A canned nvidia-smi: one GPU, one VRAM row, no compute apps.
FAKE_GPU_LINE = "GPU 00000000:01:00.0 NVIDIA GeForce RTX 3050"
FAKE_GPU_MEMORY = "8192 MiB, 7854 MiB"
FAKE_NVIDIA_SMI = """#!/bin/sh
case "$*" in
  *"-L"*) printf '%s\\n' "$FAKE_GPU_LINE" ;;
  *"memory.total"*) printf '%s\\n' "$FAKE_GPU_MEMORY" ;;
  *"query-compute-apps"*) printf '' ;;
esac
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env)


def _checkout_path(home: Path) -> Path:
    return home / "servers" / "acestep" / MANIFEST["version"] / SERVER["rev"][:12]


def _clone(tmp_path: Path) -> Path:
    """The checkout at the path the runner derives, fetched through a scratch remote."""
    home = tmp_path / "home"
    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / "requirements.txt").write_text("", encoding="utf-8")
    (remote / "acestep").mkdir()
    (remote / "acestep" / "__init__.py").write_text("", encoding="utf-8")
    (remote / "acestep" / "api_server.py").write_text(STUB_API_SERVER, encoding="utf-8")
    (remote / "uvicorn").mkdir()
    (remote / "uvicorn" / "__init__.py").write_text("", encoding="utf-8")
    (remote / "uvicorn" / "__main__.py").write_text(STUB_UVICORN, encoding="utf-8")
    for folder in ("acestep-v15-turbo", "vae"):
        place = remote / "checkpoints" / folder
        place.mkdir(parents=True)
        (place / "placeholder.bin").write_text(folder, encoding="utf-8")
    _git(remote, "init", "--quiet")
    _git(remote, "add", ".")
    _git(
        remote,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--quiet",
        "-m",
        "stub",
    )
    checkout = _checkout_path(home)
    checkout.mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.file://{remote}.insteadOf",
        "GIT_CONFIG_VALUE_0": SERVER["repo"],
    }
    _git(checkout, "init", "--quiet", env=env)
    _git(checkout, "remote", "add", "origin", SERVER["repo"], env=env)
    _git(checkout, "fetch", "--quiet", "--depth", "1", "origin", "HEAD", env=env)
    _git(checkout, "checkout", "--quiet", "--detach", "FETCH_HEAD", env=env)
    return checkout


def _stub_dir(tmp_path: Path) -> Path:
    """The PYTHONPATH stub: SDK, facet_lib.audiopreview and the two dist stubs."""
    folder = tmp_path / "stub"
    folder.mkdir()
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    (folder / "pyloudnorm.py").write_text(STUB_DIST, encoding="utf-8")
    (folder / "soundfile.py").write_text(STUB_DIST, encoding="utf-8")
    facet_lib = folder / "facet_lib"
    facet_lib.mkdir()
    (facet_lib / "__init__.py").write_text("", encoding="utf-8")
    (facet_lib / "audiopreview.py").write_text(STUB_AUDIO, encoding="utf-8")
    return folder


def _launch(checkout: Path, port: int, log: Path, wav: Path) -> subprocess.Popen[str]:
    """Start the manifest's own launch argv with the free port substituted."""
    venv_bin = checkout / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    python = venv_bin / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    argv = [token.replace("{{port}}", str(port)) for token in SERVER["launch"]]
    env = {
        **os.environ,
        "PATH": str(venv_bin) + os.pathsep + os.environ["PATH"],
        "STUB_LOG": str(log),
        "STUB_WAV": str(wav),
        "STUB_SECONDS": str(int(DURATION)),
    }
    return subprocess.Popen(
        argv,
        cwd=checkout,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_healthy(url: str, timeout_s: float = START_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1) as response:
                if response.status == OK:
                    return True
        except OSError:
            time.sleep(0.05)
    return False


def _request(
    verb: str,
    out: Path,
    piece: Path,
    inputs: dict[str, object],
    assets: tuple[Path, ...] = (),
) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "acestep.bed",
        "inputs": dict(inputs),
        "out_dir": str(out),
        "piece_dir": str(piece),
        "models": {},
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
        timeout=180,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(result_path.read_text(encoding="utf-8")), done.stdout


def _environment(stub_dir: Path, home: Path, url: str) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "FACET_MODELS": str(home / "models" / "direct"),
        "FACET_SERVER_URL": url,
    }


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


def _run_cycle(tmp_path: Path) -> tuple[dict[str, Any], str, Path, Path]:
    """One run against the stub server: result, stdout, post log, output dir."""
    stub_dir = _stub_dir(tmp_path)
    checkout = _clone(tmp_path)
    home = tmp_path / "home"
    log = tmp_path / "posts.jsonl"
    wav = tmp_path / "stub.wav"
    out = tmp_path / "out"
    out.mkdir()
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    process = _launch(checkout, port, log, wav)
    try:
        assert _wait_healthy(url), "the stub ACE-Step never became healthy"
        inputs = {"caption": CAPTION, "name": NAME, "duration": DURATION}
        request = _request("run", out, tmp_path, inputs)
        result, printed = _call(
            stub_dir, "run", request, tmp_path, _environment(stub_dir, home, url)
        )
    finally:
        process.terminate()
        process.wait(timeout=10)
    return result, printed, log, out


def test_the_cycle_composes_normalises_and_records(tmp_path: Path) -> None:
    result, printed, log, out = _run_cycle(tmp_path)
    asset = result["assets"][0]
    assert asset["file"] == f"{NAME}.wav"
    assert (asset["kind"], asset["mime"]) == ("audio", "audio/wav")
    assert asset["params"] == {"caption": CAPTION, "name": NAME, "duration": DURATION}
    properties = asset["properties"]
    assert properties["sample_rate_hz"] == RATE_HZ
    assert abs(properties["duration_s"] - DURATION) <= DURATION_TOLERANCE_S
    assert properties["peak_dbfs"] <= -1.0
    assert properties["peak_dbfs"] > PEAK_DBFS_MIN
    assert properties["lufs"] == TARGET_LUFS
    assert (out / f"{NAME}.wav").is_file()
    assert f"{NAME}.wav ok" in printed
    assert result["tool"]["name"] == "ACE-Step 1.5"

    posts = _read_lines(log)
    release = [post for post in posts if "prompt" in post]
    assert len(release) == 1
    body = release[0]
    assert body["prompt"] == CAPTION
    assert body["lyrics"] == "[Instrumental]"
    assert body["audio_duration"] == DURATION
    assert body["audio_format"] == "wav"
    assert body["model"] == "acestep-v15-turbo"
    assert body["task_type"] == "text2music"
    assert body["thinking"] is False
    queries = [post for post in posts if "task_id_list" in post]
    assert queries and queries[0]["task_id_list"] == ["stub-task"]


def test_verify_and_preview_read_the_written_bed(tmp_path: Path) -> None:
    result, _printed, _log, out = _run_cycle(tmp_path)
    stub_dir = tmp_path / "stub"
    home = tmp_path / "home"
    env = _environment(stub_dir, home, "http://127.0.0.1:1")
    inputs = {"caption": CAPTION, "name": NAME, "duration": DURATION}
    clip = out / f"{NAME}.wav"

    verdict, _ = _call(
        stub_dir,
        "verify",
        _request("verify", out, tmp_path, inputs, (clip,)),
        tmp_path,
        env,
    )
    passed = verdict["assets"][0]
    assert passed["passed"] is True
    assert passed["thresholds"] == {
        "duration_tolerance_s": DURATION_TOLERANCE_S,
        "peak_dbfs_min": PEAK_DBFS_MIN,
    }
    assert passed["verifier"] == "audiopreview"

    wrong, _ = _call(
        stub_dir,
        "verify",
        _request("verify", out, tmp_path, {**inputs, "duration": 5.0}, (clip,)),
        tmp_path,
        env,
    )
    assert wrong["assets"][0]["passed"] is False

    _call(
        stub_dir,
        "preview",
        _request("preview", out, tmp_path, inputs, (clip,)),
        tmp_path,
        env,
    )
    data = json.loads((out / f"{NAME}.wav.preview.json").read_text(encoding="utf-8"))
    assert _missing_required(data, PREVIEW_SCHEMA) == []
    assert set(data) == set(PREVIEW_SCHEMA["required"])
    assert data["kind"] == "audio"
    assert data["loudness"]["target_lufs"] == TARGET_LUFS
    assert len(data["waveform"]["max"]) == WAVEFORM_BINS
    assert result["assets"][0]["properties"]["sample_rate_hz"] == RATE_HZ


def test_a_voice_caption_is_refused_before_the_server(tmp_path: Path) -> None:
    """The sung-music verdict: exit 1 naming the word, and no /release_task."""
    stub_dir = _stub_dir(tmp_path)
    checkout = _clone(tmp_path)
    home = tmp_path / "home"
    log = tmp_path / "posts.jsonl"
    out = tmp_path / "out"
    out.mkdir()
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    process = _launch(checkout, port, log, tmp_path / "stub.wav")
    try:
        assert _wait_healthy(url), "the stub ACE-Step never became healthy"
        request = _request(
            "run",
            out,
            tmp_path,
            {"caption": VOICE_CAPTION, "name": NAME, "duration": DURATION},
        )
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
            env=_environment(stub_dir, home, url),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        output = done.stdout + done.stderr
        assert done.returncode != 0
        assert "singer" in output
        assert "always instrumental" in output
        assert not result_path.exists()
        assert _read_lines(log) == []
        assert not (out / f"{NAME}.wav").exists()
    finally:
        process.terminate()
        process.wait(timeout=10)


def _doctor(tmp_path: Path, stub_dir: Path, home: Path) -> dict[str, Any]:
    """The doctor verb on a canned nvidia-smi, the checkout and its checkpoints."""
    machine = tmp_path / "fake-path"
    machine.mkdir(exist_ok=True)
    (machine / "nvidia-smi").write_text(FAKE_NVIDIA_SMI, encoding="utf-8")
    os.chmod(machine / "nvidia-smi", 0o755)
    out = tmp_path / "doctor-out"
    out.mkdir(exist_ok=True)
    request = {
        "protocol": 1,
        "verb": "doctor",
        "capability": "acestep.bed",
        "depth": "quick",
        "inputs": {},
        "out_dir": str(out),
        "piece_dir": str(tmp_path),
        "models": {},
        "assets": [],
    }
    input_path = tmp_path / "doctor-request.json"
    result_path = tmp_path / "doctor-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "FACET_MODELS": str(home / "models" / "direct"),
        "FAKE_GPU_LINE": FAKE_GPU_LINE,
        "FAKE_GPU_MEMORY": FAKE_GPU_MEMORY,
        "PATH": str(machine) + os.pathsep + os.environ["PATH"],
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


def test_the_doctor_separates_the_machine_and_the_checkpoints(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    checkout = _clone(tmp_path)
    home = tmp_path / "home"
    result = _doctor(tmp_path, stub_dir, home)
    checks = {check["name"]: check for check in result["checks"]}
    assert set(checks) == {"gpu", "vram", "gpu_free", "imports", "checkout", "models"}
    assert checks["gpu"]["ok"] is True
    assert checks["gpu"]["detail"] == FAKE_GPU_LINE
    assert checks["vram"]["ok"] is True
    assert checks["vram"]["detail"] == FAKE_GPU_MEMORY
    assert checks["gpu_free"]["ok"] is True
    assert checks["imports"]["ok"] is True
    assert checks["checkout"]["ok"] is True
    assert checks["models"]["ok"] is True

    shutil.rmtree(checkout / "checkpoints" / "acestep-v15-turbo")
    broken = _doctor(tmp_path, stub_dir, home)
    models = {check["name"]: check for check in broken["checks"]}["models"]
    assert models["ok"] is True
    assert models["fix"] == ""
    assert "acestep-v15-turbo" in models["detail"]

    shutil.rmtree(checkout / "checkpoints" / "vae")
    gone = _doctor(tmp_path, stub_dir, home)
    gone_models = {check["name"]: check for check in gone["checks"]}["models"]
    assert gone_models["ok"] is True
    assert gone_models["fix"] == ""
    assert "acestep-v15-turbo" in gone_models["detail"]
    assert "acestep-vae" in gone_models["detail"]
