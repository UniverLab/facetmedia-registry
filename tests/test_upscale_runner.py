"""The upscale runner tested against a stub SDK and a fake ncnn binary zip."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "packages" / "upscale" / "runner.py"
MODEL_ID = "realesrgan-ncnn-vulkan-20220424-ubuntu"
SRC_W = 8
SRC_H = 6
SCALE_2X = 2
SCALE_4X = 4
MIN_FULL_CHECKS = 4

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
        values = {rest[i]: rest[i + 1] for i in range(0, len(rest), 2)}
        result = self._verbs[verb](Request.from_file(values["--input"]))
        Path(values["--result"]).write_text(json.dumps(result))
        return 0

    def main(self):
        raise SystemExit(self.run(sys.argv[1:]))
"""

FAKE_BIN = """#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from PIL import Image

if os.environ.get("UPSCALE_TEST_FAIL") == "1":
    sys.stderr.write("vkCreateInstance failed: no Vulkan device\\n")
    raise SystemExit(1)

args = sys.argv[1:]
opts = {args[i]: args[i + 1] for i in range(0, len(args), 2)}
log_path = os.environ.get("UPSCALE_TEST_ARGV_LOG")
if log_path:
    Path(log_path).write_text(" ".join(args), encoding="utf-8")

fmt_map = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP"}
scale = int(opts["-s"])
fmt = opts["-f"]
with Image.open(opts["-i"]) as src:
    out = src.resize((src.width * scale, src.height * scale), Image.Resampling.NEAREST)
    if fmt == "jpg" and out.mode != "RGB":
        out = out.convert("RGB")
    out.save(opts["-o"], format=fmt_map[fmt])
"""


def _setup_env(tmp_path: Path, *, nested: bool = True) -> tuple[Path, Path, Path]:
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(exist_ok=True)
    (stub_dir / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")

    zip_path = tmp_path / "models" / f"{MODEL_ID}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"{MODEL_ID}/" if nested else ""
    with zipfile.ZipFile(zip_path, "w") as bundle:
        bundle.writestr(f"{prefix}realesrgan-ncnn-vulkan", FAKE_BIN)
        bundle.writestr(f"{prefix}models/realesrgan-x4plus.bin", b"stub")

    piece_dir = tmp_path / "piece"
    piece_dir.mkdir(exist_ok=True)
    img = Image.new("RGB", (SRC_W, SRC_H), (20, 90, 180))
    img.putpixel((0, 0), (240, 220, 40))
    img.save(piece_dir / "sample.png", format="PNG")
    return stub_dir, zip_path, piece_dir


def _invoke_runner(
    stub_dir: Path,
    verb: str,
    request: dict[str, Any],
    tmp_path: Path,
    tag: str,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    req_path = tmp_path / f"{tag}-{verb}-req.json"
    res_path = tmp_path / f"{tag}-{verb}-res.json"
    req_path.write_text(json.dumps(request), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(stub_dir), **(extra_env or {})}
    done = subprocess.run(
        [sys.executable, str(RUNNER), verb, "--input", str(req_path), "--result", str(res_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(res_path.read_text(encoding="utf-8")) if res_path.is_file() else {}
    return done, payload


def _base_req(
    verb: str,
    out_dir: Path,
    piece_dir: Path,
    zip_path: Path,
    inputs: dict[str, Any],
    *,
    assets: list[Path] | None = None,
    depth: str = "quick",
) -> dict[str, Any]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "upscale.enhance",
        "depth": depth,
        "inputs": inputs,
        "out_dir": str(out_dir),
        "piece_dir": str(piece_dir),
        "models": {MODEL_ID: str(zip_path)},
        "assets": [str(p) for p in (assets or [])],
    }


def test_run_4x_verify_and_preview(tmp_path: Path) -> None:
    stub_dir, zip_path, piece_dir = _setup_env(tmp_path, nested=True)
    out_dir = tmp_path / "out"
    inputs = {
        "image": "sample.png",
        "name": "sample-4x",
        "scale": "4",
        "model": "realesrgan-x4plus",
        "format": "png",
    }
    done, res = _invoke_runner(
        stub_dir, "run", _base_req("run", out_dir, piece_dir, zip_path, inputs), tmp_path, "r4"
    )
    assert done.returncode == 0, done.stderr
    asset = res["assets"][0]
    assert asset["file"] == "sample-4x.png"
    assert asset["seed"] == 0
    assert asset["properties"]["width"] == SRC_W * SCALE_4X
    assert asset["properties"]["height"] == SRC_H * SCALE_4X
    assert asset["properties"]["bytes"] > 0

    out_file = out_dir / "sample-4x.png"
    done_v, res_v = _invoke_runner(
        stub_dir,
        "verify",
        _base_req("verify", out_dir, piece_dir, zip_path, inputs, assets=[out_file]),
        tmp_path,
        "v4",
    )
    assert done_v.returncode == 0, done_v.stderr
    assert res_v["assets"][0]["passed"] is True

    done_p, res_p = _invoke_runner(
        stub_dir,
        "preview",
        _base_req("preview", out_dir, piece_dir, zip_path, inputs, assets=[out_file]),
        tmp_path,
        "p4",
    )
    assert done_p.returncode == 0, done_p.stderr
    preview_file = out_dir / res_p["assets"][0]["preview"]
    preview_data = json.loads(preview_file.read_text(encoding="utf-8"))
    assert preview_data["kind"] == "image"
    assert preview_data["seed"] == 0
    assert preview_data["prompt"] == "upscale 4x (realesrgan-x4plus) of sample"
    assert preview_data["width"] == SRC_W * SCALE_4X
    assert preview_data["height"] == SRC_H * SCALE_4X


def test_run_2x_x4plus_uses_4x_then_lanczos_downscale(tmp_path: Path) -> None:
    stub_dir, zip_path, piece_dir = _setup_env(tmp_path, nested=False)
    out_dir = tmp_path / "out"
    argv_log = tmp_path / "argv.txt"
    inputs = {
        "image": "sample.png",
        "name": "sample-2x-jpg",
        "scale": "2",
        "model": "realesrgan-x4plus",
        "format": "jpg",
    }
    done, res = _invoke_runner(
        stub_dir,
        "run",
        _base_req("run", out_dir, piece_dir, zip_path, inputs),
        tmp_path,
        "r2l",
        extra_env={"UPSCALE_TEST_ARGV_LOG": str(argv_log)},
    )
    assert done.returncode == 0, done.stderr
    assert "-s 4" in argv_log.read_text(encoding="utf-8")
    assert res["assets"][0]["file"] == "sample-2x-jpg.jpg"
    assert res["assets"][0]["properties"]["width"] == SRC_W * SCALE_2X
    assert res["assets"][0]["properties"]["height"] == SRC_H * SCALE_2X

    out_file = out_dir / "sample-2x-jpg.jpg"
    _, res_v = _invoke_runner(
        stub_dir,
        "verify",
        _base_req("verify", out_dir, piece_dir, zip_path, inputs, assets=[out_file]),
        tmp_path,
        "v2l",
    )
    assert res_v["assets"][0]["passed"] is True


def test_run_2x_animevideov3_uses_native_2x(tmp_path: Path) -> None:
    stub_dir, zip_path, piece_dir = _setup_env(tmp_path, nested=True)
    out_dir = tmp_path / "out"
    argv_log = tmp_path / "argv.txt"
    inputs = {
        "image": "sample.png",
        "name": "sample-2x-native",
        "scale": "2",
        "model": "realesr-animevideov3",
        "format": "webp",
    }
    done, res = _invoke_runner(
        stub_dir,
        "run",
        _base_req("run", out_dir, piece_dir, zip_path, inputs),
        tmp_path,
        "r2n",
        extra_env={"UPSCALE_TEST_ARGV_LOG": str(argv_log)},
    )
    assert done.returncode == 0, done.stderr
    assert "-s 2" in argv_log.read_text(encoding="utf-8")
    assert res["assets"][0]["properties"]["width"] == SRC_W * SCALE_2X
    assert res["assets"][0]["properties"]["height"] == SRC_H * SCALE_2X


def test_doctor_quick_and_full_reports_vulkan_status(tmp_path: Path) -> None:
    stub_dir, zip_path, piece_dir = _setup_env(tmp_path, nested=True)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    done_ok, res_ok = _invoke_runner(
        stub_dir,
        "doctor",
        _base_req("doctor", out_dir, piece_dir, zip_path, {}, depth="full"),
        tmp_path,
        "doc_ok",
    )
    assert done_ok.returncode == 0, done_ok.stderr
    checks_ok = {item["name"]: item for item in res_ok["checks"]}
    assert len(checks_ok) >= MIN_FULL_CHECKS
    assert checks_ok["binary"]["ok"] is True
    assert checks_ok["imports"]["ok"] is True
    assert checks_ok["vulkan"]["ok"] is True

    _, res_fail = _invoke_runner(
        stub_dir,
        "doctor",
        _base_req("doctor", out_dir, piece_dir, zip_path, {}, depth="full"),
        tmp_path,
        "doc_fail",
        extra_env={"UPSCALE_TEST_FAIL": "1"},
    )
    checks_fail = {item["name"]: item for item in res_fail["checks"]}
    assert checks_fail["vulkan"]["ok"] is False
    assert "Vulkan" in checks_fail["vulkan"]["detail"]
