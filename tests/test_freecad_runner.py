"""The freecad runner: path conversion, the wrapper, the sheets and the doctor.

No real FreeCAD runs here. A stub ``freecadcmd.exe`` stands where the host
binary does: it answers ``--version`` and executes the package wrapper, which
in turn executes ``runner.py`` with a stub ``FreeCAD`` module and a stub
``PySide6`` package on its path, so the entry takes its in-FreeCAD branch.
Stub ``wslpath`` records the argument conversion, and the fake Qt writes the
page PNGs plus a minimal PDF carrying ``/Type /Pages /Count N``, proving the
sheet contract, the exact preview shape and the missing-host doctor without
FreeCAD or Qt.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "freecad"
RUNNER = PACKAGE / "runner.py"
PDF_NAME = "dibujo"
PREVIEW_KEYS = {"preview", "kind", "summary", "page_count", "pages"}
PAGE_NAMES_ONE = ["preview/page-01.png"]
PAGE_NAMES_TWO = ["preview/page-01.png", "preview/page-02.png"]
PAGE_COUNT_TWO = 2
PAGE_COUNT_THREE = 3
NOT_FOUND = (
    "freecad 1.1.4+ not found (config freecad.path, env FREECAD_EXE, PATH all empty); "
    "fix: facet config set freecad.path /path/to/freecad"
)
FIX = "facet config set freecad.path /path/to/freecad"

STUB_FREECAD = '"""A stub FreeCAD module: the runner only imports it."""\n'

STUB_QT_INIT = '"""A stub PySide6 package: the runner renders its sheets with it."""\n'

STUB_QT_CORE = '''"""A stub QtCore: QByteArray, QMarginsF and QSizeF only."""


class QByteArray(bytes):
    """The sheet's bytes, as the renderer receives them."""

    def __new__(cls, data: bytes = b"") -> "QByteArray":
        return super().__new__(cls, bytes(data))


class QMarginsF:
    """The page margins, in the unit the writer is given."""

    def __init__(self, left: float, top: float, right: float, bottom: float) -> None:
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class QSizeF:
    """A millimetre page size, as QPageSize receives it."""

    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height
'''

STUB_QT_SVG = '''"""A stub QtSvg: QSvgRenderer reports validity and renders nothing."""


class QSvgRenderer:
    """Valid unless the sheet carries the INVALID marker."""

    def __init__(self, data: bytes) -> None:
        self.data = bytes(data)

    def isValid(self) -> bool:
        return b"INVALID" not in self.data

    def render(self, painter: object) -> None:
        return None
'''

STUB_QT_GUI = '''"""A stub QtGui: images save their size, QPdfWriter behaves like Qt's.

``QPdfEngine`` truncates its file when a painter begins, its visitor writes the
page on ``newPage()``, and ``QPainter::end()`` finalizes the document: a second
painter on the same writer would restart the PDF with a single page.
"""

from pathlib import Path


class QPageSize:
    """A named page size from a QSizeF."""

    Millimeter = 0

    def __init__(self, size: object, unit: int) -> None:
        self.size = size
        self.unit = unit


class QPageLayout:
    """The page layout unit setPageMargins takes."""

    Millimeter = 0


class QImage:
    """A white page image that saves its pixel size as placeholder PNG bytes."""

    Format_ARGB32 = 1

    def __init__(self, width: int, height: int, fmt: int) -> None:
        self.width = width
        self.height = height

    def fill(self, color: int) -> None:
        self.color = color

    def save(self, path: str) -> bool:
        Path(path).write_bytes(
            b"\\x89PNG\\r\\n\\x1a" + f"{self.width}x{self.height}".encode("ascii")
        )
        return True


class QPdfWriter:
    """Collects one page per sheet and writes ``/Type /Pages /Count N``."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.pages: list[str] = []
        self.size: object = None
        self.active = False

    def setResolution(self, dpi: int) -> None:
        self.dpi = dpi

    def setPageMargins(self, margins: object, unit: int) -> None:
        self.margins = margins

    def setPageSize(self, size: object) -> None:
        self.size = size

    def begin(self) -> None:
        self.pages = [self.box()]
        self.active = True

    def newPage(self) -> bool:
        if not self.active:
            return False
        self.pages.append(self.box())
        return True

    def box(self) -> str:
        size = self.size.size
        return f"[0 0 {size.width:g} {size.height:g}]"

    def end(self) -> None:
        if not self.active:
            return
        self.active = False
        body = "".join(f"<< /Type /Page /MediaBox {box} >>\\n" for box in self.pages)
        Path(self.path).write_bytes(
            b"%PDF-1.4\\n1 0 obj\\n<< /Type /Pages /Count "
            + str(len(self.pages)).encode("ascii")
            + b" >>\\nendobj\\n"
            + body.encode("ascii")
            + b"trailer\\n"
        )


class QPainter:
    """Begins the writer it targets and ends it, as QPainter does."""

    def __init__(self, target: object) -> None:
        self.target = target
        if isinstance(target, QPdfWriter):
            target.begin()

    def render(self, renderer: object) -> None:
        return None

    def end(self) -> None:
        if isinstance(self.target, QPdfWriter):
            self.target.end()


_current: "QGuiApplication | None" = None


class QGuiApplication:
    """The application the renderer needs; reused once created."""

    def __init__(self, argv: list[str]) -> None:
        global _current
        _current = self

    @staticmethod
    def instance() -> "QGuiApplication | None":
        return _current
'''

STUB_FREECADCMD = """#!{python}
import os
import runpy
import sys

if "--version" in sys.argv[1:]:
    print(os.environ.get("STUB_FREECAD_VERSION", "FreeCAD 1.1.4"))
    sys.exit(0)
sys.path.insert(0, os.environ["STUB_FREECAD"])
wrapper = sys.argv[1]
sys.argv = [wrapper, *sys.argv[2:]]
runpy.run_path(wrapper, run_name="__main__")
sys.exit(0)
"""

WSLPATH_STUB = """#!/bin/sh
echo "$2" >> "$WSLPATH_LOG"
echo "$2"
"""

GUION_LOG = """import json
import os
import sys
from pathlib import Path

Path(os.environ["GUION_LOG"]).write_text(json.dumps(sys.argv))
prefix = sys.argv[1]
"""

GUION_ONE_SHEET = (
    GUION_LOG
    + """Path(f"{prefix}-01.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm">'
    '<rect x="10" y="10" width="400" height="277"/></svg>',
    encoding="utf-8",
)
"""
)

GUION_TWO_SHEETS = (
    GUION_LOG
    + """Path(f"{prefix}-01.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm">'
    "<rect /></svg>",
    encoding="utf-8",
)
Path(f"{prefix}-02.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm">'
    "<rect /></svg>",
    encoding="utf-8",
)
"""
)

GUION_NO_SHEET = GUION_LOG

GUION_GAP = (
    GUION_LOG
    + """Path(f"{prefix}-01.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm">'
    "<rect /></svg>",
    encoding="utf-8",
)
Path(f"{prefix}-03.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm">'
    "<rect /></svg>",
    encoding="utf-8",
)
"""
)

GUION_NO_MM = (
    GUION_LOG
    + """Path(f"{prefix}-01.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg"><rect /></svg>',
    encoding="utf-8",
)
"""
)

GUION_BAD_SVG = (
    GUION_LOG
    + """Path(f"{prefix}-01.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm">'
    "INVALID</svg>",
    encoding="utf-8",
)
"""
)

FAILING_GUION = 'raise RuntimeError("boom")\n'


def _stubs(tmp_path: Path) -> tuple[Path, Path]:
    """The stub bin directory and the stub FreeCAD module directory."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = {
        "freecadcmd.exe": STUB_FREECADCMD.replace("{python}", sys.executable),
        "wslpath": WSLPATH_STUB,
    }
    for name, text in scripts.items():
        path = bin_dir / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)
    freecad = tmp_path / "stub-freecad"
    freecad.mkdir()
    (freecad / "FreeCAD.py").write_text(STUB_FREECAD, encoding="utf-8")
    qt = freecad / "PySide6"
    qt.mkdir()
    (qt / "__init__.py").write_text(STUB_QT_INIT, encoding="utf-8")
    (qt / "QtCore.py").write_text(STUB_QT_CORE, encoding="utf-8")
    (qt / "QtSvg.py").write_text(STUB_QT_SVG, encoding="utf-8")
    (qt / "QtGui.py").write_text(STUB_QT_GUI, encoding="utf-8")
    return bin_dir, freecad


def _environment(tmp_path: Path, bin_dir: Path, freecad: Path, **extra: str) -> dict[str, str]:
    env = {
        **os.environ,
        "PATH": str(bin_dir),
        "STUB_FREECAD": str(freecad),
        "WSLPATH_LOG": str(tmp_path / "wslpath.log"),
        "GUION_LOG": str(tmp_path / "guion.log"),
    }
    env.pop("FACET_HOME", None)
    env.pop("PYTHONPATH", None)
    env.update(extra)
    env["FREECAD_EXE"] = extra.get("FREECAD_EXE", str(bin_dir / "freecadcmd.exe"))
    return env


def _piece(tmp_path: Path, guion: str = GUION_ONE_SHEET) -> tuple[Path, Path, Path]:
    piece = tmp_path / "piece"
    piece.mkdir()
    script = piece / f"{PDF_NAME}.py"
    script.write_text(guion, encoding="utf-8")
    part = piece / "pieza.step"
    part.write_bytes(b"STEP-stub")
    return piece, script, part


def _out(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    return out


def _request(verb: str, out: Path, piece: Path, **fields: Any) -> dict[str, Any]:
    inputs = fields.pop("inputs", {})
    request: dict[str, Any] = {
        "protocol": 1,
        "verb": verb,
        "capability": "freecad.plano",
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(piece),
        "models": {},
        "assets": fields.pop("assets", []),
    }
    request.update(fields)
    return request


def _call(
    tmp_path: Path, verb: str, request: dict[str, Any], env: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], Any]:
    input_path = tmp_path / f"{verb}.request.json"
    result_path = tmp_path / f"{verb}.result.json"
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
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    return done, result


def _run(tmp_path: Path, out: Path, piece: Path, env: dict[str, str], guion: str = GUION_ONE_SHEET):
    inputs = {"guion": f"{PDF_NAME}.py", "pieza": "pieza.step"}
    piece.joinpath(f"{PDF_NAME}.py").write_text(guion, encoding="utf-8")
    return _call(tmp_path, "run", _request("run", out, piece, inputs=inputs), env)


def test_run_converts_the_arguments_and_writes_the_preview(tmp_path: Path) -> None:
    """The lab's conversion, the guion's argv and the core paged preview shape."""
    bin_dir, freecad = _stubs(tmp_path)
    piece, script, part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)

    done, result = _run(tmp_path, out, piece, env)

    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    asset = result["assets"][0]
    assert (asset["file"], asset["name"], asset["kind"], asset["mime"]) == (
        f"{PDF_NAME}.pdf",
        PDF_NAME,
        "document",
        "application/pdf",
    )
    assert asset["properties"] == {"page_count": 1}
    sheet = out / f"{PDF_NAME}-01.svg"
    assert sheet.is_file()
    assert asset["inputs"] == [str(script), str(part)]
    assert (out / f"{PDF_NAME}.pdf").is_file()

    converted = (tmp_path / "wslpath.log").read_text(encoding="utf-8").splitlines()
    assert any(line.endswith(f"{PDF_NAME}.py") for line in converted)
    assert any(line.endswith("pieza.step") for line in converted)
    assert any(line.endswith("out") for line in converted)

    argv = json.loads((tmp_path / "guion.log").read_text(encoding="utf-8"))
    assert argv[0] == str(script)
    assert argv[1] == str(out / PDF_NAME)
    assert argv[2] == str(part)

    data = json.loads((out / f"{PDF_NAME}.pdf.preview.json").read_text(encoding="utf-8"))
    assert set(data) == PREVIEW_KEYS
    assert data["preview"] == 1
    assert data["kind"] == "document"
    assert data["page_count"] == 1
    assert data["pages"] == PAGE_NAMES_ONE
    assert all((out / name).is_file() for name in data["pages"])


def test_run_renders_two_sheets_into_two_pages(tmp_path: Path) -> None:
    """Two consecutive sheets become a two-page PDF and two PNGs."""
    bin_dir, freecad = _stubs(tmp_path)
    piece, script, part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)

    done, result = _run(tmp_path, out, piece, env, GUION_TWO_SHEETS)

    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    asset = result["assets"][0]
    assert asset["properties"] == {"page_count": 2}
    assert asset["inputs"] == [str(script), str(part)]
    assert (out / f"{PDF_NAME}-01.svg").is_file()
    assert (out / f"{PDF_NAME}-02.svg").is_file()
    raw = (out / f"{PDF_NAME}.pdf").read_bytes()
    assert b"/Type /Pages" in raw and f"/Count {PAGE_COUNT_TWO}".encode() in raw
    assert b"/MediaBox [0 0 420 297]" in raw
    assert b"/MediaBox [0 0 297 210]" in raw
    assert (out / "preview" / "page-01.png").read_bytes().endswith(b"2480x1754")
    assert (out / "preview" / "page-02.png").read_bytes().endswith(b"1754x1240")
    data = json.loads((out / f"{PDF_NAME}.pdf.preview.json").read_text(encoding="utf-8"))
    assert data["page_count"] == PAGE_COUNT_TWO
    assert data["pages"] == PAGE_NAMES_TWO
    assert all((out / name).is_file() for name in data["pages"])


def test_run_without_any_sheet_names_the_missing_first_sheet(tmp_path: Path) -> None:
    """A guion that writes no sheet fails before any rendering."""
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)

    done, result = _run(tmp_path, out, piece, env, GUION_NO_SHEET)

    assert done.returncode != 0
    assert result is None
    assert f"guion wrote no {PDF_NAME}-01.svg" in done.stdout + done.stderr


def test_run_with_a_numbering_gap_names_the_missing_sheet(tmp_path: Path) -> None:
    """Sheets must run consecutive from 01: -01 and -03 leave -02 missing."""
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)

    done, result = _run(tmp_path, out, piece, env, GUION_GAP)

    assert done.returncode != 0
    assert result is None
    assert f"sheet {PDF_NAME}-02.svg is missing" in done.stdout + done.stderr


def test_run_with_a_sheet_missing_its_mm_size_fails(tmp_path: Path) -> None:
    """Every sheet carries width and height in millimetres on its svg tag."""
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)

    done, result = _run(tmp_path, out, piece, env, GUION_NO_MM)

    assert done.returncode != 0
    assert result is None
    assert "the sheet needs width and height in mm" in done.stdout + done.stderr


def test_run_with_a_sheet_qt_cannot_read_fails(tmp_path: Path) -> None:
    """A sheet the renderer rejects stops the run with its own message."""
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)

    done, result = _run(tmp_path, out, piece, env, GUION_BAD_SVG)

    assert done.returncode != 0
    assert result is None
    assert "Qt cannot read this SVG" in done.stdout + done.stderr


def test_run_surfaces_a_guion_failure_instead_of_a_swallowed_zero(tmp_path: Path) -> None:
    """freecadcmd exits 0 on a raise; the wrapper's exit 1 must reach the launcher."""
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)

    done, result = _run(tmp_path, out, piece, env, FAILING_GUION)

    assert done.returncode != 0
    assert result is None
    assert "boom" in done.stdout + done.stderr
    assert "freecadcmd exited" in done.stdout + done.stderr


def test_verify_counts_the_rendered_pages(tmp_path: Path) -> None:
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)
    _done, _result = _run(tmp_path, out, piece, env, GUION_TWO_SHEETS)

    request = _request("verify", out, piece, assets=[str(out / f"{PDF_NAME}.pdf")])
    done, result = _call(tmp_path, "verify", request, env)

    assert done.returncode == 0, done.stdout + done.stderr
    assert result["assets"][0] == {
        "file": f"{PDF_NAME}.pdf",
        "passed": True,
        "metrics": {"page_count": 2},
        "thresholds": {"page_count_min": 1},
        "verifier": "pdf-pages",
    }


def test_verify_counts_the_pdf_pages_when_the_pngs_are_gone(tmp_path: Path) -> None:
    """Without rendered PNGs the count comes from the PDF's own /Count."""
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)
    _done, _result = _run(tmp_path, out, piece, env, GUION_TWO_SHEETS)
    for page in (out / "preview").glob("page-*.png"):
        page.unlink()

    request = _request("verify", out, piece, assets=[str(out / f"{PDF_NAME}.pdf")])
    done, result = _call(tmp_path, "verify", request, env)

    assert done.returncode == 0, done.stdout + done.stderr
    assert result["assets"][0]["metrics"] == {"page_count": 2}
    assert result["assets"][0]["verifier"] == "pdf-pages"


def test_preview_rewrites_the_shape_from_the_pngs_run_wrote(tmp_path: Path) -> None:
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)
    _done, _result = _run(tmp_path, out, piece, env, GUION_TWO_SHEETS)
    (out / f"{PDF_NAME}.pdf.preview.json").unlink()

    request = _request("preview", out, piece, assets=[str(out / f"{PDF_NAME}.pdf")])
    done, result = _call(tmp_path, "preview", request, env)

    assert done.returncode == 0, done.stdout + done.stderr
    assert result["assets"][0] == {
        "file": f"{PDF_NAME}.pdf",
        "preview": f"{PDF_NAME}.pdf.preview.json",
        "images": [],
    }
    data = json.loads((out / f"{PDF_NAME}.pdf.preview.json").read_text(encoding="utf-8"))
    assert set(data) == PREVIEW_KEYS
    assert data["pages"] == PAGE_NAMES_TWO
    assert all((out / name).is_file() for name in data["pages"])


def test_preview_without_pngs_fails_telling_the_user_to_run_again(tmp_path: Path) -> None:
    """No page PNGs beside the PDF means the piece was never run: say so."""
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)
    pdf = out / f"{PDF_NAME}.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Pages /Count 1 >>\nendobj\n")

    request = _request("preview", out, piece, assets=[str(pdf)])
    done, result = _call(tmp_path, "preview", request, env)

    assert done.returncode != 0
    assert result is None
    assert f"{PDF_NAME}.pdf: page PNGs are written by run" in done.stdout + done.stderr


def test_doctor_reports_the_exact_missing_host_key_and_fix(tmp_path: Path) -> None:
    """No config, no env, no PATH: the message names the key and the fix."""
    bin_dir, _freecad = _stubs(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    env = _environment(tmp_path, bin_dir, _freecad, PATH=str(empty))
    env.pop("FREECAD_EXE", None)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)

    done, result = _call(tmp_path, "doctor", _request("doctor", out, piece), env)

    assert done.returncode == 0, done.stdout + done.stderr
    check = result["checks"][0]
    assert check["name"] == "freecad"
    assert check["ok"] is False
    assert check["detail"] == NOT_FOUND
    assert check["fix"] == FIX


def test_doctor_passes_the_installed_version(tmp_path: Path) -> None:
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)

    done, result = _call(tmp_path, "doctor", _request("doctor", out, piece), env)

    assert done.returncode == 0, done.stdout + done.stderr
    check = result["checks"][0]
    assert check["ok"] is True
    assert "1.1.4" in check["detail"]
    assert check["fix"] == ""


def test_doctor_reports_a_host_older_than_the_minimum(tmp_path: Path) -> None:
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad, STUB_FREECAD_VERSION="FreeCAD 1.0.0")

    done, result = _call(tmp_path, "doctor", _request("doctor", out, piece), env)

    assert done.returncode == 0, done.stdout + done.stderr
    check = result["checks"][0]
    assert check["ok"] is False
    assert "1.0.0 found, needs 1.1.4+" in check["detail"]
    assert check["fix"] == FIX


def test_a_bare_argument_is_kept_and_only_slashed_paths_are_converted() -> None:
    """The lab's rule: no slash means a value, not a path."""
    spec = importlib.util.spec_from_file_location("freecad_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._convert_argument("escuadra", "freecadcmd.exe") == "escuadra"
    assert module._convert_argument("/tmp/x", "freecadcmd") == "/tmp/x"


def test_collect_sheets_reads_mm_sizes_and_rejects_a_ragged_run(tmp_path: Path) -> None:
    """The sheet contract without a host: sizes parse, gaps and units fail."""
    spec = importlib.util.spec_from_file_location("freecad_runner_sheets", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    prefix = str(tmp_path / "plano")
    (tmp_path / "plano-01.svg").write_text(
        '<svg width="420mm" height="297mm"><rect /></svg>', encoding="utf-8"
    )
    (tmp_path / "plano-02.svg").write_text(
        '<svg width="297.0mm" height="210.0mm"><rect /></svg>', encoding="utf-8"
    )
    sheets = module._collect_sheets(prefix, "plano")
    assert [(sheet.width_mm, sheet.height_mm) for sheet in sheets] == [
        (420.0, 297.0),
        (297.0, 210.0),
    ]

    (tmp_path / "plano-02.svg").unlink()
    (tmp_path / "plano-03.svg").write_text(
        '<svg width="420mm" height="297mm"><rect /></svg>', encoding="utf-8"
    )
    try:
        module._collect_sheets(prefix, "plano")
    except RuntimeError as exc:
        assert str(exc) == "sheet plano-02.svg is missing"
    else:  # pragma: no cover
        raise AssertionError("a numbering gap must fail")

    (tmp_path / "plano-03.svg").unlink()
    (tmp_path / "plano-02.svg").write_text("<svg><rect /></svg>", encoding="utf-8")
    try:
        module._collect_sheets(prefix, "plano")
    except RuntimeError as exc:
        assert "the sheet needs width and height in mm" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a sheet without mm sizes must fail")


def test_page_count_reads_the_pdfs_own_pages_object(tmp_path: Path) -> None:
    """Without PNGs the count is the /Count of the /Type /Pages object."""
    spec = importlib.util.spec_from_file_location("freecad_runner_pages", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    pdf = tmp_path / "dibujo.pdf"
    pdf.write_bytes(
        b"%PDF-1.4\n1 0 obj\n<< /Type /Pages /Count "
        + str(PAGE_COUNT_THREE).encode()
        + b" >>\nendobj\n"
    )
    assert module._page_count(pdf) == PAGE_COUNT_THREE

    pdf.write_bytes(b"%PDF-1.4\nno pages object here\n")
    try:
        module._page_count(pdf)
    except RuntimeError as exc:
        assert str(exc) == "cannot count the pages of dibujo.pdf"
    else:  # pragma: no cover
        raise AssertionError("a PDF without a pages object must fail")
