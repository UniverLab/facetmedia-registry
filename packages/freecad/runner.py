"""The freecad package runner: workshop drawings from a part, scripted FreeCAD.

facet drives a ``host-app`` package through the host binary: it launches
``freecadcmd freecad_run.py --pass runner.py <verb> --input <request>
--result <result>``, so this entry runs inside FreeCAD's Python and its four
verbs use what FreeCAD ships. ``run`` executes the piece's ``script`` with
``sys.argv`` set to ``[script, <out_dir>/<name>, part]`` (the lab's output
prefix convention), requires the ``<name>-NN.svg`` sheets it writes, renders
them into ``<name>.pdf`` with FreeCAD's bundled PySide6 (``QSvgRenderer``
into ``QPdfWriter``) and returns the PDF plus one image asset per sheet, in
page order. ``verify`` checks the PDF's page count and each sheet's
millimetre size, ``preview`` renders the page PNGs from the sheets beside
the PDF (or describes an SVG sheet itself), and ``doctor`` reports the
host application, TechDraw and Qt.

Started with plain Python — ``python runner.py run ...``, as the tests and a
manual paste-back do — the same entry is the launcher the lab's
``tools/freecad.sh`` is: it resolves the host (``freecad.path``, then
``FREECAD_EXE``, then ``PATH``), converts every slash-bearing argument with
``wslpath -w`` when the binary is a ``.exe``, drives it through the package's
``freecad_run.py`` wrapper (freecadcmd exits 0 when a script raises), and
retries once only on a WSL interop failure (``UtilAcceptVsock``); anything else
fails with the tail of its output.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import runpy
import shutil
import subprocess
import sys
import tomllib
import traceback
from pathlib import Path
from typing import Any, NamedTuple

#: The host application's manifest values, repeated where the runner needs them.
APP = "freecad"
CONFIG_KEY = "freecad.path"
ENV = "FREECAD_EXE"
MIN_VERSION = "1.1.4"
CAPABILITY = "freecad.drawing"
#: What the doctor calls the fix a missing host application needs.
FIX = f"facet config set {CONFIG_KEY} /path/to/{APP}"
NOT_FOUND = (
    f"{APP} {MIN_VERSION}+ not found (config {CONFIG_KEY}, env {ENV}, PATH all empty); fix: {FIX}"
)
#: The PATH names the host binary may answer to.
PATH_NAMES = ("freecadcmd", "freecadcmd.exe", "freecad", "freecad.exe")
#: The wrapper that turns freecadcmd's swallowed failure into exit 1.
WRAPPER = "freecad_run.py"
PASS_FLAG = "--pass"
#: The verbs that always need the host binary; preview launches it only beside a PDF.
NEEDS_HOST = ("run",)
#: The only failure worth a second launch: WSL interop failing the first accept.
INTEROP_MARKER = "UtilAcceptVsock"
ATTEMPTS = 2
TAIL_CHARS = 2000
WSLPATH_TIMEOUT_S = 10.0
PROBE_TIMEOUT_S = 30.0
#: Preview PNGs land here, under the run's output dir.
PREVIEW_DIR = "preview"
#: The preview PNGs' resolution: 150 dpi of each sheet's millimetre size.
PNG_DPI = 150
#: The PDF's resolution, which only fixes its coordinate system.
PDF_DPI = 300
VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")
#: The ``/Count N`` of the ``/Type /Pages`` object, read from the PDF bytes.
PAGES_RE = re.compile(rb"/Type\s*/Pages.*?/Count\s+(\d+)", re.DOTALL)
#: The ``-NN`` suffix of a ``<name>-NN.svg`` sheet file.
SHEET_NUMBER_RE = re.compile(r"-(\d+)\.svg\Z")
#: The sheet's ``<svg>`` tag, carrying ``width`` and ``height`` in millimetres.
SHEET_TAG_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
#: One ``width="420mm"`` or ``height="297mm"`` attribute of the sheet's tag.
SHEET_SIZE_RE = re.compile(r"(width|height)\s*=\s*[\"'](\d+(?:\.\d+)?)mm[\"']")
UNSAFE_NAME = re.compile(r"[^a-z0-9-]+")
#: ``C:\`` or ``C:/``: a path the Windows build already understands.
DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")
#: ``("/", "mnt", "<drive>")``: the WSL mount point's own components.
MOUNT_PARTS = 3
#: ``("", "", "server", "share")``: a UNC path's own leading components.
UNC_PARTS = 4
#: The UNC mount point of WSL's filesystem, discovered from the request's path.
_UNC_ROOT: list[str] = [""]


def main(argv: list[str] | None = None) -> int:
    """Run the verb named on the command line, inside FreeCAD or beside it."""
    verb, input_path, result_path = _parse_argv(sys.argv[1:] if argv is None else argv)
    request = json.loads(Path(input_path).read_text(encoding="utf-8"))
    _remember_root(str(input_path))
    if request.get("capability") != CAPABILITY:
        raise ValueError(f"unknown capability: {request.get('capability')}")
    return _dispatch(verb, request, input_path, result_path)


def _dispatch(verb: str, request: dict[str, Any], input_path: Path, result_path: Path) -> int:
    """The in-FreeCAD verbs, or the launcher when the host is not imported."""
    freecad = _freecad()
    if freecad is None and verb == "doctor":
        if request.get("depth") == "full" and _host_check()["ok"]:
            _launch_host(verb, input_path, result_path)
            return 0
        result = _doctor(request)
    elif freecad is None and _needs_launch(verb, request):
        _launch_host(verb, input_path, result_path)
        return 0
    else:
        table = {"run": _run, "verify": _verify, "preview": _preview, "doctor": _doctor}
        if verb not in table:
            raise ValueError(f"unknown verb: {verb}")
        result = table[verb](request)
    Path(result_path).write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


def _parse_argv(argv: list[str]) -> tuple[str, Path, Path]:
    """``(verb, request, result)`` from ``VERB --input P --result P``."""
    rest = list(argv)
    if "--" in rest:
        rest = rest[rest.index("--") + 1 :]
    if not rest:
        raise ValueError("usage: [--] VERB --input REQUEST --result RESULT")
    verb, *tokens = rest
    values: dict[str, str] = {}
    position = 0
    while position < len(tokens):
        flag = tokens[position]
        if flag not in {"--input", "--result"} or position + 1 >= len(tokens):
            raise ValueError(f"usage: [--] VERB --input REQUEST --result RESULT (got {flag!r})")
        values[flag] = tokens[position + 1]
        position += 2
    missing = [flag for flag in ("--input", "--result") if flag not in values]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    return verb, Path(values["--input"]), Path(values["--result"])


def _freecad() -> Any:
    """FreeCAD's module when this entry runs inside freecadcmd, else ``None``."""
    try:
        return __import__("FreeCAD")
    except ImportError:
        return None


# --- freecad.drawing: the script, its PDF and its pages.


def _run(request: dict[str, Any]) -> dict[str, Any]:
    """Execute the script on the part and report the drawing it wrote."""
    params = dict(request.get("inputs") or {})
    piece_dir = str(request.get("piece_dir") or "")
    script = _resolve(_required(params, "script"), piece_dir)
    part = _resolve(_required(params, "part"), piece_dir)
    name = _asset_name(script)
    windows = _on_windows()
    out_dir = _host_path(str(request["out_dir"]), windows)
    prefix = posixpath.join(out_dir, name)
    _clear_sheets(prefix)
    _execute(_host_path(script, windows), prefix, _host_path(part, windows))
    pdf = Path(f"{prefix}.pdf")
    sheets = _collect_sheets(prefix, name)
    _write_pdf(sheets, pdf)
    assets = [
        {
            "file": pdf.name,
            "name": name,
            "kind": "document",
            "mime": "application/pdf",
            "properties": {"page_count": len(sheets)},
            "params": params,
            "seed": None,
            "inputs": [script, part],
        }
    ]
    assets.extend(
        _sheet_asset(sheet, number, params, script, part)
        for number, sheet in enumerate(sheets, start=1)
    )
    return {"tool": _tool(), "assets": assets}


def _needs_launch(verb: str, request: dict[str, Any]) -> bool:
    """Whether the launcher must drive the host: run always, preview beside a PDF."""
    if verb in NEEDS_HOST:
        return True
    if verb != "preview":
        return False
    return any(str(item).lower().endswith(".pdf") for item in request.get("assets") or [])


def _required(params: dict[str, Any], key: str) -> str:
    """One required path input as non-empty text; a piece missing it is refused."""
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key}: required")
    return value


def _resolve(value: str, piece_dir: str) -> str:
    """A path resolved relative to the piece, or left alone when absolute."""
    if _is_windows(value) or value.startswith("/"):
        return value
    return posixpath.join(piece_dir, value)


def _asset_name(script: str) -> str:
    """``dibujo.py`` -> ``dibujo``: the asset base name, sanitized."""
    base = script.replace("\\", "/")
    stem = posixpath.splitext(posixpath.basename(base))[0].lower()
    safe = UNSAFE_NAME.sub("-", stem).strip("-")
    return safe or "drawing"


def _execute(script: str, prefix: str, part: str) -> None:
    """Run the script with the lab's argv and surface any failure loudly."""
    sys.argv = [script, prefix, part]
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as exit_request:
        code = exit_request.code
        if code not in (None, 0):
            raise RuntimeError(f"script exited {code}") from None
    except BaseException:
        raise RuntimeError(f"script failed:\n{traceback.format_exc()}") from None


def _tool() -> dict[str, str]:
    """The manifest's tool identity, so records name the real tool."""
    manifest = tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _sheet_asset(
    sheet: Sheet, number: int, params: dict[str, Any], script: str, part: str
) -> dict[str, Any]:
    """One sheet as a run asset: an image in page order with its mm size."""
    return {
        "file": sheet.path.name,
        "name": sheet.path.stem,
        "kind": "image",
        "mime": "image/svg+xml",
        "properties": {"page": number, "width_mm": sheet.width_mm, "height_mm": sheet.height_mm},
        "params": params,
        "seed": None,
        "inputs": [script, part],
    }


# --- the sheets: the script's SVGs, rendered with FreeCAD's own Qt.


#: The Qt application the sheet renderer needs; held for the process's life.
_QT_APP: list[Any] = []


class Sheet(NamedTuple):
    """One script sheet: its file and its size in millimetres."""

    path: Path
    width_mm: float
    height_mm: float


def _clear_sheets(prefix: str) -> None:
    """Drop the sheets an earlier run left, so this run's pages are its own."""
    parent = Path(prefix).parent
    if not parent.is_dir():
        return
    for stale in parent.glob(f"{Path(prefix).name}-*.svg"):
        if SHEET_NUMBER_RE.search(stale.name):
            stale.unlink(missing_ok=True)


def _collect_sheets(prefix: str, name: str) -> list[Sheet]:
    """The script's ``<prefix>-NN.svg`` sheets, consecutive from 01."""
    first = Path(f"{prefix}-01.svg")
    if not first.is_file():
        raise RuntimeError(f"script wrote no {name}-01.svg")
    sheets: list[Sheet] = []
    number = 1
    while True:
        path = Path(f"{prefix}-{number:02d}.svg")
        if not path.is_file():
            break
        sheets.append(_read_sheet(path))
        number += 1
    parent = Path(prefix).parent
    if parent.is_dir():
        stem = Path(prefix).name
        for candidate in parent.glob(f"{stem}-*.svg"):
            match = SHEET_NUMBER_RE.search(candidate.name)
            if match and candidate.is_file() and int(match.group(1)) >= number:
                raise RuntimeError(f"sheet {stem}-{number:02d}.svg is missing")
    return sheets


def _read_sheet(path: Path) -> Sheet:
    """One sheet with its millimetre size from the ``<svg>`` tag."""
    tag = SHEET_TAG_RE.search(path.read_text(encoding="utf-8"))
    sizes = dict(SHEET_SIZE_RE.findall(tag.group(0))) if tag else {}
    if "width" not in sizes or "height" not in sizes:
        raise RuntimeError(f"{path}: the sheet needs width and height in mm")
    return Sheet(path, float(sizes["width"]), float(sizes["height"]))


def _qt_modules() -> tuple[Any, Any, Any]:
    """FreeCAD's bundled Qt, with an offscreen application ready to render."""
    from PySide6 import QtCore, QtGui, QtSvg  # noqa: PLC0415

    windows = _on_windows()
    if not windows and "QT_QPA_PLATFORM" not in os.environ and not os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QtGui.QGuiApplication.instance()
    if app is None:
        app = QtGui.QGuiApplication(["facet"])
        _QT_APP.append(app)
    return QtCore, QtGui, QtSvg


def _sheet_renderers(sheets: list[Sheet], qt_core: Any, qt_svg: Any) -> list[Any]:
    """One valid renderer per sheet; a sheet Qt rejects stops the verb."""
    renderers: list[Any] = []
    for sheet in sheets:
        renderer = qt_svg.QSvgRenderer(qt_core.QByteArray(sheet.path.read_bytes()))
        if not renderer.isValid():
            raise RuntimeError(f"{sheet.path}: Qt cannot read this SVG")
        renderers.append(renderer)
    return renderers


def _write_pdf(sheets: list[Sheet], pdf: Path) -> None:
    """Render every sheet into one PDF, one millimetre page per sheet."""
    qt_core, qt_gui, qt_svg = _qt_modules()
    renderers = _sheet_renderers(sheets, qt_core, qt_svg)
    writer = qt_gui.QPdfWriter(_host_path(str(pdf), _on_windows()))
    writer.setResolution(PDF_DPI)
    writer.setPageMargins(qt_core.QMarginsF(0, 0, 0, 0), qt_gui.QPageLayout.Millimeter)
    writer.setPageSize(_page_size(qt_core, qt_gui, sheets[0]))
    painter = qt_gui.QPainter(writer)
    for position, (sheet, renderer) in enumerate(zip(sheets, renderers, strict=True)):
        if position:
            writer.setPageSize(_page_size(qt_core, qt_gui, sheet))
            writer.newPage()
        renderer.render(painter)
    painter.end()


def _render_pngs(sheets: list[Sheet], folder: Path) -> list[str]:
    """Render each sheet to ``page-NN.png`` under the folder; return their paths."""
    qt_core, qt_gui, qt_svg = _qt_modules()
    renderers = _sheet_renderers(sheets, qt_core, qt_svg)
    windows = _on_windows()
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    names: list[str] = []
    for index, (sheet, renderer) in enumerate(zip(sheets, renderers, strict=True), start=1):
        image = qt_gui.QImage(
            round(sheet.width_mm * PNG_DPI / 25.4),
            round(sheet.height_mm * PNG_DPI / 25.4),
            qt_gui.QImage.Format_ARGB32,
        )
        image.fill(0xFFFFFFFF)
        painter = qt_gui.QPainter(image)
        renderer.render(painter)
        painter.end()
        name = f"page-{index:02d}.png"
        target = _host_path(str(folder / name), windows)
        if not image.save(target):
            raise RuntimeError(f"Qt could not write {target}")
        names.append(name)
    return [f"{folder.name}/{name}" for name in names]


def _page_size(qt_core: Any, qt_gui: Any, sheet: Sheet) -> Any:
    """A sheet's millimetre size as the QPageSize of its PDF page."""
    return qt_gui.QPageSize(
        qt_core.QSizeF(sheet.width_mm, sheet.height_mm), qt_gui.QPageSize.Millimeter
    )


def _write_preview(pdf: Path, pages: list[str], out_dir: Path) -> str:
    """Write the core document preview shape beside the PDF."""
    count = len(pages)
    plural = "" if count == 1 else "s"
    data = {
        "preview": 1,
        "kind": "document",
        "summary": f"{pdf.name} · {count} page{plural}",
        "page_count": count,
        "pages": pages,
    }
    name = f"{pdf.name}.preview.json"
    (out_dir / name).write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return name


def _preview(request: dict[str, Any]) -> dict[str, Any]:
    """Preview each placed asset: a PDF renders its sheets, an SVG describes itself."""
    out_dir = Path(_host_path(str(request["out_dir"]), _on_windows()))
    entries: list[dict[str, Any]] = []
    for item in request.get("assets") or []:
        asset = Path(_host_path(str(item), _on_windows()))
        if asset.suffix.lower() == ".pdf":
            prefix = _pdf_sheets(asset)
            sheets = _collect_sheets(prefix, asset.stem)
            pages = _render_pngs(sheets, out_dir / PREVIEW_DIR)
            name = _write_preview(asset, pages, out_dir)
        else:
            name = _preview_sheet(request, asset, out_dir)
        entries.append({"file": asset.name, "preview": name, "images": []})
    return {"assets": entries}


def _pdf_sheets(asset: Path) -> str:
    """The sheet prefix beside a placed PDF; a run that left none must run again."""
    stem = asset.stem
    if not (asset.parent / f"{stem}-01.svg").is_file():
        missing = f"{asset.name}: its sheets {stem}-NN.svg are missing; run the piece again"
        raise RuntimeError(missing)
    return str(asset.parent / stem)


def _preview_sheet(request: dict[str, Any], asset: Path, out_dir: Path) -> str:
    """Write the image preview of one placed sheet; a browser shows the SVG itself."""
    sheet = _read_sheet(asset)
    page = _sheet_page(asset)
    width = round(sheet.width_mm * PNG_DPI / 25.4)
    height = round(sheet.height_mm * PNG_DPI / 25.4)
    data = {
        "preview": 1,
        "kind": "image",
        "summary": f"{asset.name} · page {page:02d} · {sheet.width_mm:g}×{sheet.height_mm:g} mm",
        "name": asset.stem,
        "prompt": _sheet_prompt(request, asset.name),
        "seed": 0,
        "width": width,
        "height": height,
    }
    name = f"{asset.name}.preview.json"
    (out_dir / name).write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return name


def _sheet_page(asset: Path) -> int:
    """The page number in a ``<name>-NN.svg`` sheet file; sheets without one are first."""
    match = SHEET_NUMBER_RE.search(asset.name)
    return int(match.group(1)) if match else 1


def _sheet_prompt(request: dict[str, Any], filename: str) -> str:
    """The script and part that drew the sheet, or the sheet itself when unknown."""
    inputs = request.get("inputs") or {}
    script = inputs.get("script")
    part = inputs.get("part")
    if isinstance(script, str) and script.strip() and isinstance(part, str) and part.strip():
        return f"{_basename(script)} · {_basename(part)}"
    return f"freecad sheet {filename}"


def _basename(value: str) -> str:
    """The file name of a POSIX or Windows path."""
    return value.replace("\\", "/").split("/")[-1]


def _verify(request: dict[str, Any]) -> dict[str, Any]:
    """One verdict per asset: a PDF counts pages, a sheet carries mm sizes."""
    verdicts: list[dict[str, Any]] = []
    for item in request.get("assets") or []:
        asset = Path(_host_path(str(item), _on_windows()))
        if asset.suffix.lower() == ".pdf":
            verdicts.append(_verdict(asset))
        else:
            verdicts.append(_svg_verdict(asset))
    return {"assets": verdicts}


def _verdict(pdf: Path) -> dict[str, Any]:
    """A PDF's page count, from its own ``/Count``."""
    count = _page_count(pdf)
    return {
        "file": pdf.name,
        "passed": count > 0,
        "metrics": {"page_count": count},
        "thresholds": {"page_count_min": 1},
        "verifier": "pdf-pages",
    }


def _svg_verdict(svg: Path) -> dict[str, Any]:
    """A sheet passes when its ``<svg>`` tag carries width and height in mm."""
    try:
        sheet = _read_sheet(svg)
    except RuntimeError as exc:
        return {
            "file": svg.name,
            "passed": False,
            "metrics": {"error": str(exc)},
            "thresholds": {},
            "verifier": "svg-sheet",
        }
    return {
        "file": svg.name,
        "passed": True,
        "metrics": {"width_mm": sheet.width_mm, "height_mm": sheet.height_mm},
        "thresholds": {},
        "verifier": "svg-sheet",
    }


def _page_count(pdf: Path) -> int:
    """The PDF's own ``/Type /Pages`` count."""
    try:
        raw = pdf.read_bytes()
    except OSError:
        raise RuntimeError(f"cannot count the pages of {pdf.name}") from None
    match = PAGES_RE.search(raw)
    if match is None:
        raise RuntimeError(f"cannot count the pages of {pdf.name}")
    return int(match.group(1))


# --- the doctor: the host application and TechDraw.


def _doctor(request: dict[str, Any]) -> dict[str, Any]:
    """The host application, at least 1.1.4; TechDraw and Qt on a full probe."""
    check = _host_check()
    checks = [check]
    if request.get("depth") == "full" and check["ok"] and _freecad() is not None:
        checks.append(_techdraw_check())
        checks.append(_qt_check())
    return {"checks": checks}


def _host_check() -> dict[str, Any]:
    """Resolve the host and compare ``--version`` against the manifest minimum."""
    binary = _host_binary()
    if not binary:
        return _check(False, NOT_FOUND)
    version = _probe_version(binary)
    if version is None:
        return _check(False, f"{APP} {MIN_VERSION}+ not found ({binary}); fix: {FIX}")
    if _versions(version) < _versions(MIN_VERSION):
        detail = f"{APP} {version} found, needs {MIN_VERSION}+ (config {CONFIG_KEY}); fix: {FIX}"
        return _check(False, detail)
    return _check(True, f"{APP} {version} at {binary}")


def _techdraw_check() -> dict[str, Any]:
    """TechDraw is the workbench this package exists for."""
    try:
        __import__("TechDraw")
    except ImportError as exc:
        return _check(False, f"TechDraw does not import: {exc}")
    return _check(True, "TechDraw imports")


def _qt_check() -> dict[str, Any]:
    """FreeCAD's bundled Qt, which renders the sheets into the PDF and PNGs."""
    try:
        __import__("PySide6.QtSvg")
        from PySide6.QtGui import QPdfWriter  # noqa: F401, PLC0415
    except ImportError as exc:
        return _check(False, f"Qt does not import: {exc}", name="qt")
    return _check(True, "QtSvg and QPdfWriter import", name="qt")


def _check(ok: bool, detail: str, name: str = APP) -> dict[str, Any]:
    """One doctor check; a failure carries the fix facet prints."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else FIX}


def _host_binary() -> str:
    """The host binary: ``freecad.path``, then ``FREECAD_EXE``, then ``PATH``."""
    configured = _config_value(CONFIG_KEY)
    if configured:
        return configured
    from_env = os.environ.get(ENV, "").strip()
    if from_env:
        return from_env
    for name in PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return ""


def _config_value(key: str) -> str:
    """A string from ``<FACET_HOME>/config.toml``; ``""`` when unset or absent."""
    home = os.environ.get("FACET_HOME", "")
    if not home:
        return ""
    try:
        data = tomllib.loads((Path(home) / "config.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    section, _, name = key.partition(".")
    table = data.get(section)
    value = table.get(name) if isinstance(table, dict) else None
    return value if isinstance(value, str) else ""


def _probe_version(binary: str) -> str | None:
    """The first dotted version ``<binary> --version`` prints, or ``None``."""
    try:
        done = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    match = VERSION_RE.search(f"{done.stdout}\n{done.stderr}")
    return match.group(0) if match else None


def _versions(value: str) -> tuple[int, int, int]:
    """A dotted version padded to three components, so ``1.1`` equals ``1.1.0``."""
    parts = [int(part) for part in value.split(".") if part.isdigit()]
    padded = parts + [0] * (3 - len(parts))
    return padded[0], padded[1], padded[2]


# --- the launcher: the lab's ``tools/freecad.sh``, in Python.


def _launch_host(verb: str, input_path: Path, result_path: Path) -> None:
    """Drive the host freecadcmd through the failure-reporting wrapper."""
    binary = _host_binary()
    if not binary:
        raise RuntimeError(NOT_FOUND)
    host_input = _converted_request(binary, input_path)
    windows = binary.lower().endswith(".exe")
    wrapper = _host_path(str(Path(__file__).with_name(WRAPPER)), windows)
    runner = _host_path(str(Path(__file__).resolve()), windows)
    command = [
        binary,
        wrapper,
        PASS_FLAG,
        runner,
        "--",
        verb,
        "--input",
        _convert_argument(str(host_input), binary),
        "--result",
        _convert_argument(str(result_path), binary),
    ]
    _run_host(command)


def _converted_request(binary: str, input_path: Path) -> Path:
    """Rewrite the piece's paths to Windows form when the host is a ``.exe``."""
    if not binary.lower().endswith(".exe"):
        return input_path
    request = json.loads(input_path.read_text(encoding="utf-8"))
    inputs = dict(request.get("inputs") or {})
    piece_dir = str(request.get("piece_dir") or "")
    for key in ("script", "part"):
        value = inputs.get(key)
        if isinstance(value, str) and value:
            resolved = _resolve(value, piece_dir)
            if not Path(resolved).is_file():
                raise ValueError(f"{key}: {value} is not a file beside the piece")
            inputs[key] = _convert_argument(resolved, binary)
    request["inputs"] = inputs
    for key in ("out_dir", "piece_dir"):
        if isinstance(request.get(key), str) and request[key]:
            request[key] = _convert_argument(str(request[key]), binary)
    host = input_path.with_name(f"{input_path.name}.host.json")
    host.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    return host


def _convert_argument(value: str, binary: str) -> str:
    """``wslpath -w`` of a slash-bearing argument, as the lab script does."""
    if not binary.lower().endswith(".exe") or "/" not in value:
        return value
    return _wslpath(str(Path(value).resolve())) or value


def _wslpath(value: str) -> str:
    """``wslpath -w`` of one path; ``""`` when it cannot answer."""
    try:
        done = subprocess.run(
            ["wslpath", "-w", value],
            capture_output=True,
            text=True,
            check=False,
            timeout=WSLPATH_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    converted = done.stdout.strip()
    return converted if done.returncode == 0 else ""


def _run_host(command: list[str]) -> None:
    """Launch once, and once more only when WSL interop failed."""
    for attempt in range(1, ATTEMPTS + 1):
        done = subprocess.run(command, capture_output=True, text=True, check=False)
        output = f"{done.stdout or ''}{done.stderr or ''}"
        if done.returncode == 0:
            return
        if INTEROP_MARKER not in output or attempt == ATTEMPTS:
            raise RuntimeError(f"freecadcmd exited {done.returncode}: {_tail(output)}")


def _tail(text: str) -> str:
    """The last characters of a tool's output, for a plain failure message."""
    return text[-TAIL_CHARS:].strip()


# --- paths that cross into a Windows FreeCAD, from the already-converted input.


def _on_windows() -> bool:
    """True inside the Windows build of FreeCAD, where POSIX paths do not open."""
    return sys.platform.startswith("win")


def _host_path(value: str, windows: bool, root: str | None = None) -> str:
    """The path the Windows build can open; unchanged everywhere else."""
    if not windows or not value or _is_windows(value):
        return value
    mapped = _drive_path(value)
    if mapped is not None:
        return mapped
    anchor = (root if root is not None else _UNC_ROOT[0]).rstrip("\\")
    if anchor and value.startswith("/"):
        return f"{anchor}\\{value.lstrip('/').replace('/', chr(92))}"
    return value


def _is_windows(value: str) -> bool:
    """``C:\\x`` or ``\\\\server\\share``: already a path the Windows build opens."""
    return bool(DRIVE_RE.match(value) or value.startswith("\\\\"))


def _drive_path(value: str) -> str | None:
    """``/mnt/c/Users/x`` -> ``C:\\Users\\x``; ``None`` for anything else."""
    parts = value.split("/")
    if len(parts) < MOUNT_PARTS or parts[:2] != ["", "mnt"] or len(parts[2]) != 1:
        return None
    drive = parts[2].upper()
    rest = "\\".join(parts[3:])
    return f"{drive}:\\{rest}" if rest else f"{drive}:\\"


def _remember_root(value: str) -> None:
    """Record the UNC mount point of the request path facet already converted."""
    if not value.startswith("\\\\"):
        return
    parts = value.split("\\")
    if len(parts) >= UNC_PARTS:
        _UNC_ROOT[0] = "\\".join(parts[:UNC_PARTS])


if __name__ == "__main__":
    raise SystemExit(main())
