"""The pillow runner against a stub SDK, no network and no GPU.

The runner is a subprocess of the host ``python`` with real Pillow. Its
``PYTHONPATH`` carries a stub ``facet_runner_sdk`` (the pull-time SDK
surface), so the test proves the op chain, the per-op filenames, the
jpeg alpha flatten, the hoja grid geometry, the image previews, the
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
    request = _request("run", out, piece, {"imagen": "foto.png", "operaciones": ops})
    done, result = _call(stub_dir, "run", request, tmp_path, tag)
    return done, result, out


def test_run_applies_the_ops_in_order_with_per_op_files(tmp_path: Path) -> None:
    ops = [
        {"operacion": "convertir", "formato": "webp"},
        {"operacion": "redimensionar", "ancho": 4},
        {"operacion": "hoja", "columnas": 2, "filas": 2},
    ]
    done, result, out = _run(tmp_path, ops)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    names = ["foto-1-convertir.webp", "foto-2-redimensionar.webp", "foto-3-hoja.png"]
    for name in names:
        assert (out / name).is_file(), name
    with PIL.Image.open(out / "foto-1-convertir.webp") as image:
        assert image.mode == "RGBA"
        assert image.size == (WIDTH, HEIGHT)
    with PIL.Image.open(out / "foto-2-redimensionar.webp") as image:
        assert image.mode == "RGBA"
        assert image.size == (4, 3)  # aspect preserved: 8x6 -> 4x3
    with PIL.Image.open(out / "foto-3-hoja.png") as image:
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


def test_convertir_jpeg_flattens_alpha_onto_white(tmp_path: Path) -> None:
    done, _result, out = _run(tmp_path, [{"operacion": "convertir", "formato": "jpeg"}])
    assert done.returncode == 0, done.stdout + done.stderr
    path = out / "foto-1-convertir.jpg"
    assert path.is_file()
    with PIL.Image.open(path) as image:
        assert image.mode == "RGB"
        red = image.getpixel((1, 1))
        white = image.getpixel((WIDTH - 1, 1))
    assert red[0] > CHANNEL_HIGH and red[1] < CHANNEL_LOW and red[2] < CHANNEL_LOW
    assert all(channel > CHANNEL_HIGH for channel in white)


def test_convertir_modo_rgba_png_keeps_the_alpha(tmp_path: Path) -> None:
    done, _result, out = _run(
        tmp_path, [{"operacion": "convertir", "formato": "png", "modo": "RGBA"}]
    )
    assert done.returncode == 0, done.stdout + done.stderr
    with PIL.Image.open(out / "foto-1-convertir.png") as image:
        assert image.mode == "RGBA"
        assert image.getchannel("A").getextrema() == (0, 255)


def test_redimensionar_exact_changes_the_aspect(tmp_path: Path) -> None:
    done, _result, out = _run(tmp_path, [{"operacion": "redimensionar", "ancho": 6, "alto": 4}])
    assert done.returncode == 0, done.stdout + done.stderr
    with PIL.Image.open(out / "foto-1-redimensionar.png") as image:
        assert image.size == (6, 4)  # exact: 8x6 -> 6x4, aspect may change


def test_redimensionar_one_dim_preserves_the_aspect(tmp_path: Path) -> None:
    done, _result, out = _run(tmp_path, [{"operacion": "redimensionar", "alto": 3}])
    assert done.returncode == 0, done.stdout + done.stderr
    with PIL.Image.open(out / "foto-1-redimensionar.png") as image:
        assert image.size == (4, 3)  # round(8 * 3 / 6) = 4 wide


def test_convertir_without_formato_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(tmp_path, [{"operacion": "convertir"}])
    assert done.returncode != 0
    assert result is None
    assert "operaciones[1]: pillow convertir: falta formato" in done.stderr


def test_convertir_rgba_with_jpeg_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(
        tmp_path, [{"operacion": "convertir", "formato": "jpeg", "modo": "RGBA"}]
    )
    assert done.returncode != 0
    assert result is None
    assert "pillow convertir: modo RGBA incompatible con formato jpeg" in done.stderr
    assert "usa png o webp" in done.stderr


def test_redimensionar_without_dims_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(tmp_path, [{"operacion": "redimensionar"}])
    assert done.returncode != 0
    assert result is None
    assert "operaciones[1]: pillow redimensionar: falta ancho o alto" in done.stderr


def test_redimensionar_non_positive_dim_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(tmp_path, [{"operacion": "redimensionar", "ancho": 0}])
    assert done.returncode != 0
    assert result is None
    assert "ancho debe ser un entero >= 1" in done.stderr


def test_hoja_without_filas_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(tmp_path, [{"operacion": "hoja", "columnas": 2}])
    assert done.returncode != 0
    assert result is None
    assert "operaciones[1]: pillow hoja: faltan columnas o filas" in done.stderr


def test_hoja_grid_taller_than_the_image_is_invalid_input(tmp_path: Path) -> None:
    done, result, _out = _run(
        tmp_path, [{"operacion": "hoja", "columnas": 1, "filas": 9}], tag="run-tall"
    )
    assert done.returncode != 0
    assert result is None
    assert "operaciones[1]: pillow hoja" in done.stderr
    assert "demasiado pequeña" in done.stderr


def test_preview_writes_the_image_fields_per_asset(tmp_path: Path) -> None:
    ops = [
        {"operacion": "convertir", "formato": "png"},
        {"operacion": "hoja", "columnas": 2, "filas": 2},
    ]
    done, result, out = _run(tmp_path, ops, tag="preview-run")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / "piece"
    assets = tuple(out / name for name in ("foto-1-convertir.png", "foto-2-hoja.png"))
    request = _request("preview", out, piece, {"imagen": "foto.png"}, assets=assets)
    done, preview = _call(stub_dir, "preview", request, tmp_path, "preview")
    assert done.returncode == 0, done.stdout + done.stderr
    assert preview is not None
    assert [entry["file"] for entry in preview["assets"]] == [
        "foto-1-convertir.png",
        "foto-2-hoja.png",
    ]
    first = json.loads((out / "foto-1-convertir.png.preview.json").read_text(encoding="utf-8"))
    second = json.loads((out / "foto-2-hoja.png.preview.json").read_text(encoding="utf-8"))
    for data, prompt, size in (
        (first, "pillow convertir of foto", (WIDTH, HEIGHT)),
        (second, "pillow hoja of foto", (10, 8)),
    ):
        assert set(data) == PREVIEW_FIELDS
        assert data["preview"] == 1
        assert data["kind"] == "image"
        assert data["prompt"] == prompt
        assert data["seed"] == 0
        assert (data["width"], data["height"]) == size


def test_verify_accepts_the_run_outputs_and_rejects_a_bad_file(tmp_path: Path) -> None:
    done, result, out = _run(tmp_path, [{"operacion": "convertir", "formato": "png"}])
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    asset = out / "foto-1-convertir.png"
    wrong = tmp_path / "wrong" / "foto-1-convertir.png"
    wrong.parent.mkdir()
    PIL.Image.new("RGBA", (4, 4)).save(wrong)
    stub_dir = _stub_dir(tmp_path)
    piece = tmp_path / "piece"
    request = _request(
        "verify",
        out,
        piece,
        {"imagen": "foto.png", "operaciones": [{"operacion": "convertir", "formato": "png"}]},
        assets=(asset, wrong),
    )
    done, verdict = _call(stub_dir, "verify", request, tmp_path, "verify")
    assert done.returncode == 0, done.stdout + done.stderr
    assert verdict is not None
    good, bad = verdict["assets"]
    assert good["file"] == "foto-1-convertir.png" and good["passed"] is True
    assert good["verifier"] == "pillow"
    assert bad["passed"] is False


def test_verify_accepts_the_webp_gray_round_trip(tmp_path: Path) -> None:
    """webp re-opens grayscale saved in it as RGB; verify takes the file's side."""
    ops = [{"operacion": "convertir", "formato": "webp", "modo": "L"}]
    done, result, out = _run(tmp_path, ops, tag="webp-l")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    stub_dir = _stub_dir(tmp_path)
    request = _request(
        "verify",
        out,
        tmp_path / "piece",
        {"imagen": "foto.png", "operaciones": ops},
        assets=(out / "foto-1-convertir.webp",),
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
