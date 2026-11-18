"""The kokoro preview and verify against a stub SDK, whisper and audio helpers.

The runner is a subprocess of the host ``python`` with a stub
``facet_runner_sdk`` on ``PYTHONPATH`` (the pull-time surface the real one
copies in), a stub ``faster_whisper`` that records its calls and returns a
scripted transcript, and a stub ``facet_lib.audiopreview`` over one second of
numpy zeros. The registry's own ``lib/textnorm.py`` is copied into the stub
``facet_lib`` so the WER folds exactly like the pull-time copy. No model, no
network, no GPU: the whisper "model" is a placeholder path the stub never
reads.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "kokoro"
RUNNER = PACKAGE / "runner.py"
RATE_HZ = 24_000
TEXT = "En este laboratorio probamos una voz en español."
#: A different text, so a test can prove which one the clip came from.
PER_CLIP_TEXT = "Presentamos la voz del laboratorio."
FLAT_TARGET_LUFS = -18.0
PIECE_TARGET_LUFS = -16.0
WHISPER_BEAM_SIZE = 5
PreviewRun = tuple[
    subprocess.CompletedProcess[str],
    dict[str, Any] | None,
    dict[str, Any] | None,
    list[dict[str, Any]],
]
VerifyRun = tuple[
    subprocess.CompletedProcess[str],
    dict[str, Any] | None,
    list[dict[str, Any]],
]
RawRun = tuple[
    subprocess.CompletedProcess[str],
    dict[str, Any] | None,
    Path,
    list[dict[str, Any]],
]
#: The manifest's word error rate, mirrored from the runner under test.
WER_MAX = 0.05

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

#: The audio surface: reads real WAVs and computes dropout; other values fixed.
STUB_AUDIO = r"""
import math
import wave

import numpy

RATE_HZ = 24000


def read_wav(path):
    with wave.open(str(path), "rb") as reader:
        rate = reader.getframerate()
        frames = reader.getnframes()
        channels = reader.getnchannels()
        width = reader.getsampwidth()
        raw = reader.readframes(frames)
    if width == 2:
        data = numpy.frombuffer(raw, dtype=numpy.int16).astype(numpy.float64) / 32768.0
    elif width == 1:
        data = (numpy.frombuffer(raw, dtype=numpy.uint8).astype(numpy.float64) - 128.0) / 128.0
    else:
        data = numpy.frombuffer(raw, dtype=numpy.int16).astype(numpy.float64) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels)
    return data, int(rate)


def duration_s(samples, rate):
    return len(samples) / rate


def _mono(samples):
    if samples.ndim == 1:
        return samples
    return samples.mean(axis=1)


def peak_dbfs(samples):
    peak = float(numpy.max(numpy.abs(samples))) if len(samples) else 0.0
    if peak <= 0.0:
        return -1.0
    return max(20.0 * math.log10(peak), -160.0)


def waveform(_samples):
    return {"bins": 1200, "min": [0.0] * 1200, "max": [0.0] * 1200}


def integrated_lufs(_samples, _rate):
    return -18.0


def momentary(_samples, _rate):
    return [-18.0]


def silences(_samples, _rate):
    return []


def clipped_samples(_samples):
    return 0


def digital_dropout_ms(samples, rate):
    if rate <= 0:
        return 0.0
    mono = _mono(samples)
    nonzero = numpy.flatnonzero(mono)
    if nonzero.size == 0:
        return 0.0
    first = int(nonzero[0])
    last = int(nonzero[-1])
    if last - first <= 1:
        return 0.0
    interior = mono[first + 1 : last]
    zeros = interior == 0
    if not zeros.any():
        return 0.0
    padded = numpy.concatenate(([False], zeros, [False]))
    diff = numpy.diff(padded.astype(numpy.int8))
    starts = numpy.flatnonzero(diff == 1)
    ends = numpy.flatnonzero(diff == -1)
    if starts.size == 0:
        return 0.0
    longest = int(numpy.max(ends - starts))
    return longest * 1000.0 / rate
"""


def _stub_dir(tmp_path: Path) -> Path:
    """The PYTHONPATH stub: SDK, whisper, and facet_lib with textnorm + audio."""
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
    (facet_lib / "audiopreview.py").write_text(STUB_AUDIO, encoding="utf-8")
    return folder


def _write_wav(path: Path) -> None:
    """One second of PCM 16-bit silence at Kokoro's rate."""
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(RATE_HZ)
        writer.writeframes(b"\x00\x00" * RATE_HZ)


def _request(
    out_dir: Path,
    piece_dir: Path,
    inputs: dict[str, object],
    asset: Path,
    model: Path,
    verb: str = "preview",
) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "kokoro.speak",
        "depth": "quick",
        "inputs": inputs,
        "out_dir": str(out_dir),
        "piece_dir": str(piece_dir),
        "models": {"faster-whisper-small": str(model)},
        "assets": [str(asset)],
    }


def _read_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _transcriptions(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [call for call in calls if call.get("call") == "transcribe"]


def _run_verb(
    tmp_path: Path,
    verb: str,
    inputs: dict[str, object],
    asset_name: str,
    heard: list[str],
    tag: str,
) -> RawRun:
    """One verb as a subprocess over the stub environment, plus its out dir."""
    stub_dir = _stub_dir(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    piece = tmp_path / "piece"
    piece.mkdir()
    asset = out / asset_name
    _write_wav(asset)
    model = tmp_path / "faster-whisper-small"
    model.mkdir()
    calls = tmp_path / "whisper-calls.jsonl"
    calls.touch()
    request_path = tmp_path / f"{tag}-request.json"
    result_path = tmp_path / f"{tag}-result.json"
    request_path.write_text(
        json.dumps(_request(out, piece, inputs, asset, model, verb=verb)), encoding="utf-8"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "STUB_CALLS": str(calls),
        "STUB_HEARD": json.dumps(heard),
        "FACET_HOME": str(tmp_path / "facet-home"),
    }
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            verb,
            "--input",
            str(request_path),
            "--result",
            str(result_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    return done, result, out, _read_lines(calls)


def _run_preview(
    tmp_path: Path,
    inputs: dict[str, object],
    asset_name: str,
    heard: list[str],
    tag: str,
) -> PreviewRun:
    """One ``preview`` verb, with the preview file it wrote."""
    done, result, out, calls = _run_verb(tmp_path, "preview", inputs, asset_name, heard, tag)
    preview_path = out / f"{asset_name}.preview.json"
    data = json.loads(preview_path.read_text(encoding="utf-8")) if preview_path.exists() else None
    return done, result, data, calls


def _run_verify(
    tmp_path: Path,
    inputs: dict[str, object],
    asset_name: str,
    heard: list[str],
    tag: str,
) -> VerifyRun:
    """One ``verify`` verb as a subprocess over the stub environment."""
    done, result, _out, calls = _run_verb(tmp_path, "verify", inputs, asset_name, heard, tag)
    return done, result, calls


def _assert_speech(data: dict[str, Any]) -> None:
    assert data["preview"] == 1
    assert data["kind"] == "audio"
    assert data["speech"]["text"] == TEXT
    assert data["speech"]["transcript"] == TEXT
    assert data["speech"]["wer"] == 0.0
    assert data["speech"]["alignment"]


def test_preview_accepts_flat_record_params(tmp_path: Path) -> None:
    """The run record's flat per-clip params still name the clip to preview."""
    inputs = {
        "name": "cierre-voz",
        "text": TEXT,
        "voice": "em_alex",
        "language": "es",
        "speed": 1.25,
        "target-lufs": FLAT_TARGET_LUFS,
    }
    done, result, data, calls = _run_preview(tmp_path, inputs, "cierre-voz.wav", [TEXT], "flat")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert result["assets"] == [
        {"file": "cierre-voz.wav", "preview": "cierre-voz.wav.preview.json", "images": []}
    ]
    assert data is not None
    _assert_speech(data)
    assert data["loudness"]["target_lufs"] == FLAT_TARGET_LUFS
    assert data["summary"].endswith("· em_alex")
    heard = _transcriptions(calls)
    assert len(heard) == 1
    assert heard[0]["language"] == "es"
    assert heard[0]["beam_size"] == WHISPER_BEAM_SIZE
    assert heard[0]["vad_filter"] is True


def test_preview_keeps_the_clip_array_path(tmp_path: Path) -> None:
    """A piece request's clip array is unchanged: per-clip fields still win."""
    inputs = {
        "language": "es",
        "voice": "ef_dora",
        "speed": 1.0,
        "target-lufs": PIECE_TARGET_LUFS,
        "clip": [{"name": "intro", "text": TEXT, "voice": "em_alex", "speed": 1.5}],
    }
    done, result, data, calls = _run_preview(tmp_path, inputs, "intro.wav", [TEXT], "array")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert result["assets"] == [
        {"file": "intro.wav", "preview": "intro.wav.preview.json", "images": []}
    ]
    assert data is not None
    _assert_speech(data)
    assert data["loudness"]["target_lufs"] == PIECE_TARGET_LUFS
    assert data["summary"].endswith("· em_alex")
    heard = _transcriptions(calls)
    assert len(heard) == 1
    assert heard[0]["language"] == "es"


def test_verify_accepts_flat_record_params(tmp_path: Path) -> None:
    """The run record's flat per-clip params still name the clip to verify."""
    inputs = {
        "name": "voz",
        "text": TEXT,
        "voice": "em_alex",
        "language": "es",
        "speed": 1.0,
        "target-lufs": FLAT_TARGET_LUFS,
    }
    done, result, calls = _run_verify(tmp_path, inputs, "voz.wav", [TEXT], "verify-flat")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert len(result["assets"]) == 1
    entry = result["assets"][0]
    assert entry["file"] == "voz.wav"
    assert entry["passed"] is True
    assert entry["metrics"]["wer"] <= WER_MAX
    assert entry["metrics"]["transcript"] == TEXT
    assert entry["metrics"]["words"] > 0
    assert entry["thresholds"]["wer_max"] == WER_MAX
    heard = _transcriptions(calls)
    assert len(heard) == 1
    assert heard[0]["language"] == "es"
    assert heard[0]["beam_size"] == WHISPER_BEAM_SIZE
    assert heard[0]["vad_filter"] is True


def test_verify_keeps_the_clip_array_path(tmp_path: Path) -> None:
    """A piece request's clip array is unchanged: its own text wins over flat fields."""
    inputs = {
        "name": "intro",
        "text": TEXT,
        "language": "es",
        "voice": "ef_dora",
        "speed": 1.0,
        "target-lufs": PIECE_TARGET_LUFS,
        "clip": [{"name": "intro", "text": PER_CLIP_TEXT, "voice": "em_alex", "speed": 1.5}],
    }
    done, result, calls = _run_verify(
        tmp_path, inputs, "intro.wav", [PER_CLIP_TEXT], "verify-array"
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert len(result["assets"]) == 1
    entry = result["assets"][0]
    assert entry["file"] == "intro.wav"
    assert entry["passed"] is True
    assert entry["metrics"]["wer"] == 0.0
    assert entry["thresholds"]["wer_max"] == WER_MAX
    heard = _transcriptions(calls)
    assert len(heard) == 1
    assert heard[0]["language"] == "es"


DROPOUT_MAX_MS = 200.0


def _kokoro_cache_key(
    voice: str, language: str, text: str, speed: float, target_lufs: float
) -> str:
    payload = {
        "language": language,
        "models": ["kokoro-82m-v1.0-onnx", "kokoro-voices-v1.0"],
        "speed": float(speed),
        "target_lufs": float(target_lufs),
        "text": text,
        "tool": "kokoro-onnx",
        "tool_version": "0.6.1",
        "voice": voice,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _write_tone_wav(path: Path, rate: int = RATE_HZ, frames: int = RATE_HZ) -> None:
    """A simple non-silent PCM16 WAV."""
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        samples = bytearray()
        for i in range(frames):
            value = int(12000 * math.sin(2 * math.pi * 220 * i / rate))
            samples += struct.pack("<h", value)
        writer.writeframes(bytes(samples))


def _write_dropout_wav(path: Path, rate: int = RATE_HZ) -> None:
    """Tone with a 300 ms interior all-zero block (dropout)."""
    frames = rate  # 1s
    start_zero = int(0.3 * rate)
    end_zero = start_zero + int(0.3 * rate)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        samples = bytearray()
        for i in range(frames):
            if start_zero <= i < end_zero:
                value = 0
            else:
                value = int(12000 * math.sin(2 * math.pi * 220 * i / rate))
            samples += struct.pack("<h", value)
        writer.writeframes(bytes(samples))


def _run_request(tmp_path: Path, inputs: dict[str, object], facet_home: Path, tag: str):
    stub_dir = _stub_dir(tmp_path)
    out = tmp_path / f"out-{tag}"
    out.mkdir()
    piece = tmp_path / f"piece-{tag}"
    piece.mkdir()
    request_path = tmp_path / f"{tag}-request.json"
    result_path = tmp_path / f"{tag}-result.json"
    calls = tmp_path / f"calls-{tag}.jsonl"
    calls.touch()
    request = {
        "protocol": 1,
        "verb": "run",
        "capability": "kokoro.speak",
        "depth": "quick",
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(piece),
        "models": {},
        "assets": [],
    }
    request_path.write_text(json.dumps(request), encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "FACET_HOME": str(facet_home),
        "STUB_CALLS": str(calls),
        "STUB_HEARD": "[]",
    }
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "run",
            "--input",
            str(request_path),
            "--result",
            str(result_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    return done, result, out


def _cache_file(facet_home: Path, key: str) -> Path:
    return facet_home / "data" / "kokoro" / "clip-cache" / f"{key}.wav"


def test_run_cache_hit_skips_synthesis(tmp_path: Path) -> None:
    facet_home = tmp_path / "home"
    key = _kokoro_cache_key("ef_dora", "es", "hola", 1.0, -16.0)
    cache_path = _cache_file(facet_home, key)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    _write_tone_wav(cache_path)
    inputs = {
        "voice": "ef_dora",
        "language": "es",
        "speed": 1.0,
        "target-lufs": -16.0,
        "clip": [{"name": "saludo", "text": "hola"}],
    }
    done, result, out = _run_request(tmp_path, inputs, facet_home, "hit")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    asset = result["assets"][0]
    assert asset["file"] == "saludo.wav"
    assert asset["properties"]["cached"] is True
    assert (out / "saludo.wav").is_file()


def test_verify_stores_passed_clip_in_cache(tmp_path: Path) -> None:
    facet_home = tmp_path / "home"
    inputs = {
        "name": "voz",
        "text": TEXT,
        "voice": "ef_dora",
        "language": "es",
        "speed": 1.0,
        "target-lufs": -16.0,
        "cache": True,
    }
    stub_dir = _stub_dir(tmp_path)
    out = tmp_path / "out-store"
    out.mkdir()
    piece = tmp_path / "piece-store"
    piece.mkdir()
    asset = out / "voz.wav"
    _write_tone_wav(asset)
    model = tmp_path / "faster-whisper-small"
    model.mkdir()
    calls = tmp_path / "calls-store.jsonl"
    calls.touch()
    request_path = tmp_path / "store-request.json"
    result_path = tmp_path / "store-result.json"
    request_path.write_text(
        json.dumps(_request(out, piece, inputs, asset, model, verb="verify")), encoding="utf-8"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "STUB_CALLS": str(calls),
        "STUB_HEARD": json.dumps([TEXT]),
        "FACET_HOME": str(facet_home),
    }
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "verify",
            "--input",
            str(request_path),
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
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["assets"][0]["passed"] is True
    assert "digital_silence_run_ms" in result["assets"][0]["metrics"]
    key = _kokoro_cache_key("ef_dora", "es", TEXT, 1.0, -16.0)
    assert _cache_file(facet_home, key).is_file()


def test_verify_dropout_fails_and_not_cached(tmp_path: Path) -> None:
    facet_home = tmp_path / "home"
    stub_dir = _stub_dir(tmp_path)
    out = tmp_path / "out-drop"
    out.mkdir()
    piece = tmp_path / "piece-drop"
    piece.mkdir()
    asset = out / "voz.wav"
    _write_dropout_wav(asset)
    model = tmp_path / "faster-whisper-small"
    model.mkdir()
    calls = tmp_path / "calls-drop.jsonl"
    calls.touch()
    inputs = {
        "name": "voz",
        "text": TEXT,
        "voice": "ef_dora",
        "language": "es",
        "speed": 1.0,
        "target-lufs": -16.0,
        "cache": True,
    }
    request_path = tmp_path / "drop-request.json"
    result_path = tmp_path / "drop-result.json"
    request_path.write_text(
        json.dumps(_request(out, piece, inputs, asset, model, verb="verify")), encoding="utf-8"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "STUB_CALLS": str(calls),
        "STUB_HEARD": json.dumps([TEXT]),
        "FACET_HOME": str(facet_home),
    }
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "verify",
            "--input",
            str(request_path),
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
    result = json.loads(result_path.read_text(encoding="utf-8"))
    entry = result["assets"][0]
    assert entry["passed"] is False
    assert entry["metrics"]["digital_silence_run_ms"] > DROPOUT_MAX_MS
    key = _kokoro_cache_key("ef_dora", "es", TEXT, 1.0, -16.0)
    assert not _cache_file(facet_home, key).exists()


def test_run_cache_bypass_does_not_read_cache(tmp_path: Path) -> None:
    facet_home = tmp_path / "home"
    key = _kokoro_cache_key("ef_dora", "es", "hola", 1.0, -16.0)
    cache_path = _cache_file(facet_home, key)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    _write_tone_wav(cache_path)
    inputs = {
        "voice": "ef_dora",
        "language": "es",
        "speed": 1.0,
        "target-lufs": -16.0,
        "cache": False,
        "clip": [{"name": "saludo", "text": "hola"}],
    }
    # bypass means must not use cache; without real kokoro synth this may fail,
    # but it must not take the cache-hit path.
    done, result, out = _run_request(tmp_path, inputs, facet_home, "bypass")
    # if it hit cache it would succeed with cached:true; bypass must not hit
    if done.returncode == 0 and result is not None:
        assert result["assets"][0]["properties"]["cached"] is False
    else:
        # failed because synth unavailable in stub env: proves it didn't take cache-hit path
        assert not (out / "saludo.wav").exists()
        assert result is None or "cached" not in json.dumps(result)
