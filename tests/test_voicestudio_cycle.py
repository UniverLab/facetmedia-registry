"""The voicestudio run cycle against a stub backend, with no real engine.

The runner is a subprocess with a stub ``facet_runner_sdk`` on
``PYTHONPATH`` (the pull-time surface the real one copies in) plus stub
``faster_whisper`` (scripted transcripts, recorded calls) and stub
``facet_lib`` (the registry's ``lib/textnorm.py``, so WER numbers fold
exactly like the pull-time copy). The stub backend answers
``GET /model/status`` with a scripted state sequence and
``POST /v1/audio/speech`` with a canned WAV, recording every request body
and every status poll. No real backend, no GPU, no model download: the
whisper "model" is a placeholder file the stub never reads.

The readiness wait, the doctor's profile rule and the preview file are
driven in-process over the same stub (the stub SDK's ``main()`` stands
down), so a grace window and a schema contract are asserted without a
30 s sleep or a real model.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "voicestudio"
#: The preview contract the runner's file must satisfy (a review blocker).
PREVIEW_SCHEMA: dict[str, Any] = json.loads(
    (ROOT / "schemas" / "preview" / "audio.schema.json").read_text(encoding="utf-8")
)

#: The clip the pieces narrate: a number Whisper writes as digits and a word
#: with tildes, so a transcript equal to the text still proves the fold.
TEXT = "En 2026 revisamos la hipótesis con cuidado."
BAD_HEARD = "otra cosa completamente distinta sin sentido ninguno"
#: The load failure the backend reports in ``error`` while ``status`` stays idle.
BACKEND_ERROR = "omnivoice package missing: cannot import name 'PreTrainedModel'"
SEED = 7
RETRY_SEED = SEED + 1
REGEN_ATTEMPTS = 2
#: The runner's cap on attempts per clip, and the threshold it judges by.
MAX_TRIES = 3
WER_MAX = 0.05
#: Polls a grace of 0.3 s at 0.05 s intervals must see before proceeding.
MIN_GRACE_POLLS = 2
#: The canned clip the stub backend renders, and what it means.
RATE_HZ = 24_000
CLIP_FRAMES = RATE_HZ
DURATION_S = 1.0
#: Reachability probe budget for the stub backend start.
START_TIMEOUT_S = 10
#: The byte size the manifest pins for the embedded transcriber.
WHISPER_BYTES = 486_212_372

#: The pull-time SDK surface the runner touches; the real one is copied in.
STUB_SDK = """
import json
import os
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
        if os.environ.get("STUB_SDK_NO_MAIN"):
            return 0  # the test imported the runner in-process, not as a script
        raise SystemExit(self.run(sys.argv[1:]))
"""

#: A stub faster-whisper: each load and each transcribe is recorded, and the
#: transcripts come from STUB_HEARD in call order.
STUB_WHISPER = """
import json
import os

CALLS = os.environ["STUB_CALLS"]
HEARD = list(json.loads(os.environ["STUB_HEARD"]))


def _record(item):
    with open(CALLS, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(item) + "\\n")


class _Segment:
    def __init__(self, text):
        self.text = text


class WhisperModel:
    def __init__(self, path, device="cpu", compute_type="int8"):
        _record({"call": "load", "path": path, "device": device, "compute_type": compute_type})

    def transcribe(self, path, language=None, beam_size=None, vad_filter=False):
        _record({"call": "transcribe", "path": path, "language": language,
                 "beam_size": beam_size, "vad_filter": vad_filter})
        return [_Segment(HEARD.pop(0))], {"language": language}
"""

#: The stub backend: scripted /model/status states, recorded synthesis bodies,
#: one canned WAV for every /v1/audio/speech.
STUB_BACKEND = """
import argparse
import json
import os
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATES = list(json.loads(os.environ["STUB_STATES"]))
PROFILES = list(json.loads(os.environ.get("STUB_PROFILES", "[]")))
POLLS = os.environ["STUB_POLLS"]
BODIES = os.environ["STUB_BODIES"]
GETS = os.environ["STUB_GETS"]
INSTALLS = os.environ["STUB_INSTALLS"]
CANNED = os.environ["STUB_CANNED"]
ERROR = os.environ.get("STUB_ERROR", "")
INSTALL_STATUSES = list(json.loads(os.environ.get("STUB_INSTALL_STATUSES", "[]")))
INSTALL_POST = os.environ.get("STUB_INSTALL_POST", "ok")
INSTALL_DETAIL = os.environ.get("STUB_INSTALL_DETAIL", "this host cannot serve it")


def _append(path, item):
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(item) + "\\n")


def _canned_wav():
    if not os.path.exists(CANNED):
        with wave.open(CANNED, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(24000)
            writer.writeframes(b"\\x00\\x00" * 24000)  # 1 s of silence
    with open(CANNED, "rb") as stream:
        return stream.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return None

    def send_body(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_code(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def engine_status(self):
        prior = sum(1 for line in open(GETS, encoding="utf-8") if "/install/status" in line)
        _append(GETS, {"path": self.path})
        if INSTALL_STATUSES:
            return INSTALL_STATUSES[min(prior, len(INSTALL_STATUSES) - 1)]
        engine = self.path.split("/")[3]
        return {
            "engine_id": engine,
            "installed": True,
            "managed": True,
            "install_dir": f"/data/voicestudio/engines/{engine}",
            "job": {"state": "succeeded", "steps": []},
        }

    def do_GET(self):
        if self.path == "/profiles":
            _append(GETS, {"path": self.path})
            self.send_body(json.dumps({"profiles": PROFILES}).encode(), "application/json")
            return
        if self.path.startswith("/engines/sidecar/") and self.path.endswith("/install/status"):
            self.send_body(json.dumps(self.engine_status()).encode(), "application/json")
            return
        if self.path != "/model/status":
            self.send_error(404)
            return
        index = sum(1 for _ in open(POLLS, encoding="utf-8"))
        state = STATES[min(index, len(STATES) - 1)]
        _append(POLLS, state)
        payload = {"status": state, "loaded": state == "ready", "loading": state == "loading"}
        if ERROR:
            payload["error"] = ERROR
        self.send_body(json.dumps(payload).encode(), "application/json")

    def do_POST(self):
        if self.path.startswith("/engines/sidecar/") and self.path.endswith("/install"):
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            _append(INSTALLS, {"path": self.path})
            if INSTALL_POST == "409":
                self.send_code(409, {"detail": INSTALL_DETAIL})
                return
            self.send_body(json.dumps({}).encode(), "application/json")
            return
        if self.path != "/v1/audio/speech":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        _append(BODIES, json.loads(self.rfile.read(length).decode()))
        self.send_body(_canned_wav(), "audio/wav")


def main():
    for path in (POLLS, BODIES, GETS, INSTALLS):
        open(path, "a", encoding="utf-8").close()  # the handlers read these before the first append
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3900)
    args = parser.parse_args()
    ThreadingHTTPServer((args.listen, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
"""


def _load_textnorm():
    """The registry's own textnorm, the same copy the stub facet_lib serves."""
    spec = importlib.util.spec_from_file_location("cycle_textnorm", ROOT / "lib" / "textnorm.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _import_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """The runner module in-process, over the stub SDK (whose main() is a no-op).

    The wait for readiness and the preview file are cheaper to drive here than
    through a subprocess; everything else runs the runner as facet does.
    """
    stub_dir = _stub_dir(tmp_path)
    monkeypatch.setenv("STUB_SDK_NO_MAIN", "1")
    monkeypatch.syspath_prepend(str(stub_dir))
    spec = importlib.util.spec_from_file_location(
        "voicestudio_runner_inproc", PACKAGE / "runner.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_audio() -> Any:
    """The facet_lib.audiopreview surface the preview reads, on one silent second."""

    def read_wav(_path: Path) -> tuple[Any, int]:
        return numpy.zeros(RATE_HZ, dtype=numpy.float32), RATE_HZ

    def duration_s(samples: Any, rate: int) -> float:
        return len(samples) / rate

    def waveform(_samples: Any) -> dict[str, Any]:
        return {"bins": 1200, "min": [0.0] * 1200, "max": [0.0] * 1200}

    return SimpleNamespace(
        read_wav=read_wav,
        duration_s=duration_s,
        waveform=waveform,
        integrated_lufs=lambda _samples, _rate: -70.0,
        peak_dbfs=lambda _samples: -120.0,
        momentary=lambda _samples, _rate: [None],
        silences=lambda _samples, _rate: [],
        clipped_samples=lambda _samples: 0,
    )


def _fake_whisper() -> Any:
    """A transcriber that hears exactly the piece's text back."""

    def transcribe(_path: str, language: str, beam_size: int, vad_filter: bool) -> tuple[Any, Any]:
        return [SimpleNamespace(text=TEXT)], {"language": language}

    return SimpleNamespace(transcribe=transcribe)


def _missing_required(data: object, schema: dict[str, Any], prefix: str = "") -> list[str]:
    """Every key a schema's ``required`` lists, missing from ``data``."""
    if not isinstance(data, dict):
        return [prefix or "<root>"]
    missing = [f"{prefix}{key}" for key in schema.get("required", []) if key not in data]
    for key, child in schema.get("properties", {}).items():
        if key in data and isinstance(child, dict) and "properties" in child:
            missing += _missing_required(data[key], child, f"{prefix}{key}.")
    return missing


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _stub_dir(tmp_path: Path) -> Path:
    """The PYTHONPATH stub: SDK, whisper, and the facet_lib name with textnorm."""
    folder = tmp_path / "stub"
    folder.mkdir()
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    (folder / "faster_whisper.py").write_text(STUB_WHISPER, encoding="utf-8")
    facet_lib = folder / "facet_lib"
    facet_lib.mkdir()
    (facet_lib / "__init__.py").write_text("", encoding="utf-8")
    (facet_lib / "textnorm.py").write_text(
        (ROOT / "lib" / "textnorm.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return folder


def _backend(
    tmp_path: Path,
    states: list[str],
    error: str = "",
    profiles: list[dict[str, str]] | None = None,
    install_statuses: list[dict[str, object]] | None = None,
    install_post: str = "ok",
) -> tuple[subprocess.Popen[str], str, dict[str, Path]]:
    port = _free_port()
    logs = tmp_path / "stub-logs"
    logs.mkdir()
    files = {
        "pol": logs / "polls.jsonl",
        "bod": logs / "bodies.jsonl",
        "get": logs / "gets.jsonl",
        "ins": logs / "installs.jsonl",
        "can": logs / "clip.wav",
    }
    server = tmp_path / "stub-backend.py"
    server.write_text(STUB_BACKEND, encoding="utf-8")
    env = {
        **os.environ,
        "STUB_STATES": json.dumps(states),
        "STUB_POLLS": str(files["pol"]),
        "STUB_BODIES": str(files["bod"]),
        "STUB_GETS": str(files["get"]),
        "STUB_INSTALLS": str(files["ins"]),
        "STUB_CANNED": str(files["can"]),
        "STUB_CALLS": str(tmp_path / "whisper-calls.jsonl"),
        "STUB_ERROR": error,
        "STUB_PROFILES": json.dumps(profiles or []),
        "STUB_INSTALL_STATUSES": json.dumps(install_statuses or []),
        "STUB_INSTALL_POST": install_post,
    }
    process = subprocess.Popen(
        [sys.executable, str(server), "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{port}"
    started = time.monotonic()
    while time.monotonic() - started < START_TIMEOUT_S:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break  # TCP reachability only: /model/status polls belong to the runner
        except OSError:
            time.sleep(0.05)
    else:
        process.terminate()
        raise AssertionError(f"the stub backend never listened on {url}")
    return process, url, files


def _request(
    out_dir: Path, models: dict[str, Path], inputs: dict[str, object], capability: str
) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": "run",
        "capability": capability,
        "inputs": inputs,
        "out_dir": str(out_dir),
        "piece_dir": str(out_dir),
        "models": {key: str(value) for key, value in models.items()},
        "assets": [],
    }


def _piece_request(
    tmp_path: Path,
    model: str = "voxcpm2",
    capability: str = "voicestudio.speak",
    voice: str = "narradora",
) -> Path:
    """Write the run request for one clip; the path of its result file."""
    out = tmp_path / "out"
    out.mkdir()
    piece = tmp_path / "piece"
    piece.mkdir()
    models = {"faster-whisper-small-verify": piece / "faster-whisper-small"}
    models["faster-whisper-small-verify"].mkdir()
    inputs = {
        "voice": voice,
        "model": model,
        "language": "es",
        "clip": [{"name": "intro", "text": TEXT, "seed": SEED}],
    }
    request = _request(out, models, inputs, capability)
    (tmp_path / "run-request.json").write_text(json.dumps(request), encoding="utf-8")
    return tmp_path / "run-result.json"


@dataclass(frozen=True)
class _Piece:
    """The piece-level values of one run request."""

    model: str = "voxcpm2"
    capability: str = "voicestudio.speak"
    voice: str = "narradora"
    profiles: list[dict[str, str]] | None = None


def _run_piece(
    tmp_path: Path,
    states: list[str],
    heard: list[str],
    error: str = "",
    piece: _Piece | None = None,
) -> subprocess.CompletedProcess[str]:
    """One `run` verb as a subprocess against the stub backend."""
    piece = piece or _Piece()
    result_path = _piece_request(tmp_path, piece.model, piece.capability, piece.voice)
    stub_dir = _stub_dir(tmp_path)
    calls = tmp_path / "whisper-calls.jsonl"
    calls.touch()
    process, url, _files = _backend(tmp_path, states, error, piece.profiles)
    try:
        env = {
            **os.environ,
            "PYTHONPATH": str(stub_dir),
            "FACET_SERVER_URL": url,
            "STUB_CALLS": str(calls),
            "STUB_HEARD": json.dumps(heard),
        }
        return subprocess.run(
            [
                sys.executable,
                str(PACKAGE / "runner.py"),
                "run",
                "--input",
                str(tmp_path / "run-request.json"),
                "--result",
                str(result_path),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        process.terminate()
        process.wait(timeout=10)


def _run_cycle(
    tmp_path: Path,
    states: list[str],
    heard: list[str],
    model: str = "voxcpm2",
    capability: str = "voicestudio.speak",
    voice: str = "narradora",
    profiles: list[dict[str, str]] | None = None,
) -> tuple[dict[str, object], str]:
    done = _run_piece(
        tmp_path,
        states,
        heard,
        piece=_Piece(model=model, capability=capability, voice=voice, profiles=profiles),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return _result(tmp_path / "run-result.json"), done.stdout


def _result(result_path: Path) -> dict[str, object]:
    return json.loads(result_path.read_text(encoding="utf-8"))


def _read_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_a_failing_clip_prints_regenerate_and_retries_with_seed_plus_one(
    tmp_path: Path,
) -> None:
    """Bad hearing first, then the exact clip: REGENERATE, seed 7 -> 8, keep last."""
    result, stdout = _run_cycle(tmp_path, ["loading", "ready"], [BAD_HEARD, TEXT])
    assets = result["assets"]
    assert len(assets) == 1
    asset = assets[0]
    assert asset["seed"] == RETRY_SEED
    assert asset["file"] == "intro.wav"
    assert asset["inputs"] == []
    properties = asset["properties"]
    assert properties["attempts"] == REGEN_ATTEMPTS
    assert properties["model"] == "voxcpm2"
    assert properties["voice"] == "narradora"
    assert properties["language"] == "es"
    assert properties["wer"] == 0.0
    assert "REGENERATE intro" in stdout


def test_a_clip_that_never_passes_keeps_the_last_attempt(tmp_path: Path) -> None:
    """Three bad hearings: seeds 7, 8, 9; the last clip is kept and reported."""
    result, stdout = _run_cycle(tmp_path, ["ready"], [BAD_HEARD] * MAX_TRIES)
    asset = result["assets"][0]
    assert asset["properties"]["attempts"] == MAX_TRIES
    assert asset["seed"] == SEED + MAX_TRIES - 1
    assert asset["properties"]["wer"] > WER_MAX
    assert "still wer" in stdout
    bodies = _read_lines(tmp_path / "stub-logs" / "bodies.jsonl")
    assert [body["seed"] for body in bodies] == [SEED, SEED + 1, SEED + 2]

    verify_request = json.loads((tmp_path / "run-request.json").read_text(encoding="utf-8"))
    verify_request["verb"] = "verify"
    verify_request["assets"] = [str(tmp_path / "out" / "intro.wav")]
    verify_request_path = tmp_path / "verify-request.json"
    verify_request_path.write_text(json.dumps(verify_request), encoding="utf-8")
    verify_result_path = tmp_path / "verify-result.json"
    verify_done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            "verify",
            "--input",
            str(verify_request_path),
            "--result",
            str(verify_result_path),
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(tmp_path / "stub"),
            "STUB_CALLS": str(tmp_path / "whisper-calls.jsonl"),
            "STUB_HEARD": json.dumps([BAD_HEARD]),
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert verify_done.returncode == 0, verify_done.stdout + verify_done.stderr
    verdicts = _result(verify_result_path)["assets"]
    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict["file"] == "intro.wav"
    assert verdict["passed"] is False
    assert verdict["metrics"]["wer"] > WER_MAX
    assert verdict["metrics"]["wer"] == asset["properties"]["wer"]
    assert verdict["thresholds"] == {"wer_max": WER_MAX}


def test_the_stub_saw_the_piece_engine_voice_and_both_seeds(tmp_path: Path) -> None:
    """Every synthesis carries model voxcpm2, voice narradora and the studied seeds."""
    _run_cycle(tmp_path, ["ready", "ready"], [BAD_HEARD, TEXT])
    bodies = _read_lines(tmp_path / "stub-logs" / "bodies.jsonl")
    assert [body["seed"] for body in bodies] == [SEED, SEED + 1]
    for body in bodies:
        assert body["model"] == "voxcpm2"
        assert body["voice"] == "narradora"
        assert body["language"] == "es"
        assert body["input"] == TEXT
        assert body["response_format"] == "wav"


def test_an_omnivoice_piece_reaches_the_omnivoice_backend_voice(tmp_path: Path) -> None:
    """The approved narrator engine: model omnivoice on the narradora profile."""
    result, _stdout = _run_cycle(tmp_path, ["ready"], [TEXT], model="omnivoice")
    asset = result["assets"][0]
    assert asset["properties"]["model"] == "omnivoice"
    assert asset["properties"]["voice"] == "narradora"
    assert asset["params"]["model"] == "omnivoice"
    assert asset["seed"] == SEED
    assert asset["file"] == "intro.wav"
    bodies = _read_lines(tmp_path / "stub-logs" / "bodies.jsonl")
    assert len(bodies) == 1
    assert bodies[0]["model"] == "omnivoice"
    assert bodies[0]["voice"] == "narradora"


def test_an_omnivoice_piece_waits_for_model_status_ready_before_speaking(
    tmp_path: Path,
) -> None:
    """The engine imports in the background and races /health: status is the gate."""
    _run_cycle(tmp_path, ["idle", "loading", "ready"], [TEXT], model="omnivoice")
    polls = [str(state) for state in _read_lines(tmp_path / "stub-logs" / "polls.jsonl")]
    assert polls == ["idle", "loading", "ready"]


#: The person's own clone, installed only on their machine.
CLONE_ID = "d4e9ee57"
CLONE_PROFILES = [{"id": CLONE_ID, "name": "jheison", "kind": "clone"}]


def test_a_clone_piece_speaks_the_local_profile_with_cosyvoice(tmp_path: Path) -> None:
    """`voicestudio.clone` picks the installed profile and the cosyvoice engine."""
    result, _stdout = _run_cycle(
        tmp_path,
        ["ready"],
        [TEXT],
        model="cosyvoice",
        capability="voicestudio.clone",
        voice=CLONE_ID,
        profiles=CLONE_PROFILES,
    )
    asset = result["assets"][0]
    assert asset["properties"]["model"] == "cosyvoice"
    assert asset["properties"]["voice"] == CLONE_ID
    assert asset["params"]["model"] == "cosyvoice"
    assert asset["params"]["voice"] == CLONE_ID
    gets = _read_lines(tmp_path / "stub-logs" / "gets.jsonl")
    paths = [entry["path"] for entry in gets]
    assert "/profiles" in paths
    assert "/engines/sidecar/cosyvoice/install/status" in paths
    installs = _read_lines(tmp_path / "stub-logs" / "installs.jsonl")
    assert installs == []  # already installed: status first, never a POST
    bodies = _read_lines(tmp_path / "stub-logs" / "bodies.jsonl")
    assert len(bodies) == 1
    assert bodies[0]["model"] == "cosyvoice"
    assert bodies[0]["voice"] == CLONE_ID
    assert bodies[0]["input"] == TEXT


def test_a_clone_profile_not_installed_is_refused_naming_the_spec(tmp_path: Path) -> None:
    """A profile id absent from the local backend never reaches synthesis."""
    done = _run_piece(
        tmp_path,
        ["ready"],
        [],
        piece=_Piece(model="cosyvoice", capability="voicestudio.clone", voice=CLONE_ID),
    )
    output = done.stdout + done.stderr
    assert done.returncode != 0
    assert CLONE_ID in output
    assert "is not installed in this backend" in output
    assert "facet run voicestudio.profile" in output
    gets = _read_lines(tmp_path / "stub-logs" / "gets.jsonl")
    assert [entry["path"] for entry in gets] == ["/profiles"]
    assert _read_lines(tmp_path / "stub-logs" / "bodies.jsonl") == []


def test_a_broken_profile_listing_is_not_reported_as_a_missing_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable /profiles never sends the person to create a profile."""
    module = _import_runner(monkeypatch, tmp_path)

    def broken(_url: str) -> list[dict[str, str]]:
        raise ValueError("/profiles answered an unexpected body")

    monkeypatch.setattr(module, "_profile_rows", broken)
    with pytest.raises(RuntimeError) as caught:
        module._check_clone_voice("http://127.0.0.1:3900", CLONE_ID)
    assert "GET /profiles failed" in str(caught.value)
    assert "projects/prueba-voz/mi-voz/" not in str(caught.value)


def test_a_two_engine_clone_piece_is_refused_before_speaking(tmp_path: Path) -> None:
    """One engine per piece: a clone piece naming voxcpm2 fails outright.

    The refusal needs no backend: it happens before the readiness wait, so a
    mis-engined piece never spends the idle grace and never lists profiles.
    """
    done = _run_piece(
        tmp_path,
        ["ready"],
        [],
        piece=_Piece(
            model="voxcpm2", capability="voicestudio.clone", voice=CLONE_ID, profiles=CLONE_PROFILES
        ),
    )
    output = done.stdout + done.stderr
    assert done.returncode != 0
    assert "one engine per piece" in output
    logs = tmp_path / "stub-logs"
    assert _read_lines(logs / "polls.jsonl") == []
    assert _read_lines(logs / "gets.jsonl") == []
    assert _read_lines(logs / "bodies.jsonl") == []


def test_the_runner_waited_for_readiness_before_speaking(tmp_path: Path) -> None:
    """Exactly loading then ready: the runner polled until the state said ready."""
    _run_cycle(tmp_path, ["loading", "ready"], [BAD_HEARD, TEXT])
    polls = [str(state) for state in _read_lines(tmp_path / "stub-logs" / "polls.jsonl")]
    assert polls == ["loading", "ready"]


def test_a_transient_idle_is_not_mistaken_for_nothing_preloaded(tmp_path: Path) -> None:
    """A preload that starts right after the backend reports idle, then loads.

    Proceeding on the first idle would speak while the engine is still
    importing (the lab's ``omnivoice package missing`` race), so the runner
    must keep polling through the idle window and return on ``ready``.
    """
    result, stdout = _run_cycle(tmp_path, ["idle", "loading", "ready"], [TEXT])
    asset = result["assets"][0]
    assert asset["seed"] == SEED
    assert asset["properties"]["attempts"] == 1
    assert "REGENERATE" not in stdout
    polls = [str(state) for state in _read_lines(tmp_path / "stub-logs" / "polls.jsonl")]
    assert polls == ["idle", "loading", "ready"]
    bodies = _read_lines(tmp_path / "stub-logs" / "bodies.jsonl")
    assert [body["seed"] for body in bodies] == [SEED]


def test_a_backend_error_field_fails_the_run_naming_it(tmp_path: Path) -> None:
    """The backend reports a load failure in ``error``, not in ``status``."""
    done = _run_piece(tmp_path, ["idle"], [], error=BACKEND_ERROR)
    assert done.returncode != 0, done.stdout + done.stderr
    assert BACKEND_ERROR in done.stdout + done.stderr


def test_a_missing_backend_names_the_start_recipe(tmp_path: Path) -> None:
    """Nothing listening: the failure names the recipe, not a bare traceback."""
    _piece_request(tmp_path)
    stub_dir = _stub_dir(tmp_path)
    dead_url = f"http://127.0.0.1:{_free_port()}"
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "FACET_SERVER_URL": dead_url,
        "STUB_CALLS": str(tmp_path / "whisper-calls.jsonl"),
        "STUB_HEARD": "[]",
    }
    done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            "run",
            "--input",
            str(tmp_path / "run-request.json"),
            "--result",
            str(tmp_path / "run-result.json"),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = done.stdout + done.stderr
    assert done.returncode != 0
    assert f"no VoiceStudio backend at {dead_url}" in output
    assert "facet starts it for each run" in output
    assert "facet doctor voicestudio" in output
    assert "uvicorn main:app --app-dir backend" not in output


def test_the_written_clip_is_a_real_wav_from_the_backend(tmp_path: Path) -> None:
    """The asset file beside the piece is the bytes the stub answered, readable."""
    result, _stdout = _run_cycle(tmp_path, ["ready"], [TEXT])
    clip = tmp_path / "out" / "intro.wav"
    with wave.open(str(clip), "rb") as reader:
        assert reader.getframerate() == RATE_HZ
        assert reader.getnframes() == CLIP_FRAMES
    properties = result["assets"][0]["properties"]
    assert properties["sample_rate_hz"] == RATE_HZ
    assert properties["duration_s"] == DURATION_S
    assert properties["transcript"] == TEXT
    assert result["tool"]["name"] == "VoiceStudio"


def test_the_whisper_verifier_ran_on_cpu_int8(tmp_path: Path) -> None:
    """The embedded transcriber: cpu int8, the pinned model, one transcribe call."""
    _run_cycle(tmp_path, ["ready"], [TEXT])
    calls = _read_lines(tmp_path / "whisper-calls.jsonl")
    loads = [call for call in calls if call["call"] == "load"]
    transcribes = [call for call in calls if call["call"] == "transcribe"]
    assert len(loads) == 1
    assert loads[0]["device"] == "cpu"
    assert loads[0]["compute_type"] == "int8"
    assert str(loads[0]["path"]).endswith("faster-whisper-small")  # the dir under the id suffix
    assert len(transcribes) == 1
    assert transcribes[0]["language"] == "es"
    assert transcribes[0]["vad_filter"] is True


def test_the_declared_piece_model_is_what_reaches_a_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The manifest's ``model`` input is read, not ignored behind a constant.

    The enum holds voxcpm2 alone today; reading the input means adding an
    engine later is a manifest change, never a runner one.
    """
    module = _import_runner(monkeypatch, tmp_path)
    clips = module._clips(
        {
            "model": "voxcpm3",
            "voice": "narradora",
            "clip": [{"name": "a", "text": "hola", "seed": 1}],
        }
    )
    assert clips[0]["model"] == "voxcpm3"
    assert clips[0]["voice"] == "narradora"


def test_numbers_folds_like_the_fold_rule_and_tildes_strip() -> None:
    """numbers: 2026 -> 'dos mil veintiséis'; tildes: 'hipótesis' -> 'hipotesis'."""
    numbers = _load_textnorm()
    assert numbers.spell(2026) == "dos mil veintiseis"
    reference = numbers.words("La hipótesis de 2026 se revisó.", "es")
    heard = numbers.words("la hipotesis de dos mil veintiseis se reviso", "es")
    assert reference == heard
    assert "hipotesis" in reference
    assert numbers.wer(reference, heard) == 0.0
    assert numbers.words("2026", "es") == ["dos", "mil", "veintiseis"]


def test_a_persistently_idle_backend_proceeds_after_the_grace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Nothing preloads for the whole grace: idle is then "nothing to preload"."""
    module = _import_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(module, "READY_IDLE_GRACE_S", 0.3)
    monkeypatch.setattr(module, "READY_POLL_S", 0.05)
    process, url, _files = _backend(tmp_path, ["idle"])
    try:
        detail = module._wait_ready(url)
    finally:
        process.terminate()
        process.wait(timeout=10)
    assert detail.startswith("idle")
    polls = _read_lines(tmp_path / "stub-logs" / "polls.jsonl")
    assert len(polls) >= MIN_GRACE_POLLS  # one poll was not enough: the grace had to elapse


def test_the_doctor_names_the_recipe_when_the_default_profile_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profiles are local and never bundled: the doctor says how to create it."""
    module = _import_runner(monkeypatch, tmp_path)
    profiles = [{"id": "d4e9ee57", "name": "jheison"}]
    monkeypatch.setattr(module, "_fetch_json", lambda *_args, **_kwargs: profiles)
    missing = module._doctor_profile("http://127.0.0.1:3900")
    assert missing["ok"] is False
    assert "facet run voicestudio.profile" in missing["fix"]
    assert 'name = "narradora"' in missing["fix"]
    assert "POST /profiles" not in missing["fix"]
    profiles = [{"id": "whatever-minted-per-data-dir", "name": "narradora"}]
    found = module._doctor_profile("http://127.0.0.1:3900")
    assert found["ok"] is True


def test_the_preview_file_has_what_the_audio_schema_requires(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The preview the runner writes is the kind's contract, not a close cousin."""
    module = _import_runner(monkeypatch, tmp_path)
    clip = {
        "name": "intro",
        "text": TEXT,
        "seed": SEED,
        "voice": "narradora",
        "model": "voxcpm2",
        "language": "es",
    }
    data = module._preview_data(_fake_whisper(), _fake_audio(), tmp_path / "intro.wav", clip)
    assert data["kind"] == "audio"
    assert data["speech"]["wer"] == 0.0
    assert _missing_required(data, PREVIEW_SCHEMA) == []


#: The machine the doctor's machine checks see through the canned nvidia-smi.
FAKE_GPU_LINE = "GPU 00000000:01:00.0 NVIDIA GeForce RTX 3050"
FAKE_GPU_MEMORY = "8192 MiB, 7854 MiB"
#: One compute app the fake nvidia-smi reports as holding GPU memory.
FAKE_COMPUTE_ROW = "4242, python, 5000 MiB"

FAKE_NVIDIA_SMI = """#!/bin/sh
[ "$FAKE_EXIT" = 1 ] && exit 1
case "$*" in
  *"-L"*) printf '%s\\n' "$FAKE_GPU_LINE" ;;
  *"memory.total"*) printf '%s\\n' "$FAKE_GPU_MEMORY" ;;
  *"query-compute-apps"*) printf '%s\\n' "$FAKE_COMPUTE_APPS" ;;
esac
"""


def test_the_doctor_passes_with_the_bytes_less_entry_and_names_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The backend owns omnivoice's weights: no path, no byte check, a line.

    The real manifest holds both entries, so a doctor that read ``bytes`` from
    every entry would raise on the bytes-less one; this asserts the skip and
    that the entry's id is never even asked of the request.
    """
    module = _import_runner(monkeypatch, tmp_path)
    asked: list[str] = []

    class _Request:
        def model_path(self, model_id: str) -> Path:
            asked.append(model_id)
            if model_id == "omnivoice":
                raise KeyError(model_id)  # backend-owned: never mapped to a path
            return tmp_path / model_id

    monkeypatch.setattr(module, "_tree_bytes", lambda _path: WHISPER_BYTES)
    check = module._doctor_models(_Request())
    assert check["ok"] is True, check
    assert asked == ["faster-whisper-small-verify"]
    assert "backend-owned: omnivoice" in check["detail"]
    assert f"faster-whisper-small-verify {WHISPER_BYTES} B" in check["detail"]
    assert check["fix"] == ""


def test_the_doctor_still_fails_a_backend_entry_free_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The skip does not soften the byte check for a real, sourced model."""
    module = _import_runner(monkeypatch, tmp_path)

    class _Request:
        def model_path(self, model_id: str) -> Path:
            return tmp_path / model_id

    monkeypatch.setattr(module, "_tree_bytes", lambda _path: WHISPER_BYTES - 1)
    check = module._doctor_models(_Request())
    assert check["ok"] is False
    assert f"manifest says {WHISPER_BYTES}" in check["detail"]


def _run_doctor(
    tmp_path: Path, url: str, machine: dict[str, str], depth: str = "quick"
) -> dict[str, object]:
    """The doctor verb on a stub SDK, a canned nvidia-smi on PATH, no real GPU."""
    out = tmp_path / "out"
    out.mkdir()
    stub_dir = _stub_dir(tmp_path)
    machine_dir = tmp_path / "fake-path"
    machine_dir.mkdir()
    (machine_dir / "nvidia-smi").write_text(FAKE_NVIDIA_SMI, encoding="utf-8")
    os.chmod(machine_dir / "nvidia-smi", 0o755)
    request = {
        "protocol": 1,
        "verb": "doctor",
        "capability": "voicestudio.speak",
        "depth": depth,
        "inputs": {},
        "out_dir": str(out),
        "piece_dir": str(tmp_path),
        "models": {},
        "assets": [],
    }
    input_path = tmp_path / "doctor-request.json"
    result_path = tmp_path / "doctor-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    calls = tmp_path / "whisper-calls.jsonl"
    calls.touch()
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "PATH": str(machine_dir) + os.pathsep + os.environ["PATH"],
        "STUB_CALLS": str(calls),
        "STUB_HEARD": "[]",
        "FACET_SERVER_URL": url,
        "FAKE_GPU_LINE": FAKE_GPU_LINE,
        "FAKE_GPU_MEMORY": FAKE_GPU_MEMORY,
        "FAKE_COMPUTE_APPS": "",
        **machine,
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
    return _result(result_path)


def test_the_doctor_tells_the_machine_and_the_package_apart(tmp_path: Path) -> None:
    """Quick depth: gpu, vram, gpu_free then imports, models — no backend/profile."""
    process, url, _files = _backend(tmp_path, ["ready"])
    try:
        result = _run_doctor(tmp_path, url, {})
    finally:
        process.terminate()
        process.wait(timeout=10)
    checks = {
        check["name"]: check
        for check in result["checks"]  # type: ignore[index]
        if isinstance(check, dict)
    }
    assert set(checks) == {"gpu", "vram", "gpu_free", "imports", "models"}
    assert checks["gpu"]["ok"] is True  # type: ignore[index]
    assert checks["gpu"]["detail"] == FAKE_GPU_LINE  # type: ignore[index]
    assert checks["vram"]["ok"] is True  # type: ignore[index]
    assert checks["vram"]["detail"] == FAKE_GPU_MEMORY  # type: ignore[index]
    assert checks["gpu_free"]["ok"] is True  # type: ignore[index]
    assert "owns the GPU" in checks["gpu_free"]["detail"]  # type: ignore[index]
    assert checks["models"]["fix"] == "facet pull voicestudio"  # type: ignore[index]
    assert checks["models"]["ok"] is False  # nothing pulled: the fix is the pull


def test_the_gpu_free_check_fails_when_another_model_holds_the_vram(tmp_path: Path) -> None:
    """No backend answering, a foreign compute app on the GPU: one model at a time."""
    process, dead_url, _files = _backend(tmp_path, ["ready"])
    dead_port = dead_url.rsplit(":", 1)[1]
    process.terminate()  # the URL stays: nothing listens on that port any more
    process.wait(timeout=10)
    result = _run_doctor(tmp_path, dead_url, {"FAKE_COMPUTE_APPS": FAKE_COMPUTE_ROW})
    checks = {
        check["name"]: check
        for check in result["checks"]  # type: ignore[index]
        if isinstance(check, dict)
    }
    free = checks["gpu_free"]
    assert free["ok"] is False  # type: ignore[index]
    assert FAKE_COMPUTE_ROW in free["detail"]  # type: ignore[index]
    assert free["fix"] == "stop the other GPU job: one model at a time"  # type: ignore[index]
    assert dead_port  # the dead URL was used, not the default one


def test_a_broken_nvidia_smi_fails_gpu_and_vram_with_the_fix(tmp_path: Path) -> None:
    """nvidia-smi exiting 1 fails both machine probes and names the driver fix."""
    process, dead_url, _files = _backend(tmp_path, ["ready"])
    process.terminate()
    process.wait(timeout=10)
    result = _run_doctor(tmp_path, dead_url, {"FAKE_EXIT": "1"})
    checks = {
        check["name"]: check
        for check in result["checks"]  # type: ignore[index]
        if isinstance(check, dict)
    }
    for name in ("gpu", "vram"):
        assert checks[name]["ok"] is False  # type: ignore[index]
        assert checks[name]["fix"] == "install the NVIDIA driver"  # type: ignore[index]


def _import_engines() -> Any:
    """The provisioning helpers as their own module, stubbed per test."""
    spec = importlib.util.spec_from_file_location(
        "voicestudio_engines_unit", PACKAGE / "engines.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_already_installed_engine_returns_without_posting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status first: ``installed`` true means no POST and no wait."""
    engines = _import_engines()

    def fail_post(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("no POST when the engine is installed")

    monkeypatch.setattr(
        engines,
        "_fetch_json",
        lambda *_args, **_kwargs: {"installed": True, "install_dir": "/d/voxcpm2"},
    )
    monkeypatch.setattr(engines, "_post_json", fail_post)
    assert engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2") is None


def test_a_missing_engine_installs_then_polls_to_installed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not installed: one POST, progress on each state change, return on installed."""
    engines = _import_engines()
    starting = [
        {"id": "preflight", "state": "running", "detail": None},
        {"id": "fetch_source", "state": "pending", "detail": None},
    ]
    fetching = [
        {"id": "preflight", "state": "done", "detail": "uv found, disk space OK"},
        {"id": "fetch_source", "state": "running", "detail": None},
    ]
    statuses = [
        {"installed": False, "job": {"state": "running", "steps": starting}},
        {"installed": False, "job": {"state": "running", "steps": starting}},
        {"installed": False, "job": {"state": "running", "steps": fetching}},
        {"installed": True, "install_dir": "/d/voxcpm2", "job": {"state": "succeeded"}},
    ]
    posts: list[tuple[object, ...]] = []

    def scripted_fetch(*_args: object, **_kwargs: object) -> dict[str, object]:
        return dict(statuses.pop(0))

    def record_post(*args: object, **_kwargs: object) -> dict[str, object]:
        posts.append(args)
        return {}

    monkeypatch.setattr(engines, "_fetch_json", scripted_fetch)
    monkeypatch.setattr(engines, "_post_json", record_post)
    monkeypatch.setattr(engines, "ENGINE_POLL_S", 0.0)
    assert engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2") is None
    assert len(posts) == 1
    progress = capsys.readouterr().err
    assert "voicestudio: installing voxcpm2: running preflight" in progress
    assert "voicestudio: installing voxcpm2: running fetch_source" in progress


def test_a_409_names_the_machine_as_unservable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """409 on POST: the host cannot serve the engine, with the backend's sentence."""
    engines = _import_engines()
    monkeypatch.setattr(
        engines, "_fetch_json", lambda *_args, **_kwargs: {"installed": False, "job": {}}
    )

    def conflict(*_args: object, **_kwargs: object) -> object:
        raise engines._HttpError(
            engines.HTTP_CONFLICT, json.dumps({"detail": "no CUDA on this host"})
        )

    monkeypatch.setattr(engines, "_post_json", conflict)
    with pytest.raises(RuntimeError) as caught:
        engines._ensure_engine("http://127.0.0.1:3900", "cosyvoice")
    assert "cosyvoice: VoiceStudio cannot install it on this machine" in str(caught.value)
    assert "no CUDA on this host" in str(caught.value)


def test_a_job_error_raises_with_error_and_remediation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed install job carries what broke and what settles it."""
    engines = _import_engines()
    status = {
        "installed": False,
        "job": {
            "state": "failed",
            "steps": ["fetch"],
            "error": "disk full",
            "remediation": "free 10 GB",
        },
    }
    monkeypatch.setattr(engines, "_fetch_json", lambda *_args, **_kwargs: status)
    monkeypatch.setattr(engines, "_post_json", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(engines, "ENGINE_POLL_S", 0.0)
    with pytest.raises(RuntimeError) as caught:
        engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2")
    assert "disk full" in str(caught.value)
    assert "free 10 GB" in str(caught.value)


def test_an_install_that_never_finishes_raises_and_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A patched clock past the budget: the run fails, the next run resumes the job."""
    engines = _import_engines()
    status = {"installed": False, "job": {"state": "running", "steps": ["fetch"]}}
    monkeypatch.setattr(engines, "_fetch_json", lambda *_args, **_kwargs: status)
    monkeypatch.setattr(engines, "_post_json", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(engines, "ENGINE_POLL_S", 0.0)
    ticks = [1000.0, 1000.0 + 6000.0]
    monkeypatch.setattr(engines.time, "monotonic", lambda: ticks.pop(0))
    with pytest.raises(RuntimeError) as caught:
        engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2")
    assert "install not finished after 5400 s" in str(caught.value)
    assert "facet run again resumes it" in str(caught.value)


def test_an_omnivoice_run_never_touches_the_sidecar_endpoints(tmp_path: Path) -> None:
    """``omnivoice`` is in-process: no status check, no install POST."""
    result, _stdout = _run_cycle(tmp_path, ["ready"], [TEXT], model="omnivoice")
    assert result["assets"][0]["properties"]["model"] == "omnivoice"  # type: ignore[index]
    gets = _read_lines(tmp_path / "stub-logs" / "gets.jsonl")
    assert all("/engines/" not in entry["path"] for entry in gets)
    assert _read_lines(tmp_path / "stub-logs" / "installs.jsonl") == []


def test_the_doctor_reports_an_installed_sidecar_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installed: ok, with the directory the status names."""
    module = _import_runner(monkeypatch, tmp_path)
    engines_module = importlib.import_module("engines")
    monkeypatch.setattr(
        engines_module,
        "engine_status",
        lambda _base, _engine, timeout_s=10.0: {
            "installed": True,
            "install_dir": "/data/voicestudio/engines/voxcpm2",
        },
    )
    assert module._doctor_engine("http://127.0.0.1:3900", "voxcpm2") == {
        "name": "engines-voxcpm2",
        "ok": True,
        "detail": "voxcpm2 installed at /data/voicestudio/engines/voxcpm2",
        "fix": "",
    }


def test_the_doctor_reports_an_engine_the_first_run_will_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not installed: still ok, with the size the first run will fetch."""
    module = _import_runner(monkeypatch, tmp_path)
    engines_module = importlib.import_module("engines")
    monkeypatch.setattr(
        engines_module,
        "engine_status",
        lambda _base, _engine, timeout_s=10.0: {"installed": False, "job": {}},
    )
    check = module._doctor_engine("http://127.0.0.1:3900", "cosyvoice")
    assert check["ok"] is True
    assert "cosyvoice not installed yet" in check["detail"]
    assert "~13 GB" in check["detail"]


def test_the_doctor_fails_an_engine_whose_status_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The doctor never POSTs: an unreadable status is not ok, with the error text."""
    module = _import_runner(monkeypatch, tmp_path)
    engines_module = importlib.import_module("engines")

    def broken(_base: str, _engine: str, timeout_s: float = 10.0) -> object:
        raise OSError("connection refused")

    monkeypatch.setattr(engines_module, "engine_status", broken)
    check = module._doctor_engine("http://127.0.0.1:3900", "voxcpm2")
    assert check["ok"] is False
    assert "connection refused" in check["detail"]


def test_the_full_doctor_lists_each_sidecar_engine_and_never_posts(tmp_path: Path) -> None:
    """Full depth: one engines check per sidecar engine, read from status only."""
    profiles = [{"id": "d4e9ee57", "name": "narradora"}]
    process, url, _files = _backend(tmp_path, ["ready"], profiles=profiles)
    try:
        result = _run_doctor(tmp_path, url, {}, depth="full")
    finally:
        process.terminate()
        process.wait(timeout=10)
    checks = {
        check["name"]: check
        for check in result["checks"]  # type: ignore[index]
        if isinstance(check, dict)
    }
    for engine in ("voxcpm2", "cosyvoice"):
        check = checks[f"engines-{engine}"]
        assert check["ok"] is True
        assert f"{engine} installed at" in check["detail"]
    gets = [str(entry["path"]) for entry in _read_lines(tmp_path / "stub-logs" / "gets.jsonl")]
    for engine in ("voxcpm2", "cosyvoice"):
        assert f"/engines/sidecar/{engine}/install/status" in gets
    assert _read_lines(tmp_path / "stub-logs" / "installs.jsonl") == []  # the doctor never POSTs


def test_the_doctor_fails_cosyvoice_when_no_cxx_compiler_can_build_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cosyvoice compiles pyworld on install: without g++ the doctor names the fix."""
    module = _import_runner(monkeypatch, tmp_path)
    engines_module = importlib.import_module("engines")
    monkeypatch.setattr(
        engines_module,
        "engine_status",
        lambda _base, _engine, timeout_s=10.0: {"installed": False, "job": {}},
    )
    monkeypatch.setattr(engines_module.shutil, "which", lambda _name: None)
    check = module._doctor_engine("http://127.0.0.1:3900", "cosyvoice")
    assert check["ok"] is False
    assert "g++" in check["detail"]
    assert check["fix"] == "sudo apt install build-essential"
    assert module._doctor_engine("http://127.0.0.1:3900", "voxcpm2")["ok"] is True


def test_ensure_engine_refuses_cosyvoice_before_posting_without_a_compiler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The install is never started when it would fail compiling pyworld."""
    _import_runner(monkeypatch, tmp_path)
    engines_module = importlib.import_module("engines")
    posts: list[str] = []
    monkeypatch.setattr(
        engines_module,
        "engine_status",
        lambda _base, _engine, timeout_s=10.0: {"installed": False, "job": {}},
    )
    monkeypatch.setattr(
        engines_module, "_post_json", lambda _base, path, _timeout: posts.append(path)
    )
    monkeypatch.setattr(engines_module.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="build-essential"):
        engines_module._ensure_engine("http://127.0.0.1:3900", "cosyvoice")
    assert posts == []
