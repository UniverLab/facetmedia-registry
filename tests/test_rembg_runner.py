"""The rembg runner against a stub SDK and a stub rembg, no weights download.

The runner is a subprocess of the host ``python``. Its ``PYTHONPATH``
carries a stub ``facet_runner_sdk`` (the pull-time SDK surface) and a stub
``rembg`` module whose ``new_session`` records the model name, providers
and ``U2NET_HOME``, and whose ``remove`` returns a deterministic RGBA
image — the right half fully transparent — so the test can prove the
alpha PNG and the checkerboard ``-checkerboard`` beside it, the image previews,
the verify verdicts and the doctor's weights check, all without onnxruntime
or the real 4.6 MB weights.
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
PACKAGE = ROOT / "packages" / "rembg"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
MODEL = MANIFEST["models"][0]
RUNNER = PACKAGE / "runner.py"
WIDTH = 64
HEIGHT = 48
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
CHECKER_COLORS = {(255, 255, 255), (216, 221, 226)}
LAMINA_WIDTH = 640
LAMINA_HEIGHT = 64
PAPER = (210, 200, 190)
OBJECT = (20, 120, 60)
PAPER_TOLERANCE = 8

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

#: A deterministic rembg: records the session arguments, returns an RGBA
#: image whose right half is fully transparent.
STUB_REMBG = """
import json
import os
from pathlib import Path

from PIL import Image

LOG = os.environ.get("REMBG_STUB_LOG", "")


def new_session(name, providers=None, **kwargs):
    if LOG:
        Path(LOG).write_text(
            json.dumps(
                {
                    "name": name,
                    "providers": providers,
                    "u2net_home": os.environ.get("U2NET_HOME"),
                }
            )
        )
    return {"name": name, "providers": providers}


def remove(image, session=None, only_mask=False, **kwargs):
    if only_mask:
        mask = Image.new("L", image.size, 255)
        pixels = mask.load()
        width, height = mask.size
        for y in range(height):
            for x in range(width // 2, width):
                pixels[x, y] = 0
        return mask
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    for y in range(height):
        for x in range(width // 2, width):
            pixels[x, y] = (0, 0, 0, 0)
    return rgba
"""


def _stub_modules(tmp_path: Path) -> Path:
    """A directory holding the stub SDK and the stub rembg, for PYTHONPATH."""
    folder = tmp_path / "stub-modules"
    folder.mkdir()
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    (folder / "rembg.py").write_text(STUB_REMBG, encoding="utf-8")
    return folder


def _model_file(home: Path, content: bytes | None = None) -> Path:
    """A placeholder weights file where facet pull puts it."""
    path = home / "models" / "direct" / str(MODEL["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if content is not None else b"stub weights")
    return path


def _piece(tmp_path: Path) -> Path:
    """The piece dir with a small RGB photo for the cutout."""
    piece = tmp_path / "piece"
    piece.mkdir()
    gradient = PIL.Image.new("RGB", (WIDTH, HEIGHT))
    pixels = gradient.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pixels[x, y] = (x * 3 % 256, y * 5 % 256, (x + y) % 256)
    gradient.save(piece / "entrada.png")
    return piece


def _paper_piece(tmp_path: Path, width: int = LAMINA_WIDTH) -> Path:
    """A plate: flat paper P on the right, an object O in the left half."""
    piece = tmp_path / "paper-piece"
    piece.mkdir()
    plate = PIL.Image.new("RGB", (width, LAMINA_HEIGHT), PAPER)
    pixels = plate.load()
    for y in range(10, 54):
        for x in range(10, 100):
            pixels[x, y] = OBJECT
    plate.save(piece / "plate.png")
    return piece


def _request(
    verb: str,
    out_dir: Path,
    piece_dir: Path,
    models: dict[str, Path],
    assets: tuple[Path, ...] = (),
    inputs: dict[str, object] | None = None,
    capability: str = "rembg.cutout",
) -> dict[str, object]:
    if inputs is None:
        inputs = {"photo": "entrada.png"}
    return {
        "protocol": 1,
        "verb": verb,
        "capability": capability,
        "inputs": inputs,
        "out_dir": str(out_dir),
        "piece_dir": str(piece_dir),
        "models": {key: str(value) for key, value in models.items()},
        "assets": [str(path) for path in assets],
    }


def _call(
    stub_dir: Path,
    verb: str,
    request: dict[str, object],
    tmp_path: Path,
    env: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    input_path = tmp_path / f"{verb}-request.json"
    result_path = tmp_path / f"{verb}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    result_path.unlink(missing_ok=True)
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


def _environment(stub_dir: Path, tmp_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "REMBG_STUB_LOG": str(tmp_path / "session.json"),
    }


def test_run_writes_the_alpha_png_and_the_checkerboard(tmp_path: Path) -> None:
    stub_dir = _stub_modules(tmp_path)
    home = tmp_path / "home"
    weights = _model_file(home)
    piece = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(stub_dir, tmp_path)
    done, result = _call(
        stub_dir, "run", _request("run", out, piece, {"u2netp": weights}), tmp_path, env
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    cutout = out / "entrada.png"
    checkerboard = out / "entrada-checkerboard.png"
    assert cutout.is_file() and checkerboard.is_file()
    with PIL.Image.open(cutout) as image:
        assert image.mode == "RGBA"
        assert image.size == (WIDTH, HEIGHT)
        assert image.getchannel("A").getextrema() == (0, 255)
    with PIL.Image.open(checkerboard) as image:
        assert image.mode == "RGB"
        assert image.size == (WIDTH, HEIGHT)
        # The transparent right half shows only checker colours; the opaque
        # left half carries the source pixel through the alpha mask.
        for x, y in ((WIDTH - 1, 0), (WIDTH - 1, HEIGHT - 1), (WIDTH // 2 + 8, 8)):
            assert image.getpixel((x, y)) in CHECKER_COLORS
        with PIL.Image.open(piece / "entrada.png") as source:
            assert image.getpixel((4, 4)) == source.convert("RGB").getpixel((4, 4))
    session = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert session["name"] == "u2netp"
    assert session["providers"] == ["CPUExecutionProvider"]
    assert session["u2net_home"] == str(weights.parent)
    assets = result["assets"]
    assert [asset["file"] for asset in assets] == ["entrada.png", "entrada-checkerboard.png"]
    assert all(asset["kind"] == "image" for asset in assets)
    assert all(asset["name"] == "entrada" for asset in assets)
    assert all(asset["seed"] == 0 for asset in assets)
    assert assets[1]["properties"]["checkerboard"] is True
    assert result["tool"]["name"] == MANIFEST["tool_name"]


def test_preview_writes_the_image_fields_for_both_assets(tmp_path: Path) -> None:
    stub_dir = _stub_modules(tmp_path)
    home = tmp_path / "home"
    weights = _model_file(home)
    piece = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    cutout_image = PIL.Image.new("RGBA", (WIDTH, HEIGHT))
    cutout_image.putpixel((1, 1), (20, 120, 60, 255))
    cutout_image.save(out / "entrada.png")
    view = PIL.Image.new("RGB", (WIDTH, HEIGHT))
    view.putpixel((1, 1), (20, 120, 60))
    view.save(out / "entrada-checkerboard.png")
    env = _environment(stub_dir, tmp_path)
    request = _request(
        "preview",
        out,
        piece,
        {"u2netp": weights},
        assets=(out / "entrada.png", out / "entrada-checkerboard.png"),
    )
    done, result = _call(stub_dir, "preview", request, tmp_path, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert [entry["file"] for entry in result["assets"]] == [
        "entrada.png",
        "entrada-checkerboard.png",
    ]
    for name in ("entrada.png", "entrada-checkerboard.png"):
        data = json.loads((out / f"{name}.preview.json").read_text(encoding="utf-8"))
        assert set(data) == PREVIEW_FIELDS
        assert data["preview"] == 1
        assert data["kind"] == "image"
        assert data["name"] == "entrada"
        assert data["prompt"] == "cutout of entrada"
        assert data["seed"] == 0
        assert (data["width"], data["height"]) == (WIDTH, HEIGHT)


def test_verify_accepts_the_pair_and_rejects_a_bad_file(tmp_path: Path) -> None:
    stub_dir = _stub_modules(tmp_path)
    home = tmp_path / "home"
    weights = _model_file(home)
    piece = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    cutout_image = PIL.Image.new("RGBA", (WIDTH, HEIGHT))
    cutout_image.putpixel((1, 1), (20, 120, 60, 255))
    cutout_image.save(out / "entrada.png")
    view = PIL.Image.new("RGB", (WIDTH, HEIGHT))
    view.putpixel((1, 1), (20, 120, 60))
    view.save(out / "entrada-checkerboard.png")
    rgb_as_cutout = tmp_path / "wrong" / "entrada.png"
    rgb_as_cutout.parent.mkdir()
    PIL.Image.new("RGB", (WIDTH, HEIGHT)).save(rgb_as_cutout)
    notes = out / "notes.txt"
    notes.write_text("not an image\n", encoding="utf-8")
    env = _environment(stub_dir, tmp_path)
    request = _request(
        "verify",
        out,
        piece,
        {"u2netp": weights},
        assets=(out / "entrada.png", out / "entrada-checkerboard.png", rgb_as_cutout, notes),
    )
    done, result = _call(stub_dir, "verify", request, tmp_path, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    cutout, checkerboard, wrong_mode, bad = result["assets"]
    assert cutout["file"] == "entrada.png" and cutout["passed"] is True
    assert cutout["metrics"]["mode"] == "RGBA"
    assert checkerboard["file"] == "entrada-checkerboard.png" and checkerboard["passed"] is True
    assert checkerboard["metrics"]["mode"] == "RGB"
    assert wrong_mode["file"] == "entrada.png" and wrong_mode["passed"] is False
    assert wrong_mode["metrics"]["mode"] == "RGB"
    assert bad["file"] == "notes.txt" and bad["passed"] is False


def test_doctor_fails_the_weights_without_the_pulled_file(tmp_path: Path) -> None:
    stub_dir = _stub_modules(tmp_path)
    piece = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(stub_dir, tmp_path)
    done, result = _call(
        stub_dir,
        "doctor",
        _request("doctor", out, piece, {}),
        tmp_path,
        env,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["imports"]["ok"] is False  # rembg is not in this env
    weights = checks["weights"]
    assert weights["ok"] is False
    assert weights["fix"] == "facet pull rembg"


def test_doctor_fails_a_mismatched_weights_file(tmp_path: Path) -> None:
    stub_dir = _stub_modules(tmp_path)
    home = tmp_path / "home"
    weights = _model_file(home, content=b"not the real weights")
    piece = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(stub_dir, tmp_path)
    done, result = _call(
        stub_dir,
        "doctor",
        _request("doctor", out, piece, {"u2netp": weights}),
        tmp_path,
        env,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    checks = {check["name"]: check for check in result["checks"]}
    weights_check = checks["weights"]
    assert weights_check["ok"] is False
    assert "bytes" in weights_check["detail"]
    assert weights_check["fix"] == "facet pull rembg"


def test_doctor_fails_a_same_size_weights_with_the_wrong_hash(tmp_path: Path) -> None:
    """Right byte count but wrong sha256 still fails on the hash itself."""
    stub_dir = _stub_modules(tmp_path)
    home = tmp_path / "home"
    weights = _model_file(home, content=b"\0" * int(MODEL["bytes"]))
    piece = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(stub_dir, tmp_path)
    done, result = _call(
        stub_dir,
        "doctor",
        _request("doctor", out, piece, {"u2netp": weights}),
        tmp_path,
        env,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    checks = {check["name"]: check for check in result["checks"]}
    weights_check = checks["weights"]
    assert weights_check["ok"] is False
    assert "sha256" in weights_check["detail"]
    assert weights_check["fix"] == "facet pull rembg"


def test_run_paper_writes_one_rgb_asset_on_flat_paper(tmp_path: Path) -> None:
    """Papel keeps the object's pixels and replaces everything else with paper."""
    stub_dir = _stub_modules(tmp_path)
    home = tmp_path / "home"
    weights = _model_file(home)
    piece = _paper_piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(stub_dir, tmp_path)
    request = _request(
        "run",
        out,
        piece,
        {"u2netp": weights},
        inputs={"plate": "plate.png"},
        capability="rembg.paper",
    )
    done, result = _call(stub_dir, "run", request, tmp_path, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    path = out / "plate-paper.png"
    assert path.is_file()
    assert not (out / "plate-checkerboard.png").exists()
    with PIL.Image.open(path) as image:
        assert image.mode == "RGB"
        assert image.size == (LAMINA_WIDTH, LAMINA_HEIGHT)
        assert image.getpixel((50, 30)) == OBJECT
        paper = image.getpixel((500, 30))
    assert all(abs(got - want) <= PAPER_TOLERANCE for got, want in zip(paper, PAPER, strict=True))
    session = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert session["name"] == "u2netp"
    assets = result["assets"]
    assert [asset["file"] for asset in assets] == ["plate-paper.png"]
    assert assets[0]["name"] == "plate"
    assert assets[0]["kind"] == "image"
    assert assets[0]["seed"] == 0
    assert "checkerboard" not in assets[0]["properties"]


def test_run_paper_on_a_plate_narrower_than_the_border_inset_is_not_black(
    tmp_path: Path,
) -> None:
    """A 128 px plate once sliced an empty border and wrote an all-black image."""
    stub_dir = _stub_modules(tmp_path)
    home = tmp_path / "home"
    weights = _model_file(home)
    piece = _paper_piece(tmp_path, width=128)
    out = tmp_path / "out"
    out.mkdir()
    env = _environment(stub_dir, tmp_path)
    request = _request(
        "run",
        out,
        piece,
        {"u2netp": weights},
        inputs={"plate": "plate.png"},
        capability="rembg.paper",
    )
    done, _result = _call(stub_dir, "run", request, tmp_path, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Mean of empty slice" not in done.stderr
    with PIL.Image.open(out / "plate-paper.png") as image:
        paper = image.getpixel((120, 30))
    assert all(abs(got - want) <= PAPER_TOLERANCE for got, want in zip(paper, PAPER, strict=True))


def test_verify_rejects_a_flat_image(tmp_path: Path) -> None:
    """An all-black paper must not verify: a uniform image is never a real plate."""
    stub_dir = _stub_modules(tmp_path)
    home = tmp_path / "home"
    weights = _model_file(home)
    piece = _paper_piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    black = out / "plate-paper.png"
    PIL.Image.new("RGB", (LAMINA_WIDTH, LAMINA_HEIGHT), (0, 0, 0)).save(black)
    env = _environment(stub_dir, tmp_path)
    request = _request(
        "verify",
        out,
        piece,
        {"u2netp": weights},
        assets=(black,),
        inputs={"plate": "plate.png"},
        capability="rembg.paper",
    )
    done, result = _call(stub_dir, "verify", request, tmp_path, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert result["assets"][0]["passed"] is False
    assert result["assets"][0]["metrics"]["flat"] is True


def test_verify_paper_expects_rgb_and_rejects_rgba(tmp_path: Path) -> None:
    """Without the paper branch the RGBA fallback would reject every output."""
    stub_dir = _stub_modules(tmp_path)
    home = tmp_path / "home"
    weights = _model_file(home)
    piece = _paper_piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    good = out / "plate-paper.png"
    paper_image = PIL.Image.new("RGB", (LAMINA_WIDTH, LAMINA_HEIGHT), PAPER)
    paper_image.putpixel((20, 20), OBJECT)
    paper_image.save(good)
    stale = tmp_path / "stale" / "plate-paper.png"
    stale.parent.mkdir()
    PIL.Image.new("RGBA", (LAMINA_WIDTH, LAMINA_HEIGHT), (*PAPER, 255)).save(stale)
    env = _environment(stub_dir, tmp_path)
    request = _request(
        "verify",
        out,
        piece,
        {"u2netp": weights},
        assets=(good, stale),
        inputs={"plate": "plate.png"},
        capability="rembg.paper",
    )
    done, result = _call(stub_dir, "verify", request, tmp_path, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    rgb, rgba = result["assets"]
    assert rgb["passed"] is True
    assert rgb["metrics"]["mode"] == "RGB"
    assert rgba["passed"] is False
    assert rgba["metrics"]["mode"] == "RGBA"


def test_preview_paper_writes_the_image_fields(tmp_path: Path) -> None:
    stub_dir = _stub_modules(tmp_path)
    home = tmp_path / "home"
    weights = _model_file(home)
    piece = _paper_piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    asset = out / "plate-paper.png"
    PIL.Image.new("RGB", (LAMINA_WIDTH, LAMINA_HEIGHT), PAPER).save(asset)
    env = _environment(stub_dir, tmp_path)
    request = _request(
        "preview",
        out,
        piece,
        {"u2netp": weights},
        assets=(asset,),
        inputs={"plate": "plate.png"},
        capability="rembg.paper",
    )
    done, result = _call(stub_dir, "preview", request, tmp_path, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert [entry["file"] for entry in result["assets"]] == ["plate-paper.png"]
    data = json.loads((out / "plate-paper.png.preview.json").read_text(encoding="utf-8"))
    assert set(data) == PREVIEW_FIELDS
    assert data["prompt"] == "clean paper of plate"
    assert data["name"] == "plate"
    assert data["seed"] == 0
    assert (data["width"], data["height"]) == (LAMINA_WIDTH, LAMINA_HEIGHT)
