"""The pillow runner against a stub SDK, no network and no GPU.

The runner is a subprocess of the host ``python`` with real Pillow. Its
``PYTHONPATH`` carries a stub ``facet_runner_sdk`` (the pull-time SDK
surface), so the test proves the op chain, the per-op filenames, the
jpeg alpha flatten, the sheet grid geometry, the image previews, the
verify verdicts and the doctor checks without any package environment.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import PIL.Image

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "pillow"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
RUNNER = PACKAGE / "runner.py"
WIDTH = 8
HEIGHT = 6
PREVIEW_FIELDS = {
    "preview",
    "kind",
    "summary",
    "name",
    "prompt",
    "seed",
    "width",
    "height",
}
WHITE = (255, 255, 255, 255)
OPAQUE_RED = (255, 0, 0, 255)
#: JPEG is lossy: channel dominance, not exact values, judges the flatten.
CHANNEL_HIGH = 200
CHANNEL_LOW = 40
#: EXIF tag id for orientation; value 6 means the pixels are stored rotated.
EXIF_ORIENTATION_TAG = 274

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


def _piece(tmp_path: Path, name: str = "foto.png") -> Path:
    """A piece dir whose RGBA foto is opaque red left, transparent right."""
    piece = tmp_path / "piece"
    piece.mkdir(exist_ok=True)
    image = PIL.Image.new("RGBA", (WIDTH, HEIGHT))
    pixels = image.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pixels[x, y] = OPAQUE_RED if x < WIDTH // 2 else (0, 255, 0, 0)
    image.save(piece / name)
    return piece


def _request(
    verb: str,
    out_dir: Path,
    piece_dir: Path,
    inputs: dict[str, object],
    assets: tuple[Path, ...] = (),
    depth: str = "quick",
) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "pillow.base",
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
    request: dict[str, object],
    tmp_path: Path,
    tag: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    input_path = tmp_path / f"{tag}-{verb}-request.json"
    result_path = tmp_path / f"{tag}-{verb}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    result_path.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONPATH": str(stub_dir)}
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
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
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    return done, result


def _run(
    tmp_path: Path, ops: list[dict[str, object]], tag: str = "run"
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, Path]:
    """One ``run`` against a fresh piece and out dir."""
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path)
    out = tmp_path / f"out-{tag}"
    out.mkdir()
    request = _request("run", out, piece, {"image": "foto.png", "operations": ops})
    done, result = _call(stub_dir, "run", request, tmp_path, tag)
    return done, result, out


def _piece_exif6(tmp_path: Path, name: str = "foto6.jpg") -> Path:
    """A piece dir whose 8x6 JPEG has EXIF orientation 6, red left, green right."""
    piece = tmp_path / "piece-exif6"
    piece.mkdir(exist_ok=True)
    image = PIL.Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    assert pixels is not None
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pixels[x, y] = (255, 0, 0) if x < WIDTH // 2 else (0, 255, 0)
    exif = PIL.Image.Exif()
    exif[EXIF_ORIENTATION_TAG] = 6
    image.save(piece / name, exif=exif)
    return piece


def _run_on_piece(
    tmp_path: Path,
    piece: Path,
    image_name: str,
    ops: list[dict[str, object]],
    tag: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, Path]:
    """One ``run`` against an explicit piece dir and image name."""
    stub_dir = _stub_dir(tmp_path)
    out = tmp_path / f"out-{tag}"
    out.mkdir(exist_ok=True)
    request = _request("run", out, piece, {"image": image_name, "operations": ops})
    done, result = _call(stub_dir, "run", request, tmp_path, tag)
    return done, result, out


def test_run_applies_exif_orientation_6(tmp_path: Path) -> None:
    """Orientation 6 is transposed before the ops: 8x6 stored reads as 6x8 upright."""
    piece = _piece_exif6(tmp_path)
    ops: list[dict[str, object]] = [{"op": "convert", "format": "png"}]
    done, _result, out = _run_on_piece(tmp_path, piece, "foto6.jpg", ops, tag="exif6")
    assert done.returncode == 0, done.stdout + done.stderr
    path = out / "foto6-1-convert.png"
    assert path.is_file()
    with PIL.Image.open(path) as image:
        assert image.size == (HEIGHT, WIDTH)
        assert EXIF_ORIENTATION_TAG not in image.getexif()
        top_right = image.getpixel((HEIGHT - 1, 0))
    assert top_right[0] > CHANNEL_HIGH and top_right[1] < CHANNEL_LOW


def test_run_without_exif_unchanged(tmp_path: Path) -> None:
    """A tagless image keeps its stored size: the transpose is a no-op for it."""
    done, _result, out = _run(tmp_path, [{"op": "convert", "format": "png"}])
    assert done.returncode == 0, done.stdout + done.stderr
    with PIL.Image.open(out / "foto-1-convert.png") as image:
        assert image.size == (WIDTH, HEIGHT)


def test_run_applies_the_ops_in_order_with_per_op_files(tmp_path: Path) -> None:
    ops = [
        {"op": "convert", "format": "webp"},
        {"op": "resize", "width": 4},
        {"op": "sheet", "columns": 2, "rows": 2},
    ]
    done, result, out = _run(tmp_path, ops)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    names = ["foto-1-convert.webp", "foto-2-resize.webp", "foto-3-sheet.png"]
    for name in names:
        assert (out / name).is_file(), name
    with PIL.Image.open(out / "foto-1-convert.webp") as image:
        assert image.mode == "RGBA"
        assert image.size == (WIDTH, HEIGHT)
    with PIL.Image.open(out / "foto-2-resize.webp") as image:
        assert image.mode == "RGBA"
        assert image.size == (4, 3)  # aspect preserved: 8x6 -> 4x3
    with PIL.Image.open(out / "foto-3-sheet.png") as image:
        assert image.mode == "RGBA"
        # floor tiles 4x3 into 2x2 of 2x1, plus one 2px divider each axis.
        assert image.size == (6, 4)
        assert image.getpixel((0, 0)) == OPAQUE_RED
        assert image.getpixel((2, 0)) == WHITE  # vertical divider column
        assert image.getpixel((0, 2)) == WHITE  # horizontal divider row
    assets = result["assets"]
    assert [asset["file"] for asset in assets] == names
    assert all(asset["kind"] == "image" for asset in assets)
    assert all(asset["seed"] == 0 for asset in assets)
    assert assets[0]["mime"] == "image/webp"
    assert assets[2]["mime"] == "image/png"
    assert assets[2]["properties"] == {"width": 6, "height": 4}
    assert result["tool"]["name"] == MANIFEST["tool_name"]


def test_convert_jpeg_flattens_alpha_onto_white(tmp_path: Path) -> None:
    done, _result, out = _run(tmp_path, [{"op": "convert", "format": "jpeg"}])
    assert done.returncode == 0, done.stdout + done.stderr
    path = out / "foto-1-convert.jpg"
    assert path.is_file()
    with PIL.Image.open(path) as image:
        assert image.mode == "RGB"
        red = image.getpixel((1, 1))
        white = image.getpixel((WIDTH - 1, 1))
    assert red[0] > CHANNEL_HIGH and red[1] < CHANNEL_LOW and red[2] < CHANNEL_LOW
    assert all(channel > CHANNEL_HIGH for channel in white)


def test_convert_mode_rgba_png_keeps_the_alpha(tmp_path: Path) -> None:
    done, _result, out = _run(tmp_path, [{"op": "convert", "format": "png", "mode": "RGBA"}])
    assert done.returncode == 0, done.stdout + done.stderr
    with PIL.Image.open(out / "foto-1-convert.png") as image:
        assert image.mode == "RGBA"
        assert image.getchannel("A").getextrema() == (0, 255)


def test_resize_exact_changes_the_aspect(tmp_path: Path) -> None:
    done, _result, out = _run(tmp_path, [{"op": "resize", "width": 6, "height": 4}])
    assert done.returncode == 0, done.stdout + done.stderr
    with PIL.Image.open(out / "foto-1-resize.png") as image:
        assert image.size == (6, 4)  # exact: 8x6 -> 6x4, aspect may change


def test_resize_one_dim_preserves_the_aspect(tmp_path: Path) -> None:
    done, _result, out = _run(tmp_path, [{"op": "resize", "height": 3}])
    assert done.returncode == 0, done.stdout + done.stderr
    with PIL.Image.open(out / "foto-1-resize.png") as image:
        assert image.size == (4, 3)  # round(8 * 3 / 6) = 4 wide


def test_convert_without_format_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(tmp_path, [{"op": "convert"}])
    assert done.returncode != 0
    assert result is None
    assert "operations[1]: pillow convert: format is required" in done.stderr


def test_convert_rgba_with_jpeg_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(tmp_path, [{"op": "convert", "format": "jpeg", "mode": "RGBA"}])
    assert done.returncode != 0
    assert result is None
    assert "pillow convert: mode RGBA is incompatible with jpeg" in done.stderr
    assert "use png or webp" in done.stderr


def test_resize_without_dims_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(tmp_path, [{"op": "resize"}])
    assert done.returncode != 0
    assert result is None
    assert "operations[1]: pillow resize: width or height is required" in done.stderr


def test_resize_non_positive_dim_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(tmp_path, [{"op": "resize", "width": 0}])
    assert done.returncode != 0
    assert result is None
    assert "width must be an integer >= 1" in done.stderr


def test_sheet_without_rows_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(tmp_path, [{"op": "sheet", "columns": 2}])
    assert done.returncode != 0
    assert result is None
    assert "operations[1]: pillow sheet: columns or rows is required" in done.stderr


def test_sheet_grid_taller_than_the_image_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(tmp_path, [{"op": "sheet", "columns": 1, "rows": 9}], tag="run-tall")
    assert done.returncode != 0
    assert result is None
    assert "operations[1]: pillow sheet" in done.stderr
    assert "too small" in done.stderr


def test_preview_writes_the_image_fields_per_asset(tmp_path: Path) -> None:
    ops = [
        {"op": "convert", "format": "png"},
        {"op": "sheet", "columns": 2, "rows": 2},
    ]
    done, result, out = _run(tmp_path, ops, tag="preview-run")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / "piece"
    assets = tuple(out / name for name in ("foto-1-convert.png", "foto-2-sheet.png"))
    request = _request("preview", out, piece, {"image": "foto.png"}, assets=assets)
    done, preview = _call(stub_dir, "preview", request, tmp_path, "preview")
    assert done.returncode == 0, done.stdout + done.stderr
    assert preview is not None
    assert [entry["file"] for entry in preview["assets"]] == [
        "foto-1-convert.png",
        "foto-2-sheet.png",
    ]
    first = json.loads((out / "foto-1-convert.png.preview.json").read_text(encoding="utf-8"))
    second = json.loads((out / "foto-2-sheet.png.preview.json").read_text(encoding="utf-8"))
    for data, prompt, size in (
        (first, "pillow convert of foto", (WIDTH, HEIGHT)),
        (second, "pillow sheet of foto", (10, 8)),
    ):
        assert set(data) == PREVIEW_FIELDS
        assert data["preview"] == 1
        assert data["kind"] == "image"
        assert data["prompt"] == prompt
        assert data["seed"] == 0
        assert (data["width"], data["height"]) == size


def test_verify_accepts_the_run_outputs_and_rejects_a_bad_file(tmp_path: Path) -> None:
    done, result, out = _run(tmp_path, [{"op": "convert", "format": "png"}])
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    asset = out / "foto-1-convert.png"
    wrong = tmp_path / "wrong" / "foto-1-convert.png"
    wrong.parent.mkdir()
    PIL.Image.new("RGBA", (4, 4)).save(wrong)
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / "piece"
    request = _request(
        "verify",
        out,
        piece,
        {"image": "foto.png", "operations": [{"op": "convert", "format": "png"}]},
        assets=(asset, wrong),
    )
    done, verdict = _call(stub_dir, "verify", request, tmp_path, "verify")
    assert done.returncode == 0, done.stdout + done.stderr
    assert verdict is not None
    good, bad = verdict["assets"]
    assert good["file"] == "foto-1-convert.png" and good["passed"] is True
    assert good["verifier"] == "pillow"
    assert bad["passed"] is False


def test_verify_accepts_the_webp_gray_round_trip(tmp_path: Path) -> None:
    """webp re-opens grayscale saved in it as RGB; verify takes the file's side."""
    ops = [{"op": "convert", "format": "webp", "mode": "L"}]
    done, result, out = _run(tmp_path, ops, tag="webp-l")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    stub_dir = _stub_dir(tmp_path)
    request = _request(
        "verify",
        out,
        tmp_path / "piece",
        {"image": "foto.png", "operations": ops},
        assets=(out / "foto-1-convert.webp",),
    )
    done, verdict = _call(stub_dir, "verify", request, tmp_path, "verify-l")
    assert done.returncode == 0, done.stdout + done.stderr
    assert verdict is not None
    assert verdict["assets"][0]["passed"] is True


def test_doctor_passes_the_import_and_the_full_ops_roundtrip(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path)
    out = tmp_path / "out-doctor"
    out.mkdir()
    quick, quick_result = _call(
        stub_dir,
        "doctor",
        _request("doctor", out, piece, {}, depth="quick"),
        tmp_path,
        "doctor-quick",
    )
    assert quick.returncode == 0, quick.stdout + quick.stderr
    assert quick_result is not None
    checks = {check["name"]: check for check in quick_result["checks"]}
    assert checks["imports"]["ok"] is True
    assert "13.0.0" in checks["imports"]["detail"]
    assert "ops" not in checks
    full, full_result = _call(
        stub_dir,
        "doctor",
        _request("doctor", out, piece, {}, depth="full"),
        tmp_path,
        "doctor-full",
    )
    assert full.returncode == 0, full.stdout + full.stderr
    assert full_result is not None
    checks = {check["name"]: check for check in full_result["checks"]}
    assert checks["ops"]["ok"] is True


def _retouch_request(
    verb: str,
    out_dir: Path,
    piece_dir: Path,
    inputs: dict[str, object],
    assets: tuple[Path, ...] = (),
) -> dict[str, object]:
    req = _request(verb, out_dir, piece_dir, inputs, assets=assets)
    req["capability"] = "pillow.retouch"
    return req


def _run_retouch(
    tmp_path: Path,
    image: PIL.Image.Image,
    inputs: dict[str, object],
    tag: str,
    filename: str = "photo.png",
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, Path, Path]:
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / f"piece-{tag}"
    piece.mkdir(exist_ok=True)
    image.save(piece / filename)
    out = tmp_path / f"out-{tag}"
    out.mkdir(exist_ok=True)
    full_inputs = {"image": filename, "name": "retouched", **inputs}
    req = _retouch_request("run", out, piece, full_inputs)
    done, result = _call(stub_dir, "run", req, tmp_path, tag)
    return done, result, out, piece


def test_retouch_aspect_crop_and_pad(tmp_path: Path) -> None:
    src = PIL.Image.new("RGB", (20, 10), (100, 120, 140))
    done, result, out, _piece = _run_retouch(
        tmp_path, src, {"aspect": "1:1", "pad-px": 4, "pad-color": "#112233"}, tag="aspect-pad"
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    out_path = out / "retouched.png"
    assert out_path.is_file()
    with PIL.Image.open(out_path) as img:
        # 20x10 cropped to 1:1 -> 10x10, plus 4px pad each side -> 18x18
        assert img.size == (18, 18)
        assert img.getpixel((0, 0)) == (0x11, 0x22, 0x33)
        assert img.getpixel((9, 9)) == (100, 120, 140)


def test_retouch_warmth_lut(tmp_path: Path) -> None:
    src = PIL.Image.new("RGB", (8, 8), (128, 128, 128))
    done, _res, out, _p = _run_retouch(tmp_path, src, {"warmth": 1.0}, tag="warm")
    assert done.returncode == 0, done.stdout + done.stderr
    with PIL.Image.open(out / "retouched.png") as img:
        assert img.getpixel((0, 0)) == (152, 128, 104)


def test_retouch_autocontrast_and_grading(tmp_path: Path) -> None:
    src = PIL.Image.new("RGB", (8, 8), (100, 120, 140))
    pixels = src.load()
    assert pixels is not None
    pixels[0, 0] = (60, 80, 100)
    pixels[7, 7] = (180, 200, 220)
    done, _res, out, _p = _run_retouch(
        tmp_path,
        src,
        {"autocontrast": True, "brightness": 1.1, "contrast": 1.2, "saturation": 0.0},
        tag="grade",
    )
    assert done.returncode == 0, done.stdout + done.stderr
    with PIL.Image.open(out / "retouched.png") as img:
        r, g, b = img.getpixel((4, 4))
        # saturation=0.0 -> grayscale
        assert r == g == b


def test_retouch_sharpen_enhances_edge(tmp_path: Path) -> None:
    low_val = 80
    high_val = 160
    src = PIL.Image.new("RGB", (12, 12), (low_val, low_val, low_val))
    for y in range(12):
        for x in range(6, 12):
            src.putpixel((x, y), (high_val, high_val, high_val))
    done, _res, out, _p = _run_retouch(tmp_path, src, {"sharpen": 2.0}, tag="sharpen")
    assert done.returncode == 0, done.stdout + done.stderr
    with PIL.Image.open(out / "retouched.png") as img:
        left_edge = img.getpixel((5, 6))[0]
        right_edge = img.getpixel((6, 6))[0]
        assert left_edge < low_val
        assert right_edge > high_val


def test_retouch_formats_and_alpha_flattening(tmp_path: Path) -> None:
    src = PIL.Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for y in range(8):
        for x in range(4):
            src.putpixel((x, y), OPAQUE_RED)
    # PNG preserves alpha
    done_png, _r1, out_png, _p1 = _run_retouch(tmp_path, src, {"format": "png"}, tag="fmt-png")
    assert done_png.returncode == 0
    with PIL.Image.open(out_png / "retouched.png") as img:
        assert img.mode == "RGBA"
    # WebP preserves alpha
    done_webp, _r2, out_webp, _p2 = _run_retouch(tmp_path, src, {"format": "webp"}, tag="fmt-webp")
    assert done_webp.returncode == 0
    with PIL.Image.open(out_webp / "retouched.webp") as img:
        assert img.mode == "RGBA"
    # JPEG with pad-px == 0 flattens onto white
    done_jpg, _r3, out_jpg, _p3 = _run_retouch(tmp_path, src, {"format": "jpeg"}, tag="fmt-jpg")
    assert done_jpg.returncode == 0
    with PIL.Image.open(out_jpg / "retouched.jpg") as img:
        assert img.mode == "RGB"
        assert all(c > CHANNEL_HIGH for c in img.getpixel((7, 0)))
    # JPEG with pad-px > 0 flattens onto pad-color
    done_pad, _r4, out_pad, _p4 = _run_retouch(
        tmp_path, src, {"format": "jpeg", "pad-px": 2, "pad-color": "#0000FF"}, tag="fmt-jpg-pad"
    )
    assert done_pad.returncode == 0
    with PIL.Image.open(out_pad / "retouched.jpg") as img:
        assert img.mode == "RGB"
        px = img.getpixel((9, 2))
        assert px[0] < CHANNEL_LOW and px[1] < CHANNEL_LOW and px[2] > CHANNEL_HIGH


def test_retouch_verify_and_preview(tmp_path: Path) -> None:
    src = PIL.Image.new("RGB", (20, 10), (120, 130, 140))
    inputs: dict[str, object] = {"image": "photo.png", "name": "plate-out", "aspect": "4:5"}
    done, _res, out, piece = _run_retouch(tmp_path, src, inputs, tag="vp")
    assert done.returncode == 0, done.stdout + done.stderr
    asset = out / "plate-out.png"
    bad = tmp_path / "bad" / "plate-out.png"
    bad.parent.mkdir()
    PIL.Image.new("RGB", (5, 5)).save(bad)
    stub_dir = _stub_dir(tmp_path)
    v_done, verdict = _call(
        stub_dir,
        "verify",
        _retouch_request("verify", out, piece, inputs, assets=(asset, bad)),
        tmp_path,
        "vp-verify",
    )
    assert v_done.returncode == 0, v_done.stdout + v_done.stderr
    assert verdict is not None
    assert verdict["assets"][0]["passed"] is True
    assert verdict["assets"][1]["passed"] is False

    p_done, preview = _call(
        stub_dir,
        "preview",
        _retouch_request("preview", out, piece, inputs, assets=(asset,)),
        tmp_path,
        "vp-preview",
    )
    assert p_done.returncode == 0, p_done.stdout + p_done.stderr
    assert preview is not None
    pdata = json.loads((out / "plate-out.png.preview.json").read_text(encoding="utf-8"))
    assert set(pdata) == PREVIEW_FIELDS
    assert pdata["prompt"] == "pillow retouch of photo"
    assert pdata["seed"] == 0
    assert (pdata["width"], pdata["height"]) == (8, 10)
