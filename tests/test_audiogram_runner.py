"""The audiogram runner against the package environment, no display, no GPU.

The runner is a subprocess of the package's own python (pinned NumPy,
soundfile, Pillow and imageio-ffmpeg). Its ``PYTHONPATH`` carries a
stub ``facet_runner_sdk`` (the pull-time SDK surface), so the tests
prove the run writes an MP4 per style and aspect, verify accepts a live
render and refuses wrong canvases and static renders, the previews
match the video schema, and the doctor checks pass.
"""

from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any

import PIL.Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
SQUARE = 1080
WIDE_WIDTH = 1280
WIDE_HEIGHT = 720
FPS = 12
PACKAGE = ROOT / "packages" / "audiogram"
RUNNER = PACKAGE / "runner.py"
PYTHON = PACKAGE / ".venv" / "bin" / "python"
VIDEO_SCHEMA: dict[str, Any] = json.loads(
    (ROOT / "schemas" / "preview" / "video.schema.json").read_text(encoding="utf-8")
)
PREVIEW_FIELDS = set(VIDEO_SCHEMA["required"])
FIXTURE = PACKAGE / "examples" / "fixture.wav"

pytestmark = pytest.mark.skipif(
    not PYTHON.exists(), reason="sync the package env with `uv sync --project packages/audiogram`"
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


def _stub_dir(tmp_path: Path) -> Path:
    """A directory holding the stub SDK, for PYTHONPATH."""
    folder = tmp_path / "stub-modules"
    folder.mkdir(exist_ok=True)
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    return folder


def _wav(path: Path, seconds: float, hz: float, tremolo_hz: float) -> None:
    """A mono 16-bit tone with a slow tremolo, so frames visibly react."""
    rate = 44100
    count = int(seconds * rate)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for index in range(count):
            tick = index / rate
            envelope = 0.5 + 0.5 * math.sin(2 * math.pi * tremolo_hz * tick)
            sample = int(16000 * envelope * math.sin(2 * math.pi * hz * tick))
            frames += struct.pack("<h", sample)
        handle.writeframes(bytes(frames))


def _inputs(**overrides: Any) -> dict[str, Any]:
    """A valid bars piece; callers override what they probe."""
    base: dict[str, Any] = {"audio": "tone.wav", "name": "card", "style": "bars"}
    base.update(overrides)
    return base


def _request(
    verb: str,
    out_dir: Path,
    piece_dir: Path,
    inputs: dict[str, Any],
    assets: tuple[Path, ...] = (),
    depth: str = "quick",
) -> dict[str, Any]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "audiogram.render",
        "depth": depth,
        "inputs": inputs,
        "out_dir": str(out_dir),
        "piece_dir": str(piece_dir),
        "models": {},
        "assets": [str(path) for path in assets],
    }


def _call(
    stub_dir: Path,
    verb: str,
    request: dict[str, Any],
    tmp_path: Path,
    tag: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    input_path = tmp_path / f"{tag}-{verb}-request.json"
    result_path = tmp_path / f"{tag}-{verb}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    result_path.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONPATH": str(stub_dir)}
    done = subprocess.run(
        [str(PYTHON), str(RUNNER), verb, "--input", str(input_path), "--result", str(result_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    return done, result


def _piece(tmp_path: Path, tag: str, seconds: float = 1.0) -> Path:
    """A piece dir holding a reactive tone."""
    piece = tmp_path / f"piece-{tag}"
    piece.mkdir(exist_ok=True)
    _wav(piece / "tone.wav", seconds, 440.0, 2.0)
    return piece


def _run(
    tmp_path: Path, inputs: dict[str, Any], tag: str, seconds: float = 1.0
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, Path]:
    """One ``run`` against a fresh piece and out dir."""
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path, tag, seconds)
    out = tmp_path / f"out-{tag}"
    out.mkdir()
    request = _request("run", out, piece, inputs)
    done, result = _call(stub_dir, "run", request, tmp_path, tag)
    return done, result, out


def _verify(
    tmp_path: Path,
    stub_dir: Path,
    out: Path,
    piece: Path,
    inputs: dict[str, Any],
    asset: str,
    tag: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    request = _request("verify", out, piece, inputs, assets=(out / asset,))
    return _call(stub_dir, "verify", request, tmp_path, f"{tag}-verify")


def test_run_writes_a_square_bars_mp4(tmp_path: Path) -> None:
    done, result, out = _run(tmp_path, _inputs(fps=12), "bars-square")
    assert done.returncode == 0, done.stderr
    assert result is not None
    assert result["tool"] == {"name": "Audiogram", "version": "0.1.0"}
    assert [asset["file"] for asset in result["assets"]] == ["card.mp4"]
    asset = result["assets"][0]
    assert asset["kind"] == "video"
    assert asset["mime"] == "video/mp4"
    assert asset["seed"] == 0
    assert (out / "card.mp4").stat().st_size > 0


def test_run_renders_waveform_and_widescreen(tmp_path: Path) -> None:
    done, result, out = _run(
        tmp_path, _inputs(style="waveform", aspect="16:9", title="Hello", fps=12), "wave-wide"
    )
    assert done.returncode == 0, done.stderr
    assert result is not None
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / "piece-wave-wide"
    preview_request = _request(
        "preview",
        out,
        piece,
        _inputs(style="waveform", aspect="16:9", title="Hello", fps=12),
        assets=(out / "card.mp4",),
    )
    done, preview = _call(stub_dir, "preview", preview_request, tmp_path, "wave-wide")
    assert done.returncode == 0, done.stderr
    assert preview is not None
    data = json.loads((out / "card.mp4.preview.json").read_text(encoding="utf-8"))
    assert data["width"] == WIDE_WIDTH
    assert data["height"] == WIDE_HEIGHT
    assert data["fps"] == FPS


def test_run_covers_a_backdrop_image(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path, "cover")
    cover = piece / "cover.png"
    PIL.Image.new("RGB", (64, 64), (200, 30, 30)).save(cover)
    out = tmp_path / "out-cover"
    out.mkdir()
    inputs = _inputs(cover="cover.png", title="Cover", fps=12)
    request = _request("run", out, piece, inputs)
    done, result = _call(stub_dir, "run", request, tmp_path, "cover")
    assert done.returncode == 0, done.stderr
    assert result is not None
    assert [asset["file"] for asset in result["assets"]] == ["card.mp4"]


def test_run_refuses_a_missing_clip(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / "piece-missing"
    piece.mkdir()
    out = tmp_path / "out-missing"
    out.mkdir()
    request = _request("run", out, piece, _inputs())
    done, _result = _call(stub_dir, "run", request, tmp_path, "missing")
    assert done.returncode != 0


def test_run_refuses_a_bad_color(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path, "bad-color")
    out = tmp_path / "out-bad-color"
    out.mkdir()
    request = _request("run", out, piece, _inputs(background="red"))
    done, _result = _call(stub_dir, "run", request, tmp_path, "bad-color")
    assert done.returncode != 0


def test_verify_accepts_a_live_render(tmp_path: Path) -> None:
    done, result, out = _run(tmp_path, _inputs(fps=12), "verify-ok")
    assert done.returncode == 0, done.stderr
    assert result is not None
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / "piece-verify-ok"
    done, verdict = _verify(tmp_path, stub_dir, out, piece, _inputs(fps=12), "card.mp4", "ok")
    assert done.returncode == 0, done.stderr
    assert verdict is not None
    (entry,) = verdict["assets"]
    assert entry["file"] == "card.mp4"
    assert entry["passed"] is True
    assert entry["metrics"]["width"] == SQUARE
    assert entry["metrics"]["height"] == SQUARE
    assert entry["metrics"]["audio_codec"]


def test_verify_rejects_a_wrong_canvas(tmp_path: Path) -> None:
    done, result, out = _run(tmp_path, _inputs(fps=12), "verify-canvas")
    assert done.returncode == 0, done.stderr
    assert result is not None
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / "piece-verify-canvas"
    wrong = _inputs(aspect="9:16", fps=12)
    done, verdict = _verify(tmp_path, stub_dir, out, piece, wrong, "card.mp4", "canvas")
    assert done.returncode == 0, done.stderr
    assert verdict is not None
    (entry,) = verdict["assets"]
    assert entry["passed"] is False


def _silence(path: Path, seconds: float) -> None:
    """A mono 16-bit silent clip: nothing to react to, every frame identical."""
    rate = 44100
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00" * int(seconds * rate) * 2)


def test_verify_rejects_a_static_render(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / "piece-static"
    piece.mkdir(exist_ok=True)
    _silence(piece / "tone.wav", 1.0)
    out = tmp_path / "out-static"
    out.mkdir()
    inputs = _inputs(fps=12)
    request = _request("run", out, piece, inputs)
    done, result = _call(stub_dir, "run", request, tmp_path, "static")
    assert done.returncode == 0, done.stderr
    assert result is not None
    done, verdict = _verify(tmp_path, stub_dir, out, piece, inputs, "card.mp4", "static")
    assert done.returncode == 0, done.stderr
    assert verdict is not None
    (entry,) = verdict["assets"]
    assert entry["passed"] is False
    assert entry["metrics"]["motion"] == 0.0


def test_preview_matches_the_video_schema(tmp_path: Path) -> None:
    done, result, out = _run(tmp_path, _inputs(fps=12), "preview")
    assert done.returncode == 0, done.stderr
    assert result is not None
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / "piece-preview"
    inputs = _inputs(fps=12)
    request = _request("preview", out, piece, inputs, assets=(out / "card.mp4",))
    done, preview = _call(stub_dir, "preview", request, tmp_path, "preview")
    assert done.returncode == 0, done.stderr
    assert preview is not None
    data = json.loads((out / "card.mp4.preview.json").read_text(encoding="utf-8"))
    assert set(data) == PREVIEW_FIELDS
    assert data["kind"] == "video"
    assert data["name"] == "card"
    assert data["prompt"] == "render video card"
    assert data["seed"] == 0
    assert (data["width"], data["height"]) == (1080, 1080)
    assert data["length"] == data["fps"]


def test_doctor_quick_checks_the_environment(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    out = tmp_path / "out-doctor"
    out.mkdir()
    piece = _piece(tmp_path, "doctor")
    request = _request("doctor", out, piece, {}, depth="quick")
    done, result = _call(stub_dir, "doctor", request, tmp_path, "doctor-quick")
    assert done.returncode == 0, done.stderr
    assert result is not None
    (check,) = result["checks"]
    assert check["name"] == "imports"
    assert check["ok"] is True


def test_doctor_full_renders_a_sine_audiogram(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    out = tmp_path / "out-doctor-full"
    out.mkdir()
    piece = _piece(tmp_path, "doctor-full")
    request = _request("doctor", out, piece, {}, depth="full")
    done, result = _call(stub_dir, "doctor", request, tmp_path, "doctor-full")
    assert done.returncode == 0, done.stderr
    assert result is not None
    assert [check["name"] for check in result["checks"]] == ["imports", "render"]
    assert all(check["ok"] for check in result["checks"])


def test_the_bundled_fixture_renders_and_verifies(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / "piece-fixture"
    piece.mkdir(exist_ok=True)
    (piece / "fixture.wav").write_bytes(FIXTURE.read_bytes())
    out = tmp_path / "out-fixture"
    out.mkdir()
    inputs = {"audio": "fixture.wav", "name": "fixture-card", "style": "bars"}
    request = _request("run", out, piece, inputs)
    done, result = _call(stub_dir, "run", request, tmp_path, "fixture")
    assert done.returncode == 0, done.stderr
    assert result is not None
    done, verdict = _verify(tmp_path, stub_dir, out, piece, inputs, "fixture-card.mp4", "fixture")
    assert done.returncode == 0, done.stderr
    assert verdict is not None
    (entry,) = verdict["assets"]
    assert entry["passed"] is True
