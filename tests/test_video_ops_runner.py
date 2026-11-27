"""End-to-end runner tests for packages/video-ops using real imageio-ffmpeg and Pillow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "video-ops"
RUNNER = PACKAGE / "runner.py"
EXAMPLES = PACKAGE / "examples"
FIXTURE_MP4 = EXAMPLES / "fixture.mp4"
FIXTURE_WAV = EXAMPLES / "fixture.wav"

VIDEO_PREVIEW_KEYS = {
    "preview",
    "kind",
    "summary",
    "name",
    "prompt",
    "seed",
    "width",
    "height",
    "length",
    "fps",
}
IMAGE_PREVIEW_KEYS = {
    "preview",
    "kind",
    "summary",
    "name",
    "prompt",
    "seed",
    "width",
    "height",
}
DOWNSCALED_WIDTH = 160
FIXTURE_HEIGHT = 120
TRIM_DURATION_S = 0.5
DURATION_TOL_S = 0.25
REFRAME_WIDTH = 1080
REFRAME_HEIGHT_9_16 = 1920
REFRAME_SQUARE = 720

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

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text()))


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


def _invoke(
    tmp_path: Path,
    verb: str,
    *,
    capability: str = "",
    inputs: dict[str, Any] | None = None,
    assets: list[Path] | None = None,
    depth: str = "quick",
) -> dict[str, Any]:
    sdk_dir = tmp_path / "sdk"
    sdk_dir.mkdir(exist_ok=True)
    (sdk_dir / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir(exist_ok=True)
    req_file = tmp_path / f"{verb}_input.json"
    res_file = tmp_path / f"{verb}_result.json"
    req_file.write_text(
        json.dumps(
            {
                "verb": verb,
                "capability": capability,
                "depth": depth,
                "inputs": inputs or {},
                "out_dir": str(out_dir),
                "piece_dir": str(EXAMPLES),
                "assets": [str(p) for p in (assets or [])],
            }
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(sdk_dir)
    proc = subprocess.run(
        [sys.executable, str(RUNNER), verb, "--input", str(req_file), "--result", str(res_file)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, f"runner failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return json.loads(res_file.read_text(encoding="utf-8"))


def test_transcode_run_verify_and_preview(tmp_path: Path) -> None:
    inputs = {
        "video": FIXTURE_MP4.name,
        "name": "out-clip",
        "crf": 26,
        "max-width": 240,
        "fps": 20,
        "start-s": 0.0,
        "end-s": TRIM_DURATION_S,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.transcode", inputs=inputs)
    asset = run_res["assets"][0]
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()
    # max-width=240 must not upscale a 160px-wide fixture
    assert asset["properties"]["width"] == DOWNSCALED_WIDTH
    assert asset["properties"]["height"] == FIXTURE_HEIGHT
    assert abs(asset["properties"]["duration_s"] - TRIM_DURATION_S) <= DURATION_TOL_S

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.transcode", inputs=inputs, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is True

    prev_res = _invoke(
        tmp_path, "preview", capability="video-ops.transcode", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == VIDEO_PREVIEW_KEYS
    assert preview_data["kind"] == "video"
    assert preview_data["width"] == DOWNSCALED_WIDTH
    assert preview_data["length"] >= 1
    assert preview_data["fps"] >= 1


def test_mux_audio_run_verify_and_preview(tmp_path: Path) -> None:
    inputs = {
        "video": FIXTURE_MP4.name,
        "audio": FIXTURE_WAV.name,
        "name": "muxed-clip",
        "audio-bitrate-kbps": 128,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.mux-audio", inputs=inputs)
    out_file = tmp_path / "out" / run_res["assets"][0]["file"]
    assert out_file.is_file()
    assert run_res["assets"][0]["properties"]["audio_codec"] == "aac"

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.mux-audio", inputs=inputs, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is True

    prev_res = _invoke(
        tmp_path, "preview", capability="video-ops.mux-audio", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == VIDEO_PREVIEW_KEYS
    assert preview_data["kind"] == "video"
    assert preview_data["length"] >= 1
    assert preview_data["fps"] >= 1


def test_frame_run_verify_and_preview(tmp_path: Path) -> None:
    inputs = {"video": FIXTURE_MP4.name, "name": "thumb", "at-s": 0.2, "format": "png"}
    run_res = _invoke(tmp_path, "run", capability="video-ops.frame", inputs=inputs)
    asset = run_res["assets"][0]
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()
    assert asset["properties"]["width"] == DOWNSCALED_WIDTH
    assert asset["properties"]["height"] == FIXTURE_HEIGHT

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.frame", inputs=inputs, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is True

    prev_res = _invoke(
        tmp_path, "preview", capability="video-ops.frame", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == IMAGE_PREVIEW_KEYS
    assert preview_data["kind"] == "image"
    assert preview_data["width"] == DOWNSCALED_WIDTH
    assert preview_data["height"] == FIXTURE_HEIGHT


def test_verify_reports_failed_on_corrupt_or_missing_assets(tmp_path: Path) -> None:
    bad_mp4 = tmp_path / "bad.mp4"
    bad_mp4.write_bytes(b"not a video")
    bad_png = tmp_path / "bad.png"
    bad_png.write_bytes(b"not an image")

    ver_vid = _invoke(tmp_path, "verify", capability="video-ops.transcode", assets=[bad_mp4])
    assert ver_vid["assets"][0]["passed"] is False

    ver_img = _invoke(tmp_path, "verify", capability="video-ops.frame", assets=[bad_png])
    assert ver_img["assets"][0]["passed"] is False


def test_mux_audio_verify_fails_on_video_without_audio(tmp_path: Path) -> None:
    silent_mp4 = tmp_path / "silent.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-nostdin",
            "-hide_banner",
            "-y",
            "-i",
            str(FIXTURE_MP4),
            "-c:v",
            "copy",
            "-an",
            str(silent_mp4),
        ],
        capture_output=True,
        check=True,
    )
    ver_transcode = _invoke(
        tmp_path, "verify", capability="video-ops.transcode", assets=[silent_mp4]
    )
    assert ver_transcode["assets"][0]["passed"] is True

    ver_mux = _invoke(tmp_path, "verify", capability="video-ops.mux-audio", assets=[silent_mp4])
    assert ver_mux["assets"][0]["passed"] is False
    assert ver_mux["assets"][0]["metrics"]["audio_codec"] is None


def test_frame_jpg_run_and_verify(tmp_path: Path) -> None:
    inputs = {"video": FIXTURE_MP4.name, "name": "thumb-jpg", "at-s": 0.0, "format": "jpg"}
    run_res = _invoke(tmp_path, "run", capability="video-ops.frame", inputs=inputs)
    asset = run_res["assets"][0]
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.name == "thumb-jpg.jpg"
    assert out_file.is_file()
    assert asset["mime"] == "image/jpeg"

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.frame", inputs=inputs, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is True


def test_doctor_quick_and_full(tmp_path: Path) -> None:
    quick = _invoke(tmp_path, "doctor", depth="quick")
    assert [c["name"] for c in quick["checks"]] == ["binary", "encoders", "imports"]
    assert all(c["ok"] for c in quick["checks"]), quick

    full = _invoke(tmp_path, "doctor", depth="full")
    assert [c["name"] for c in full["checks"]] == ["binary", "encoders", "imports", "roundtrip"]
    assert all(c["ok"] for c in full["checks"]), full


def test_concat_run_verify_and_preview(tmp_path: Path) -> None:
    inputs = {
        "clip": [{"video": FIXTURE_MP4.name}, {"video": FIXTURE_MP4.name}],
        "name": "joined",
        "transition": "fade",
        "transition-s": 0.5,
        "fps": 30,
        "crf": 23,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.concat", inputs=inputs)
    asset = run_res["assets"][0]
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()
    assert asset["kind"] == "video"
    assert asset["properties"]["width"] == DOWNSCALED_WIDTH
    assert asset["properties"]["height"] == FIXTURE_HEIGHT

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.concat", inputs=inputs, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is True, ver_res

    prev_res = _invoke(
        tmp_path, "preview", capability="video-ops.concat", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == VIDEO_PREVIEW_KEYS
    assert preview_data["kind"] == "video"
    assert preview_data["width"] == DOWNSCALED_WIDTH
    assert preview_data["height"] == FIXTURE_HEIGHT


def test_concat_cut_verify(tmp_path: Path) -> None:
    inputs = {
        "clip": [{"video": FIXTURE_MP4.name}, {"video": FIXTURE_MP4.name}],
        "name": "cut-join",
        "transition": "cut",
        "fps": 30,
        "crf": 23,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.concat", inputs=inputs)
    out_file = tmp_path / "out" / run_res["assets"][0]["file"]
    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.concat", inputs=inputs, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is True, ver_res


def test_burn_subs_run_verify_and_preview(tmp_path: Path) -> None:
    inputs = {
        "video": FIXTURE_MP4.name,
        "subtitles": "sample.srt",
        "name": "subs-out",
        "font-size": 22,
        "margin-v": 36,
        "crf": 23,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.burn-subs", inputs=inputs)
    asset = run_res["assets"][0]
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()
    assert asset["kind"] == "video"

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.burn-subs", inputs=inputs, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is True, ver_res

    prev_res = _invoke(
        tmp_path, "preview", capability="video-ops.burn-subs", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == VIDEO_PREVIEW_KEYS
    assert preview_data["kind"] == "video"


def test_grade_run_verify_and_preview(tmp_path: Path) -> None:
    inputs = {
        "video": FIXTURE_MP4.name,
        "name": "graded-out",
        "brightness": 0.05,
        "contrast": 1.1,
        "saturation": 1.2,
        "gamma": 1.0,
        "fade-in-s": 0.2,
        "fade-out-s": 0.2,
        "crf": 23,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.grade", inputs=inputs)
    asset = run_res["assets"][0]
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()
    assert asset["kind"] == "video"

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.grade", inputs=inputs, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is True, ver_res

    prev_res = _invoke(
        tmp_path, "preview", capability="video-ops.grade", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == VIDEO_PREVIEW_KEYS
    assert preview_data["kind"] == "video"


def test_new_caps_verify_fail_on_corrupt_assets(tmp_path: Path) -> None:
    bad_mp4 = tmp_path / "bad.mp4"
    bad_mp4.write_bytes(b"not a video")
    concat_inputs = {
        "clip": [{"video": FIXTURE_MP4.name}, {"video": FIXTURE_MP4.name}],
        "name": "x",
        "transition": "fade",
        "transition-s": 0.5,
    }
    for cap, inputs in [
        ("video-ops.concat", concat_inputs),
        (
            "video-ops.burn-subs",
            {"video": FIXTURE_MP4.name, "subtitles": "sample.srt", "name": "x"},
        ),
        ("video-ops.grade", {"video": FIXTURE_MP4.name, "name": "x"}),
        (
            "video-ops.overlay",
            {"base": FIXTURE_MP4.name, "overlay": "logo.png", "name": "x"},
        ),
        ("video-ops.speed", {"video": FIXTURE_MP4.name, "name": "x", "factor": 2.0}),
        (
            "video-ops.reframe",
            {"video": FIXTURE_MP4.name, "name": "x", "aspect": "9:16"},
        ),
        ("video-ops.jumpcut", {"video": FIXTURE_MP4.name, "name": "x"}),
        ("video-ops.fx", {"video": FIXTURE_MP4.name, "name": "x", "preset": "film"}),
    ]:
        res = _invoke(tmp_path, "verify", capability=cap, inputs=inputs, assets=[bad_mp4])
        assert res["assets"][0]["passed"] is False, (cap, res)


def test_overlay_run_verify_and_preview(tmp_path: Path) -> None:
    inputs = {
        "base": FIXTURE_MP4.name,
        "overlay": "logo.png",
        "name": "overlay-out",
        "position": "center",
        "crf": 23,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.overlay", inputs=inputs)
    asset = run_res["assets"][0]
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()
    assert asset["kind"] == "video"

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.overlay", inputs=inputs, assets=[out_file]
    )
    entry = ver_res["assets"][0]
    assert entry["passed"] is True, ver_res
    assert entry["metrics"]["width"] == DOWNSCALED_WIDTH
    assert entry["metrics"]["height"] == FIXTURE_HEIGHT
    assert abs(entry["metrics"]["duration_s"] - 1.0) <= DURATION_TOL_S

    prev_res = _invoke(
        tmp_path, "preview", capability="video-ops.overlay", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == VIDEO_PREVIEW_KEYS
    assert preview_data["kind"] == "video"


def test_speed_run_verify_and_preview(tmp_path: Path) -> None:
    inputs = {
        "video": FIXTURE_MP4.name,
        "name": "speed-out",
        "factor": 2.0,
        "keep-audio": True,
        "crf": 23,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.speed", inputs=inputs)
    asset = run_res["assets"][0]
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()
    assert asset["kind"] == "video"

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.speed", inputs=inputs, assets=[out_file]
    )
    entry = ver_res["assets"][0]
    assert entry["passed"] is True, ver_res
    assert entry["metrics"]["width"] == DOWNSCALED_WIDTH
    assert entry["metrics"]["height"] == FIXTURE_HEIGHT
    assert abs(entry["metrics"]["duration_s"] - 1.0 / 2.0) <= DURATION_TOL_S
    assert entry["thresholds"]["duration_tolerance_s"] == DURATION_TOL_S

    prev_res = _invoke(
        tmp_path, "preview", capability="video-ops.speed", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == VIDEO_PREVIEW_KEYS
    assert preview_data["kind"] == "video"


def test_reframe_run_verify_and_preview(tmp_path: Path) -> None:
    inputs = {
        "video": FIXTURE_MP4.name,
        "name": "reframe-out",
        "aspect": "9:16",
        "mode": "crop",
        "width": 1080,
        "crf": 23,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.reframe", inputs=inputs)
    asset = run_res["assets"][0]
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()
    assert asset["kind"] == "video"

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.reframe", inputs=inputs, assets=[out_file]
    )
    entry = ver_res["assets"][0]
    assert entry["passed"] is True, ver_res
    assert entry["metrics"]["width"] == REFRAME_WIDTH
    assert entry["metrics"]["height"] == REFRAME_HEIGHT_9_16
    assert abs(entry["metrics"]["duration_s"] - 1.0) <= DURATION_TOL_S

    prev_res = _invoke(
        tmp_path, "preview", capability="video-ops.reframe", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == VIDEO_PREVIEW_KEYS
    assert preview_data["kind"] == "video"


def test_reframe_blur_pad_run_and_verify(tmp_path: Path) -> None:
    inputs = {
        "video": FIXTURE_MP4.name,
        "name": "reframe-pad-out",
        "aspect": "1:1",
        "mode": "blur-pad",
        "width": 720,
        "crf": 23,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.reframe", inputs=inputs)
    out_file = tmp_path / "out" / run_res["assets"][0]["file"]
    assert out_file.is_file()

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.reframe", inputs=inputs, assets=[out_file]
    )
    entry = ver_res["assets"][0]
    assert entry["passed"] is True, ver_res
    assert entry["metrics"]["width"] == REFRAME_SQUARE
    assert entry["metrics"]["height"] == REFRAME_SQUARE


def test_jumpcut_run_verify_and_preview(tmp_path: Path) -> None:
    inputs = {
        "video": FIXTURE_MP4.name,
        "name": "jumpcut-out",
        "threshold-db": -35.0,
        "min-silence-s": 0.6,
        "margin-s": 0.12,
        "crf": 23,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.jumpcut", inputs=inputs)
    assert len(run_res["assets"]) == 1
    asset = run_res["assets"][0]
    out_file = tmp_path / "out" / asset["file"]
    cuts_file = out_file.with_suffix(".cuts.json")
    assert out_file.is_file()
    assert cuts_file.is_file()
    assert asset["kind"] == "video"
    assert asset["properties"]["cuts_file"] == cuts_file.name

    cuts_data = json.loads(cuts_file.read_text(encoding="utf-8"))
    assert cuts_data["segments"]
    assert cuts_data["output_duration_s"] <= cuts_data["source_duration_s"]

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.jumpcut", inputs=inputs, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is True, ver_res

    cuts_file.unlink()
    bad_ver = _invoke(
        tmp_path, "verify", capability="video-ops.jumpcut", inputs=inputs, assets=[out_file]
    )
    assert bad_ver["assets"][0]["passed"] is False

    prev_res = _invoke(
        tmp_path, "preview", capability="video-ops.jumpcut", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == VIDEO_PREVIEW_KEYS


def test_fx_run_verify_and_preview(tmp_path: Path) -> None:
    inputs = {
        "video": FIXTURE_MP4.name,
        "name": "fx-out",
        "preset": "crt",
        "chroma-px": 3,
        "seed": 42,
        "crf": 23,
    }
    run_res = _invoke(tmp_path, "run", capability="video-ops.fx", inputs=inputs)
    asset = run_res["assets"][0]
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()
    assert asset["kind"] == "video"

    ver_res = _invoke(
        tmp_path, "verify", capability="video-ops.fx", inputs=inputs, assets=[out_file]
    )
    entry = ver_res["assets"][0]
    assert entry["passed"] is True, ver_res
    assert entry["metrics"]["width"] == DOWNSCALED_WIDTH
    assert entry["metrics"]["height"] == FIXTURE_HEIGHT
    assert abs(entry["metrics"]["duration_s"] - 1.0) <= DURATION_TOL_S

    prev_res = _invoke(
        tmp_path, "preview", capability="video-ops.fx", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == VIDEO_PREVIEW_KEYS
