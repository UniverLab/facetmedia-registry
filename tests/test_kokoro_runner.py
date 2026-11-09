"""The kokoro preview against a stub SDK, whisper and audio helpers.

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

import json
import os
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
FLAT_TARGET_LUFS = -18.0
PIECE_TARGET_LUFS = -16.0
WHISPER_BEAM_SIZE = 5
PreviewRun = tuple[
    subprocess.CompletedProcess[str],
    dict[str, Any] | None,
    dict[str, Any] | None,
    list[dict[str, Any]],
]

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

#: The audio surface preview reads, fixed on one second of 24 kHz zeros.
STUB_AUDIO = """
import numpy

RATE_HZ = 24000


def read_wav(_path):
    return numpy.zeros(RATE_HZ, dtype=numpy.float32), RATE_HZ


def duration_s(samples, rate):
    return len(samples) / rate


def waveform(_samples):
    return {"bins": 1200, "min": [0.0] * 1200, "max": [0.0] * 1200}


def integrated_lufs(_samples, _rate):
    return -18.0


def peak_dbfs(_samples):
    return -1.0


def momentary(_samples, _rate):
    return [-18.0]


def silences(_samples, _rate):
    return []


def clipped_samples(_samples):
    return 0
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
) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": "preview",
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


def _run_preview(
    tmp_path: Path,
    inputs: dict[str, object],
    asset_name: str,
    heard: list[str],
    tag: str,
) -> PreviewRun:
    """One ``preview`` verb as a subprocess over the stub environment."""
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
        json.dumps(_request(out, piece, inputs, asset, model)), encoding="utf-8"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "STUB_CALLS": str(calls),
        "STUB_HEARD": json.dumps(heard),
    }
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "preview",
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
    preview_path = out / f"{asset_name}.preview.json"
    data = json.loads(preview_path.read_text(encoding="utf-8")) if preview_path.exists() else None
    return done, result, data, _read_lines(calls)


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
