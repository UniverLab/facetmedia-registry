"""End-to-end runner tests for packages/pdf-ops in its own environment.

The test drives ``runner.py`` as a subprocess of the package
environment's own python over a stub SDK, so the real pikepdf,
pypdfium2 and Pillow do the work: merge really concatenates, split
really selects, compress really rewrites, and rasterize really renders
PNGs. The committed fixtures are tiny blank PDFs beside the examples.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "pdf-ops"
RUNNER = PACKAGE / "runner.py"
EXAMPLES = PACKAGE / "examples"
PYTHON = PACKAGE / ".venv" / "bin" / "python"
IMAGE_SCHEMA = json.loads((ROOT / "schemas" / "preview" / "image.schema.json").read_text())

pytestmark = pytest.mark.skipif(
    not PYTHON.exists(), reason="sync the package env with `uv sync --project packages/pdf-ops`"
)

DOCUMENT_PREVIEW_KEYS = {"preview", "kind", "summary", "page_count", "pages"}
IMAGE_PREVIEW_KEYS = set(IMAGE_SCHEMA["required"])
#: The committed fixtures: a.pdf and b.pdf hold one page, doc.pdf holds two.
SINGLE_PAGE_COUNT = 1
DOUBLE_PAGE_COUNT = 2

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
        [str(PYTHON), str(RUNNER), verb, "--input", str(req_file), "--result", str(res_file)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, f"runner failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return json.loads(res_file.read_text(encoding="utf-8"))


def _run_raw(
    tmp_path: Path, verb: str, capability: str, inputs: dict[str, Any], depth: str = "quick"
) -> subprocess.CompletedProcess[str]:
    sdk_dir = tmp_path / "sdk-raw"
    sdk_dir.mkdir(exist_ok=True)
    (sdk_dir / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    out_dir = tmp_path / "out-raw"
    out_dir.mkdir(exist_ok=True)
    req_file = tmp_path / "raw_input.json"
    res_file = tmp_path / "raw_result.json"
    req_file.write_text(
        json.dumps(
            {
                "verb": verb,
                "capability": capability,
                "depth": depth,
                "inputs": inputs,
                "out_dir": str(out_dir),
                "piece_dir": str(EXAMPLES),
                "assets": [],
            }
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(sdk_dir)
    return subprocess.run(
        [str(PYTHON), str(RUNNER), verb, "--input", str(req_file), "--result", str(res_file)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=300,
    )


def test_merge_combines_two_one_page_pdfs_in_order(tmp_path: Path) -> None:
    inputs = {"pdf": [{"path": "a.pdf"}, {"path": "b.pdf"}], "name": "merged-doc"}
    run_res = _invoke(tmp_path, "run", capability="pdf-ops.merge", inputs=inputs)
    asset = run_res["assets"][0]
    assert asset["kind"] == "document"
    assert asset["file"] == "merged-doc.pdf"
    assert asset["properties"]["page_count"] == DOUBLE_PAGE_COUNT
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()

    ver_res = _invoke(
        tmp_path, "verify", capability="pdf-ops.merge", inputs=inputs, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is True
    assert ver_res["assets"][0]["metrics"]["expected_page_count"] == DOUBLE_PAGE_COUNT

    prev_res = _invoke(
        tmp_path, "preview", capability="pdf-ops.merge", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == DOCUMENT_PREVIEW_KEYS
    assert preview_data["kind"] == "document"
    assert preview_data["page_count"] == DOUBLE_PAGE_COUNT
    assert len(preview_data["pages"]) == DOUBLE_PAGE_COUNT


def test_split_extracts_the_selected_pages(tmp_path: Path) -> None:
    inputs = {"pdf": "doc.pdf", "pages": "2", "name": "split-doc"}
    run_res = _invoke(tmp_path, "run", capability="pdf-ops.split", inputs=inputs)
    asset = run_res["assets"][0]
    assert asset["file"] == "split-doc.pdf"
    assert asset["properties"]["page_count"] == SINGLE_PAGE_COUNT
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()

    ver_res = _invoke(
        tmp_path, "verify", capability="pdf-ops.split", inputs=inputs, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is True
    assert ver_res["assets"][0]["metrics"] == {
        "page_count": SINGLE_PAGE_COUNT,
        "expected_page_count": SINGLE_PAGE_COUNT,
    }

    prev_res = _invoke(
        tmp_path, "preview", capability="pdf-ops.split", inputs=inputs, assets=[out_file]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert preview_data["kind"] == "document"
    assert preview_data["page_count"] == SINGLE_PAGE_COUNT


def test_verify_fails_when_the_selection_does_not_match(tmp_path: Path) -> None:
    inputs = {"pdf": "doc.pdf", "pages": "1", "name": "split-doc"}
    run_res = _invoke(tmp_path, "run", capability="pdf-ops.split", inputs=inputs)
    out_file = tmp_path / "out" / run_res["assets"][0]["file"]
    wrong = {"pdf": "doc.pdf", "pages": "1-2", "name": "split-doc"}
    ver_res = _invoke(
        tmp_path, "verify", capability="pdf-ops.split", inputs=wrong, assets=[out_file]
    )
    assert ver_res["assets"][0]["passed"] is False


def test_compress_keeps_the_page_count(tmp_path: Path) -> None:
    inputs = {"pdf": "doc.pdf", "name": "compressed-doc"}
    run_res = _invoke(tmp_path, "run", capability="pdf-ops.compress", inputs=inputs)
    asset = run_res["assets"][0]
    assert asset["file"] == "compressed-doc.pdf"
    out_file = tmp_path / "out" / asset["file"]
    assert out_file.is_file()
    assert out_file.stat().st_size > 0

    ver_res = _invoke(
        tmp_path, "verify", capability="pdf-ops.compress", inputs=inputs, assets=[out_file]
    )
    verdict = ver_res["assets"][0]
    assert verdict["passed"] is True
    assert verdict["metrics"]["page_count"] == DOUBLE_PAGE_COUNT
    assert verdict["metrics"]["expected_page_count"] == DOUBLE_PAGE_COUNT


def test_rasterize_renders_one_png_per_page(tmp_path: Path) -> None:
    inputs = {"pdf": "doc.pdf", "name": "doc-shots", "pages": "1-2", "dpi": 150}
    run_res = _invoke(tmp_path, "run", capability="pdf-ops.rasterize", inputs=inputs)
    assert len(run_res["assets"]) == DOUBLE_PAGE_COUNT
    assert [asset["file"] for asset in run_res["assets"]] == [
        "doc-shots-page-01.png",
        "doc-shots-page-02.png",
    ]
    out_files = [tmp_path / "out" / asset["file"] for asset in run_res["assets"]]
    assert all(path.is_file() for path in out_files)
    assert all(asset["properties"]["width"] > 0 for asset in run_res["assets"])
    assert all(asset["properties"]["height"] > 0 for asset in run_res["assets"])

    ver_res = _invoke(
        tmp_path, "verify", capability="pdf-ops.rasterize", inputs=inputs, assets=out_files
    )
    assert all(entry["passed"] for entry in ver_res["assets"])

    prev_res = _invoke(
        tmp_path, "preview", capability="pdf-ops.rasterize", inputs=inputs, assets=[out_files[0]]
    )
    preview_data = json.loads((tmp_path / "out" / prev_res["assets"][0]["preview"]).read_text())
    assert set(preview_data) == IMAGE_PREVIEW_KEYS
    assert preview_data["kind"] == "image"
    assert preview_data["width"] > 0
    assert preview_data["height"] > 0


def test_rasterize_defaults_to_every_page(tmp_path: Path) -> None:
    inputs = {"pdf": "doc.pdf", "name": "all-shots"}
    run_res = _invoke(tmp_path, "run", capability="pdf-ops.rasterize", inputs=inputs)
    assert len(run_res["assets"]) == DOUBLE_PAGE_COUNT


def test_bad_page_selections_fail_the_run(tmp_path: Path) -> None:
    for pages in ("0", "3", "2-1", "1,,2", "abc", "1-2-3", ""):
        done = _run_raw(
            tmp_path,
            "run",
            "pdf-ops.split",
            {"pdf": "doc.pdf", "pages": pages, "name": "bad-split"},
        )
        assert done.returncode != 0, pages
        assert "pages" in (done.stderr or ""), pages


def test_doctor_proves_the_imports_and_the_roundtrip(tmp_path: Path) -> None:
    quick = _invoke(tmp_path, "doctor", capability="pdf-ops.merge", depth="quick")
    assert {check["name"] for check in quick["checks"]} == {"pikepdf", "pypdfium2", "PIL"}
    assert all(check["ok"] for check in quick["checks"])

    full = _invoke(tmp_path, "doctor", capability="pdf-ops.merge", depth="full")
    assert all(check["ok"] for check in full["checks"])
    assert len(full["checks"]) == len(quick["checks"]) + 1
