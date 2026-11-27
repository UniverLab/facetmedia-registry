"""The ffmpeg normalize path against a hot voice, with the bundled static binary.

The v1 defect: normalizing the kokoro ``ef_dora`` Spanish voice always came
out at about -20.22 LUFS whatever the target (-16, -20, -12) or rate. The
voice enters near -20 LUFS with its peak at -1 dBFS, so the gain a -16
target needs would push the peak past the true-peak ceiling and both
loudnorm passes stalled; changing loudnorm's arguments alone cannot create
headroom. The fix is an ``acompressor`` pre-stage both passes now share.

The fixture is synthesized here with the standard library only (``wave``,
``math``, ``struct``, no numpy): gated speech-like bursts at 48 kHz mono,
hot enough (peak at or above -1 dBFS, integrated near -20 LUFS) to
reproduce the defect without the fix. The runner runs as a subprocess of
the package environment's own python over a stub SDK, with the registry's
real ``lib/audiopreview.py`` copied in, so the measurements are the real
ones the runner reports. No committed binary, no model, no network, no GPU.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import struct
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "ffmpeg"
RUNNER = PACKAGE / "runner.py"
PYTHON = PACKAGE / ".venv" / "bin" / "python"
REAL_VOICE = ROOT / "tests" / "fixtures" / "ffmpeg" / "cierre-voz.wav"
SPEC = importlib.util.spec_from_file_location("ffmpeg_graph_clean", PACKAGE / "graph.py")
assert SPEC is not None and SPEC.loader is not None
graph = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(graph)
RATE = 48000
TP = -1.5
MARGIN = 0.1
TOL = 1.0
DURATION_TOL = 0.02
#: clean: how far the pre-stage may move a mono source's level, and how even the sides land.
UNITY_TOL_DB = 0.5
BALANCE_TOL_DB = 0.5
#: clean: a side quieter than this carries no voice.
SILENT_SIDE_DB = -40.0
#: The output channel counts the clean tests ask for.
MONO_CHANNELS = 1
STEREO_CHANNELS = 2
TARGETS = (-16.0, -20.0, -12.0)
HOT_DURATION = 3.72
BURSTS = 6
BURST_S = 0.42
GAP_S = 0.20
PULSE_S = 0.003
PULSE_HZ = 1800.0
PULSE_GAIN = 0.891
VOICE_GAIN = 0.30

pytestmark = pytest.mark.skipif(
    not PYTHON.exists(), reason="sync the package env with `uv sync --project packages/ffmpeg`"
)

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


def _lcg(count: int) -> list[float]:
    """A deterministic white-noise floor in [-1, 1]."""
    state = 12345
    values: list[float] = []
    for _ in range(count):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        values.append(state / 0x3FFFFFFF - 1.0)
    return values


def _pcm16(samples: list[float]) -> bytes:
    return b"".join(struct.pack("<h", int(round(max(-1.0, min(1.0, x)) * 32767))) for x in samples)


def _write_wav(path: Path, payload: bytes) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        writer.writeframes(payload)


def _write_stereo(path: Path, left: list[float], right: list[float]) -> None:
    """Two channels at the fixture rate, 16-bit, from per-side sample lists."""
    interleaved: list[float] = []
    for index, value in enumerate(left):
        interleaved.extend([value, right[index]])
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        writer.writeframes(_pcm16(interleaved))


def _samples(payload: bytes) -> list[float]:
    """16-bit PCM bytes back to floats in [-1, 1]."""
    return [value / 32768.0 for (value,) in struct.iter_unpack("<h", payload)]


def _read_channels(path: Path) -> tuple[list[float], list[float] | None]:
    """A 16-bit WAV's samples per side; mono returns the second side as ``None``."""
    with wave.open(str(path), "rb") as reader:
        width = reader.getnchannels()
        frames = reader.readframes(reader.getnframes())
    values = [value / 32768.0 for (value,) in struct.iter_unpack("<h", frames)]
    if width == 1:
        return values, None
    return values[0::2], values[1::2]


def _level_db(samples: list[float]) -> float:
    """A channel's RMS in dBFS, floored so digital silence stays finite."""
    rms = math.sqrt(sum(value * value for value in samples) / max(len(samples), 1))
    return 20.0 * math.log10(rms + 1e-12)


def _pre_stage(
    tmp_path: Path, source: Path, channel: str
) -> tuple[list[float], list[float] | None]:
    """The clean pre-stage alone, denoise and high-pass off, read back as samples."""
    pre = tmp_path / "pre-stage-f32.wav"
    pcm = tmp_path / "pre-stage.wav"
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    args = graph.clean_pre_args(source, pre, channel, denoise=False, highpass_hz=0)
    done = subprocess.run(
        [exe, "-nostdin", "-hide_banner", "-y", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    done = subprocess.run(
        [exe, "-nostdin", "-hide_banner", "-y", "-i", str(pre), "-acodec", "pcm_s16le", str(pcm)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return _read_channels(pcm)


def _hot_voice() -> bytes:
    """Six gated speech-like bursts plus a 3 ms transient: ~-20 LUFS at ~-1 dBFS."""
    burst = int(BURST_S * RATE)
    gap = int(GAP_S * RATE)
    total = BURSTS * (burst + gap)
    noise = _lcg(total)
    samples = [0.0] * total
    for index in range(BURSTS):
        base = index * (burst + gap)
        for i in range(burst):
            t = i / RATE
            env = math.sin(math.pi * i / burst) ** 0.4
            f0 = 140.0 + 18.0 * math.sin(2 * math.pi * 2.3 * t)
            phase = 2 * math.pi * f0 * t
            samples[base + i] = env * (
                0.55 * math.sin(phase)
                + 0.28 * math.sin(2 * phase)
                + 0.12 * math.sin(3 * phase)
                + 0.05 * noise[base + i]
            )
    peak = max(abs(x) for x in samples)
    fitted = [x * (VOICE_GAIN / peak) for x in samples]
    pulse_n = int(PULSE_S * RATE)
    pulse = [
        math.sin(2 * math.pi * PULSE_HZ * i / RATE) * (1 - i / pulse_n) for i in range(pulse_n)
    ]
    pulse_peak = max(abs(x) for x in pulse)
    for index in range(BURSTS):
        base = index * (burst + gap)
        for i in range(pulse_n):
            fitted[base + i] += PULSE_GAIN * pulse[i] / pulse_peak
    assert max(abs(x) for x in fitted) >= PULSE_GAIN
    return _pcm16(fitted)


def _sine(seconds: float = 2.0, hz: float = 440.0, amplitude: float = 0.5) -> bytes:
    return _pcm16(
        [amplitude * math.sin(2 * math.pi * hz * i / RATE) for i in range(int(seconds * RATE))]
    )


def _noise(seconds: float = 2.0, amplitude: float = 0.5) -> bytes:
    return _pcm16([amplitude * x for x in _lcg(int(seconds * RATE))])


def _stub_dir(tmp_path: Path) -> Path:
    """The PYTHONPATH stub: the SDK plus ``facet_lib`` with the real audio module."""
    folder = tmp_path / "stub"
    folder.mkdir()
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    facet_lib = folder / "facet_lib"
    facet_lib.mkdir()
    (facet_lib / "__init__.py").write_text("", encoding="utf-8")
    (facet_lib / "audiopreview.py").write_text(
        (ROOT / "lib" / "audiopreview.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return folder


def _base_request(out: Path, capability: str, inputs: dict[str, object]) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": "run",
        "capability": capability,
        "depth": "quick",
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(out),
        "models": {},
        "assets": [],
    }


def _normalize_request(out: Path, audio: Path, name: str, target: float) -> dict[str, object]:
    inputs = {
        "clip": [{"name": name, "audio": str(audio)}],
        "target-lufs": target,
        "true-peak-db": TP,
        "sample-rate-hz": "48000",
    }
    return _base_request(out, "ffmpeg.normalize", inputs)


def _invoke(tmp_path: Path, stub: Path, request: dict[str, object], tag: str) -> dict[str, object]:
    request_path = tmp_path / f"{tag}-request.json"
    result_path = tmp_path / f"{tag}-result.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(stub)}
    done = subprocess.run(
        [
            str(PYTHON),
            str(RUNNER),
            str(request["verb"]),
            "--input",
            str(request_path),
            "--result",
            str(result_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(result_path.read_text(encoding="utf-8"))


def _properties(result: dict[str, object]) -> dict[str, object]:
    assets = result["assets"]
    assert isinstance(assets, list) and assets
    properties = assets[0]["properties"]
    assert isinstance(properties, dict)
    return properties


def _normalize(tmp_path: Path, payload: bytes, name: str, target: float) -> dict[str, object]:
    source = tmp_path / f"{name}.wav"
    _write_wav(source, payload)
    out = tmp_path / "out"
    out.mkdir()
    stub = _stub_dir(tmp_path)
    request = _normalize_request(out, source, name, target)
    result = _invoke(tmp_path, stub, request, f"normalize-{name}-{abs(target):g}")
    return _properties(result)


@pytest.mark.parametrize("target", TARGETS)
def test_hot_voice_tracks_each_target(tmp_path: Path, target: float) -> None:
    properties = _normalize(tmp_path, _hot_voice(), "hot-voice", target)
    assert abs(float(properties["lufs"]) - target) <= TOL
    assert float(properties["peak_dbfs"]) <= TP + MARGIN
    assert abs(float(properties["duration_s"]) - HOT_DURATION) <= DURATION_TOL


@pytest.mark.parametrize("target", TARGETS)
def test_real_closure_voice_tracks_each_target(tmp_path: Path, target: float) -> None:
    """The committed kokoro ef_dora closure voice: every target lands, peak under the ceiling."""
    assert REAL_VOICE.exists(), f"missing committed fixture {REAL_VOICE}"
    out = tmp_path / "out"
    out.mkdir()
    stub = _stub_dir(tmp_path)
    request = _normalize_request(out, REAL_VOICE, "cierre-voz", target)
    properties = _properties(_invoke(tmp_path, stub, request, f"real-{abs(target):g}"))
    assert abs(float(properties["lufs"]) - target) <= TOL
    assert float(properties["peak_dbfs"]) <= TP + MARGIN


def test_run_then_verify_passes_at_minus_twelve(tmp_path: Path) -> None:
    source = tmp_path / "hot-voice.wav"
    _write_wav(source, _hot_voice())
    out = tmp_path / "out"
    out.mkdir()
    stub = _stub_dir(tmp_path)
    request = _normalize_request(out, source, "hot-voice", -12.0)
    _invoke(tmp_path, stub, request, "verify-run")
    verify = {**request, "verb": "verify", "assets": [str(out / "hot-voice.wav")]}
    result = _invoke(tmp_path, stub, verify, "verify-check")
    verdicts = result["assets"]
    assert isinstance(verdicts, list) and verdicts
    assert verdicts[0]["passed"] is True


def test_sine_tracks_target(tmp_path: Path) -> None:
    properties = _normalize(tmp_path, _sine(), "sine", -16.0)
    assert abs(float(properties["lufs"]) + 16.0) <= TOL
    assert float(properties["peak_dbfs"]) <= TP + MARGIN


def test_noise_tracks_target(tmp_path: Path) -> None:
    properties = _normalize(tmp_path, _noise(), "noise", -16.0)
    assert abs(float(properties["lufs"]) + 16.0) <= TOL
    assert float(properties["peak_dbfs"]) <= TP + MARGIN


def test_mix_tracks_target_and_keeps_the_peak_ceiling(tmp_path: Path) -> None:
    voice = tmp_path / "voice.wav"
    bed = tmp_path / "bed.wav"
    _write_wav(voice, _sine(seconds=1.5, hz=220.0, amplitude=0.6))
    _write_wav(bed, _noise(seconds=2.0, amplitude=0.2))
    out = tmp_path / "out"
    out.mkdir()
    stub = _stub_dir(tmp_path)
    inputs = {
        "name": "voice-over-bed",
        "layer": [
            {"audio": str(voice), "role": "voice", "start-s": 0.0, "gain-db": 0.0},
            {"audio": str(bed), "role": "bed", "start-s": 0.0, "gain-db": -6.0},
        ],
        "ducking": True,
        "duck-db": -12.0,
        "target-lufs": -16.0,
    }
    result = _invoke(tmp_path, stub, _base_request(out, "ffmpeg.mix", inputs), "mix")
    properties = _properties(result)
    assert abs(float(properties["lufs"]) + 16.0) <= TOL
    assert float(properties["peak_dbfs"]) <= TP + MARGIN


def _clean_request(out: Path, audio: Path, name: str, **fields: object) -> dict[str, object]:
    inputs: dict[str, object] = {
        "audio": str(audio),
        "name": name,
        "channel": "auto",
        "target-lufs": -16.0,
        "true-peak-db": TP,
        "sample-rate-hz": "48000",
    }
    inputs.update(fields)
    return _base_request(out, "ffmpeg.clean", inputs)


def _right_only_stereo(tmp_path: Path) -> Path:
    """A mono mic recorded on the right side only: left silent, right voice plus hiss."""
    voice = _samples(_hot_voice())
    noise = _lcg(len(voice))
    left = [0.0] * len(voice)
    right = [0.5 * value + 0.002 * noise[index] for index, value in enumerate(voice)]
    source = tmp_path / "right-only.wav"
    _write_stereo(source, left, right)
    return source


def test_clean_pre_stage_keeps_mono_at_unity_gain(tmp_path: Path) -> None:
    """The mix channel is aformat, never a 0.5+0.5 pan: mono must not drop 6 dB."""
    source = tmp_path / "mono.wav"
    _write_wav(source, _sine(seconds=1.0, hz=300.0, amplitude=0.5))
    staged, right = _pre_stage(tmp_path, source, "mix")
    assert right is None, "the pre-stage wrote more than one channel for a mono source"
    source_left, _unused = _read_channels(source)
    assert abs(_level_db(staged) - _level_db(source_left)) < UNITY_TOL_DB


def test_clean_auto_extracts_the_right_channel_as_dual_mono(tmp_path: Path) -> None:
    source = _right_only_stereo(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    stub = _stub_dir(tmp_path)
    request = _clean_request(out, source, "voice-clean", channels="2")
    result = _invoke(tmp_path, stub, request, "clean-stereo")
    asset = result["assets"][0]
    properties = asset["properties"]
    assert asset["params"]["channel"] == "right", "auto detection missed the live channel"
    assert int(properties["channels"]) == STEREO_CHANNELS
    assert abs(float(properties["lufs"]) + 16.0) <= TOL
    assert float(properties["peak_dbfs"]) <= TP + MARGIN
    left, right = _read_channels(out / "voice-clean.wav")
    assert right is not None
    assert _level_db(left) > SILENT_SIDE_DB, "the left side is silent: wrong channel extracted"
    assert abs(_level_db(left) - _level_db(right)) < BALANCE_TOL_DB
    verify = {**request, "verb": "verify", "assets": [str(out / "voice-clean.wav")]}
    verdicts = _invoke(tmp_path, stub, verify, "clean-stereo-verify")["assets"]
    assert verdicts[0]["passed"] is True


def test_clean_defaults_to_centered_mono(tmp_path: Path) -> None:
    source = _right_only_stereo(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    stub = _stub_dir(tmp_path)
    request = _clean_request(out, source, "voice-mono")
    result = _invoke(tmp_path, stub, request, "clean-mono")
    properties = _properties(result)
    assert int(properties["channels"]) == MONO_CHANNELS
    assert int(properties["sample_rate_hz"]) == RATE
    assert abs(float(properties["lufs"]) + 16.0) <= TOL
    assert float(properties["peak_dbfs"]) <= TP + MARGIN
    verify = {**request, "verb": "verify", "assets": [str(out / "voice-mono.wav")]}
    verdicts = _invoke(tmp_path, stub, verify, "clean-mono-verify")["assets"]
    assert verdicts[0]["passed"] is True
