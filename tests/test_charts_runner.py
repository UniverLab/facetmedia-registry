"""The charts runner against the package environment, no display and no GPU.

The runner is a subprocess of the package's own python (pinned
matplotlib and Pillow). Its ``PYTHONPATH`` carries a stub
``facet_runner_sdk`` (the pull-time SDK surface), so the test proves the
tabular loader's refusals, the four geometries at exact pixel sizes, the
SVG root and primitives, the image previews, the verify verdicts and the
doctor checks without a display.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import PIL.Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "charts"
RUNNER = PACKAGE / "runner.py"
PYTHON = PACKAGE / ".venv" / "bin" / "python"
IMAGE_SCHEMA: dict[str, Any] = json.loads(
    (ROOT / "schemas" / "preview" / "image.schema.json").read_text(encoding="utf-8")
)
PREVIEW_FIELDS = set(IMAGE_SCHEMA["required"])
WIDTH = 800
HEIGHT = 500
WIDTH_DEFAULT = 1200
HEIGHT_DEFAULT = 675

pytestmark = pytest.mark.skipif(
    not PYTHON.exists(), reason="sync the package env with `uv sync --project packages/charts`"
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

CSV_ROWS = "month,units\nJan,120\nFeb,150\nMar,90\nApr,200\n"
JSON_ROWS = [
    {"month": "Jan", "units": 120},
    {"month": "Feb", "units": 150},
    {"month": "Mar", "units": 90},
    {"month": "Apr", "units": 200},
]
NUMERIC_ROWS = "t,v\n1,2.5\n2,3.5\n3,1.5\n"


def _stub_dir(tmp_path: Path) -> Path:
    """A directory holding the stub SDK, for PYTHONPATH."""
    folder = tmp_path / "stub-modules"
    folder.mkdir(exist_ok=True)
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    return folder


def _piece(tmp_path: Path, files: dict[str, str], tag: str = "piece") -> Path:
    """A piece dir holding the given data files."""
    piece = tmp_path / tag
    piece.mkdir(exist_ok=True)
    for name, content in files.items():
        (piece / name).write_text(content, encoding="utf-8")
    return piece


def _inputs(**overrides: Any) -> dict[str, Any]:
    """A valid bar piece; callers override what they probe."""
    base: dict[str, Any] = {
        "data": "sample.csv",
        "name": "quarter",
        "chart": "bar",
        "title": "Q1 production",
        "subtitle": "Thousands of units",
        "source": "Lab ledger",
        "x": "month",
        "y": "units",
    }
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
        "capability": "charts.render",
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
        [
            str(PYTHON),
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
        timeout=180,
        check=False,
    )
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    return done, result


def _run(
    tmp_path: Path,
    inputs: dict[str, Any],
    files: dict[str, str],
    tag: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, Path]:
    """One ``run`` against a fresh piece and out dir."""
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path, files, tag=f"piece-{tag}")
    out = tmp_path / f"out-{tag}"
    out.mkdir()
    request = _request("run", out, piece, inputs)
    done, result = _call(stub_dir, "run", request, tmp_path, tag)
    return done, result, out


def test_run_writes_a_png_at_the_requested_size(tmp_path: Path) -> None:
    done, result, out = _run(
        tmp_path,
        _inputs(**{"width-px": WIDTH, "height-px": HEIGHT}),
        {"sample.csv": CSV_ROWS},
        "png-size",
    )
    assert done.returncode == 0, done.stderr
    assert result is not None
    assert result["tool"] == {"name": "Editorial Charts", "version": "0.1.0"}
    assert [asset["file"] for asset in result["assets"]] == ["quarter.png"]
    asset = result["assets"][0]
    assert asset["kind"] == "image"
    assert asset["mime"] == "image/png"
    assert asset["seed"] == 0
    with PIL.Image.open(out / "quarter.png") as image:
        assert image.size == (WIDTH, HEIGHT)


def test_run_reads_a_json_table_and_renders_svg(tmp_path: Path) -> None:
    piece_files = {"sample.json": json.dumps(JSON_ROWS)}
    done, result, out = _run(
        tmp_path,
        _inputs(data="sample.json", name="quarter-svg", format="svg"),
        piece_files,
        "svg",
    )
    assert done.returncode == 0, done.stderr
    assert result is not None
    assert [asset["file"] for asset in result["assets"]] == ["quarter-svg.svg"]
    assert result["assets"][0]["mime"] == "image/svg+xml"
    root = ET.parse(out / "quarter-svg.svg").getroot()
    assert root.tag.endswith("svg")
    assert root.get("width") == "1200"
    assert root.get("height") == "675"
    assert root.get("viewBox") == "0 0 1200 675"
    assert (out / "quarter-svg.svg").stat().st_size > 0


def test_run_covers_line_scatter_and_horizontal_bars(tmp_path: Path) -> None:
    cases = [
        ("line-num", {"chart": "line", "data": "points.csv", "x": "t", "y": "v"}, NUMERIC_ROWS),
        ("scatter", {"chart": "scatter", "data": "points.csv", "x": "t", "y": "v"}, NUMERIC_ROWS),
        ("barh", {"chart": "barh"}, CSV_ROWS),
    ]
    for tag, override, content in cases:
        name = f"chart-{tag}"
        files = {str(override.get("data", "sample.csv")): content}
        done, result, out = _run(tmp_path, _inputs(name=name, **override), files, tag)
        assert done.returncode == 0, done.stderr
        assert result is not None
        assert [asset["file"] for asset in result["assets"]] == [f"{name}.png"]
        with PIL.Image.open(out / f"{name}.png") as image:
            assert image.size == (1200, 675)


def test_run_refuses_bad_tables(tmp_path: Path) -> None:
    bad: list[tuple[str, dict[str, Any], dict[str, str]]] = [
        ("empty", {}, {"sample.csv": "month,units\n"}),
        ("no-header", {}, {"sample.csv": ""}),
        ("missing-column", {"x": "region"}, {"sample.csv": CSV_ROWS}),
        ("non-numeric-y", {"y": "month"}, {"sample.csv": CSV_ROWS}),
        ("scatter-words", {"chart": "scatter", "x": "month"}, {"sample.csv": CSV_ROWS}),
        ("unknown-chart", {"chart": "pie"}, {"sample.csv": CSV_ROWS}),
        ("bad-accent", {"accent": "gold"}, {"sample.csv": CSV_ROWS}),
        ("bad-ext", {"data": "sample.txt"}, {"sample.txt": CSV_ROWS}),
        ("missing-file", {"data": "absent.csv"}, {"sample.csv": CSV_ROWS}),
    ]
    for tag, override, files in bad:
        done, result, _out = _run(tmp_path, _inputs(**override), files, f"bad-{tag}")
        assert done.returncode != 0, tag
        assert result is None, tag


def test_verify_passes_the_rendered_assets(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    _done, result, out = _run(tmp_path, _inputs(), {"sample.csv": CSV_ROWS}, "verify-pass")
    assert result is not None
    assets = [out / asset["file"] for asset in result["assets"]]
    request = _request("verify", out, out, _inputs(), tuple(assets))
    done, verdict = _call(stub_dir, "verify", request, tmp_path, "verify-pass")
    assert done.returncode == 0, done.stderr
    assert verdict is not None
    assert [entry["file"] for entry in verdict["assets"]] == ["quarter.png"]
    assert all(entry["passed"] for entry in verdict["assets"])
    assert all(entry["verifier"] == "charts" for entry in verdict["assets"])


def test_verify_rejects_a_flat_png_and_bad_svg(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path, {"sample.csv": CSV_ROWS}, tag="piece-verify-fail")
    out = tmp_path / "out-verify-fail"
    out.mkdir()
    flat = out / "quarter.png"
    PIL.Image.new("RGB", (WIDTH, HEIGHT), "white").save(flat)
    broken = out / "quarter.svg"
    broken.write_text("<svg><oops>", encoding="utf-8")
    request = _request("verify", out, piece, _inputs(), (flat, broken))
    done, verdict = _call(stub_dir, "verify", request, tmp_path, "verify-fail")
    assert done.returncode == 0, done.stderr
    assert verdict is not None
    by_file = {entry["file"]: entry for entry in verdict["assets"]}
    assert by_file["quarter.png"]["passed"] is False
    assert by_file["quarter.svg"]["passed"] is False


def test_verify_fails_missing_assets_without_crashing(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path, {"sample.csv": CSV_ROWS}, tag="piece-verify-missing")
    out = tmp_path / "out-verify-missing"
    out.mkdir()
    missing = (out / "gone.png", out / "gone.svg")
    request = _request("verify", out, piece, _inputs(), missing)
    done, verdict = _call(stub_dir, "verify", request, tmp_path, "verify-missing")
    assert done.returncode == 0, done.stderr
    assert verdict is not None
    by_file = {entry["file"]: entry for entry in verdict["assets"]}
    assert by_file["gone.png"]["passed"] is False
    assert by_file["gone.svg"]["passed"] is False


def test_preview_writes_the_image_schema_fields(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    _done, result, out = _run(tmp_path, _inputs(), {"sample.csv": CSV_ROWS}, "preview")
    assert result is not None
    assets = [out / asset["file"] for asset in result["assets"]]
    request = _request("preview", out, out, _inputs(), tuple(assets))
    done, previews = _call(stub_dir, "preview", request, tmp_path, "preview")
    assert done.returncode == 0, done.stderr
    assert previews is not None
    assert previews["assets"][0]["preview"] == "quarter.png.preview.json"
    data = json.loads((out / "quarter.png.preview.json").read_text(encoding="utf-8"))
    assert set(data) >= PREVIEW_FIELDS
    assert data["preview"] == 1
    assert data["kind"] == "image"
    assert data["name"] == "quarter"
    assert data["prompt"] == "bar: Q1 production"
    assert data["seed"] == 0
    assert (data["width"], data["height"]) == (WIDTH_DEFAULT, HEIGHT_DEFAULT)


def test_preview_reports_the_requested_size_for_svg(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    inputs = _inputs(name="quarter-svg", format="svg", **{"width-px": WIDTH, "height-px": HEIGHT})
    _done, result, out = _run(tmp_path, inputs, {"sample.csv": CSV_ROWS}, "preview-svg")
    assert result is not None
    assets = [out / asset["file"] for asset in result["assets"]]
    request = _request("preview", out, out, inputs, tuple(assets))
    done, previews = _call(stub_dir, "preview", request, tmp_path, "preview-svg")
    assert done.returncode == 0, done.stderr
    assert previews is not None
    data = json.loads((out / "quarter-svg.svg.preview.json").read_text(encoding="utf-8"))
    assert data["prompt"] == "bar: Q1 production"
    assert data["seed"] == 0
    assert (data["width"], data["height"]) == (WIDTH, HEIGHT)


def test_doctor_checks_imports_and_renders_at_full_depth(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    out = tmp_path / "out-doctor"
    out.mkdir()
    piece = _piece(tmp_path, {"sample.csv": CSV_ROWS}, tag="piece-doctor")
    quick = _request("doctor", out, piece, {}, depth="quick")
    done, report = _call(stub_dir, "doctor", quick, tmp_path, "doctor-quick")
    assert done.returncode == 0, done.stderr
    assert report is not None
    assert [check["name"] for check in report["checks"]] == ["imports"]
    assert all(check["ok"] for check in report["checks"])
    full = _request("doctor", out, piece, {}, depth="full")
    done, report = _call(stub_dir, "doctor", full, tmp_path, "doctor-full")
    assert done.returncode == 0, done.stderr
    assert report is not None
    assert [check["name"] for check in report["checks"]] == ["imports", "render"]
    assert all(check["ok"] for check in report["checks"])
