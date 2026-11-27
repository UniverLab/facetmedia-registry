"""The deepfilter run/verify/preview/doctor cycle, with no real DeepFilterNet.

The test stands in for the package environment: it runs ``runner.py`` as a
subprocess of the package environment's own python over a stub SDK, with the
registry's real ``lib/audiopreview.py`` copied in, so the measurements are
the real ones the runner reports. A stub ``deep-filter`` script stands in
for the pinned static binary: it records its argv (so ``-D``/``-a``/``--pf``
are proven, not assumed), answers ``--help`` like v0.5.6, copies the input
WAV to the out dir the way the real binary writes the enhanced file beside
the input name, and can be told to fail. No test touches the real binary.
"""

from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "deepfilter"
RUNNER = PACKAGE / "runner.py"
PYTHON = PACKAGE / ".venv" / "bin" / "python"
SCHEMA = json.loads((ROOT / "schemas" / "preview" / "audio.schema.json").read_text())
MODEL_ID = "deep-filter-0.5.6-linux-x86_64"
RATE = 48000
DURATION_TOL_S = 0.15
SUMMARY_MAX = 160
WAVEFORM_BINS = 1200
#: The voice fixture: four gated bursts with gaps.
VOICE_BURSTS = 4
BURST_S = 0.30
GAP_S = 0.15
VOICE_S = VOICE_BURSTS * (BURST_S + GAP_S)

pytestmark = pytest.mark.skipif(
    not PYTHON.exists(), reason="sync the package env with `uv sync --project packages/deepfilter`"
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

#: The stub binary the tests execute. ``__PYTHON__`` becomes the running
#: interpreter; STUB_DF_LOG / STUB_DF_FAIL / STUB_DF_RENAME steer its answers.
STUB_BINARY = """#!__PYTHON__
import os
import shutil
import sys
from pathlib import Path


def record(argv):
    log = os.environ.get("STUB_DF_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as stream:
            stream.write(" ".join(argv) + "\\n")


def main(argv):
    record(argv)
    if argv[:1] == ["--help"]:
        if os.environ.get("STUB_DF_HELP_FAIL") == "1":
            print("stub deep-filter: broken usage", file=sys.stderr)
            return 2
        print("usage: deep-filter [-D] [-a ATTEN_LIM_DB] [--pf] [-o OUT_DIR] <wav>")
        print("  -a, --atten-lim-db <ATTEN_LIM_DB>")
        return 0
    if os.environ.get("STUB_DF_FAIL") == "1":
        print("stub deep-filter: the neural net exploded", file=sys.stderr)
        return 3
    out_dir = Path(argv[argv.index("-o") + 1])
    source = Path(argv[-1])
    if os.environ.get("STUB_DF_RENAME") == "1":
        shutil.copy(source, out_dir / "enhanced-output.wav")
    else:
        shutil.copy(source, out_dir / source.name)
    return 0


raise SystemExit(main(sys.argv[1:]))
"""


def _lcg(count: int) -> list[float]:
    """A deterministic white-noise floor in [-1, 1]."""
    state = 12345
    values: list[float] = []
    for _ in range(count):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        values.append(state / 0x3FFFFFFF - 1.0)
    return values


def _voice() -> bytes:
    """Gated speech-like bursts with a noise floor, 16-bit PCM at 48 kHz."""
    burst = int(BURST_S * RATE)
    gap = int(GAP_S * RATE)
    total = VOICE_BURSTS * (burst + gap)
    noise = _lcg(total)
    samples = [0.0] * total
    for index in range(4):
        base = index * (burst + gap)
        for i in range(burst):
            t = i / RATE
            env = math.sin(math.pi * i / burst) ** 0.4
            phase = 2 * math.pi * (140.0 + 18.0 * math.sin(2 * math.pi * 2.3 * t)) * t
            samples[base + i] = env * (
                0.45 * math.sin(phase) + 0.22 * math.sin(2 * phase) + 0.05 * noise[base + i]
            )
    peak = max(abs(x) for x in samples)
    fitted = [x * (0.5 / peak) for x in samples]
    return b"".join(struct.pack("<h", round(x * 32767)) for x in fitted)


def _write_wav(path: Path, payload: bytes, channels: int = 1, rate: int = RATE) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(payload)


def _write_stereo(path: Path, left: bytes, right: bytes) -> None:
    first = struct.iter_unpack("<h", left)
    second = struct.iter_unpack("<h", right)
    interleaved = b"".join(
        struct.pack("<hh", a[0], b[0]) for a, b in zip(first, second, strict=True)
    )
    _write_wav(path, interleaved, channels=2)


def _silent(seconds: float = 1.0) -> bytes:
    return b"\x00\x00" * int(seconds * RATE)


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


def _binary(tmp_path: Path, executable: bool = True) -> Path:
    """The stub deep-filter binary under a fake models dir."""
    binary = tmp_path / "deep-filter"
    binary.write_text(STUB_BINARY.replace("__PYTHON__", sys.executable), encoding="utf-8")
    if executable:
        binary.chmod(0o755)
    return binary


def _base_request(
    out: Path, binary: Path, audio: Path, name: str, **fields: object
) -> dict[str, object]:
    inputs: dict[str, object] = {"audio": str(audio), "name": name, **fields}
    return {
        "protocol": 1,
        "verb": "run",
        "capability": "deepfilter.enhance",
        "depth": "quick",
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(out),
        "models": {MODEL_ID: str(binary)},
        "assets": [],
    }


def _invoke(
    tmp_path: Path,
    stub: Path,
    request: dict[str, object],
    tag: str,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    request_path = tmp_path / f"{tag}-request.json"
    result_path = tmp_path / f"{tag}-result.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    environ = {**os.environ, "PYTHONPATH": str(stub)}
    if env:
        environ.update(env)
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
        env=environ,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(result_path.read_text(encoding="utf-8"))


def _setup(tmp_path: Path, **fields: object) -> tuple[Path, Path, Path, Path]:
    """A noisy source, an out dir, the stub dir and the stub binary."""
    source = tmp_path / "take.wav"
    _write_wav(source, _voice())
    out = tmp_path / "out"
    out.mkdir()
    return source, out, _stub_dir(tmp_path), _binary(tmp_path)


def _argv(tmp_path: Path) -> list[str]:
    log = tmp_path / "argv.log"
    assert log.is_file()
    return log.read_text(encoding="utf-8").strip().splitlines()[-1].split(" ")


def _properties(result: dict[str, object]) -> dict[str, object]:
    assets = result["assets"]
    assert isinstance(assets, list) and assets
    properties = assets[0]["properties"]
    assert isinstance(properties, dict)
    return properties


def test_run_writes_the_enhanced_wav_with_the_tool_argv(tmp_path: Path) -> None:
    source, out, stub, binary = _setup(tmp_path)
    log = tmp_path / "argv.log"
    log.write_text("", encoding="utf-8")
    result = _invoke(
        tmp_path,
        stub,
        _base_request(out, binary, source, "take-clean"),
        "run",
        {"STUB_DF_LOG": str(log)},
    )
    assets = result["assets"]
    assert isinstance(assets, list) and len(assets) == 1
    asset = assets[0]
    assert asset["file"] == "take-clean.wav"
    assert asset["kind"] == "audio"
    assert asset["mime"] == "audio/wav"
    assert (out / "take-clean.wav").is_file()
    argv = _argv(tmp_path)
    assert argv[0:3] == ["-D", "-a", "100.0"]
    assert "--pf" in argv
    assert "-o" in argv and argv[-1].endswith(".in.wav")
    properties = _properties(result)
    assert int(properties["sample_rate_hz"]) == RATE
    assert abs(float(properties["duration_s"]) - VOICE_S) <= DURATION_TOL_S


def test_run_honours_attenuation_and_no_post_filter(tmp_path: Path) -> None:
    source, out, stub, binary = _setup(tmp_path)
    log = tmp_path / "argv.log"
    log.write_text("", encoding="utf-8")
    _invoke(
        tmp_path,
        stub,
        _base_request(
            out, binary, source, "take-soft", **{"atten-lim-db": 50.0, "post-filter": False}
        ),
        "run-atten",
        {"STUB_DF_LOG": str(log)},
    )
    argv = _argv(tmp_path)
    assert "-a" in argv and argv[argv.index("-a") + 1] == "50.0"
    assert "--pf" not in argv


def test_run_makes_a_non_executable_binary_executable(tmp_path: Path) -> None:
    source = tmp_path / "take.wav"
    _write_wav(source, _voice())
    out = tmp_path / "out"
    out.mkdir()
    stub = _stub_dir(tmp_path)
    binary = _binary(tmp_path, executable=False)
    assert not os.access(binary, os.X_OK)
    _invoke(tmp_path, stub, _base_request(out, binary, source, "take-clean"), "run-chmod")
    assert os.access(binary, os.X_OK)
    assert (out / "take-clean.wav").is_file()


def test_run_takes_the_single_wav_when_the_name_differs(tmp_path: Path) -> None:
    source, out, stub, binary = _setup(tmp_path)
    result = _invoke(
        tmp_path,
        stub,
        _base_request(out, binary, source, "take-clean"),
        "run-rename",
        {"STUB_DF_RENAME": "1"},
    )
    assert result["assets"][0]["file"] == "take-clean.wav"
    assert (out / "take-clean.wav").is_file()


def test_run_auto_picks_the_live_side_of_stereo(tmp_path: Path) -> None:
    voice = _voice()
    silent = _silent(seconds=len(voice) / 2 / RATE)
    assert len(voice) == len(silent)
    source = tmp_path / "stereo.wav"
    _write_stereo(source, voice, silent)
    out = tmp_path / "out"
    out.mkdir()
    stub = _stub_dir(tmp_path)
    binary = _binary(tmp_path)
    result = _invoke(
        tmp_path, stub, _base_request(out, binary, source, "stereo-clean"), "run-stereo"
    )
    assert result["assets"][0]["params"]["channel"] == "left"
    assert int(_properties(result)["channels"]) == 1


def test_run_reports_the_tool_failure(tmp_path: Path) -> None:
    source, out, stub, binary = _setup(tmp_path)
    request_path = tmp_path / "fail-request.json"
    result_path = tmp_path / "fail-result.json"
    request = _base_request(out, binary, source, "take-clean")
    request_path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run(
        [
            str(PYTHON),
            str(RUNNER),
            "run",
            "--input",
            str(request_path),
            "--result",
            str(result_path),
        ],
        env={**os.environ, "PYTHONPATH": str(stub), "STUB_DF_FAIL": "1"},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode != 0
    assert "deep-filter exited 3" in (done.stderr + done.stdout)


def test_run_then_verify_passes(tmp_path: Path) -> None:
    source, out, stub, binary = _setup(tmp_path)
    request = _base_request(out, binary, source, "take-clean")
    _invoke(tmp_path, stub, request, "verify-run")
    verify = {**request, "verb": "verify", "assets": [str(out / "take-clean.wav")]}
    result = _invoke(tmp_path, stub, verify, "verify-check")
    verdicts = result["assets"]
    assert isinstance(verdicts, list) and verdicts
    assert verdicts[0]["passed"] is True
    assert verdicts[0]["verifier"] == "deep-filter-0.5.6"


def test_verify_rejects_a_silent_output_when_the_source_has_signal(tmp_path: Path) -> None:
    source, out, stub, binary = _setup(tmp_path)
    request = _base_request(out, binary, source, "take-clean")
    _invoke(tmp_path, stub, request, "silent-run")
    silent = out / "take-clean.wav"
    _write_wav(silent, _silent(seconds=2.0))
    verify = {**request, "verb": "verify", "assets": [str(silent)]}
    result = _invoke(tmp_path, stub, verify, "silent-check")
    assert result["assets"][0]["passed"] is False
    assert "silent" in result["assets"][0]["metrics"]["error"]


def test_verify_rejects_a_resampled_output(tmp_path: Path) -> None:
    source, out, stub, binary = _setup(tmp_path)
    request = _base_request(out, binary, source, "take-clean")
    _invoke(tmp_path, stub, request, "rate-run")
    resampled = out / "take-clean.wav"
    _write_wav(resampled, _voice(), rate=16000)
    verify = {**request, "verb": "verify", "assets": [str(resampled)]}
    result = _invoke(tmp_path, stub, verify, "rate-check")
    assert result["assets"][0]["passed"] is False


def test_preview_matches_the_audio_schema(tmp_path: Path) -> None:
    source, out, stub, binary = _setup(tmp_path)
    request = _base_request(out, binary, source, "take-clean")
    _invoke(tmp_path, stub, request, "preview-run")
    result = _invoke(
        tmp_path,
        stub,
        {**request, "verb": "preview", "assets": [str(out / "take-clean.wav")]},
        "preview-check",
    )
    entries = result["assets"]
    assert isinstance(entries, list) and entries
    assert entries[0]["preview"] == "take-clean.wav.preview.json"
    preview = json.loads((out / entries[0]["preview"]).read_text(encoding="utf-8"))
    for key in SCHEMA["required"]:
        assert key in preview, key
    assert preview["preview"] == 1
    assert preview["kind"] == "audio"
    assert len(preview["summary"]) <= SUMMARY_MAX
    assert preview["waveform"]["bins"] == WAVEFORM_BINS


def test_doctor_quick_checks_the_binary_and_the_imports(tmp_path: Path) -> None:
    _source, out, stub, binary = _setup(tmp_path)
    request = _base_request(out, binary, tmp_path / "take.wav", "take-clean")
    result = _invoke(tmp_path, stub, {**request, "verb": "doctor"}, "doctor-quick")
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["binary"]["ok"] is True
    assert checks["imports"]["ok"] is True


def test_doctor_quick_names_the_pull_when_the_binary_is_missing(tmp_path: Path) -> None:
    _source, out, stub, _binary_path = _setup(tmp_path)
    request = _base_request(out, tmp_path / "absent" / "deep-filter", tmp_path / "take.wav", "x")
    result = _invoke(tmp_path, stub, {**request, "verb": "doctor"}, "doctor-missing")
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["binary"]["ok"] is False
    assert checks["binary"]["fix"] == "facet pull deepfilter"


def test_doctor_quick_fails_when_help_exits_nonzero(tmp_path: Path) -> None:
    _source, out, stub, binary = _setup(tmp_path)
    request = _base_request(out, binary, tmp_path / "take.wav", "take-clean")
    result = _invoke(
        tmp_path,
        stub,
        {**request, "verb": "doctor"},
        "doctor-help-fail",
        {"STUB_DF_HELP_FAIL": "1"},
    )
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["binary"]["ok"] is False
    assert checks["binary"]["fix"] == "facet pull deepfilter"


def test_doctor_full_enhances_a_noisy_clip(tmp_path: Path) -> None:
    source, out, stub, binary = _setup(tmp_path)
    request = _base_request(out, binary, source, "take-clean")
    result = _invoke(tmp_path, stub, {**request, "verb": "doctor", "depth": "full"}, "doctor-full")
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["roundtrip"]["ok"] is True
