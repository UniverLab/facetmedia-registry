"""The freecad package runner: workshop drawings from a part, scripted FreeCAD.

facet drives a ``host-app`` package through the host binary: it launches
``freecadcmd freecad_run.py --pass runner.py <verb> --input <request>
--result <result>``, so this entry runs inside FreeCAD's Python and its four
verbs use what FreeCAD ships. ``run`` executes the piece's ``guion`` with
``sys.argv`` set to ``[guion, <out_dir>/<name>, pieza]`` (the lab's output
prefix convention), requires the ``<name>.pdf`` it writes, rasterizes the
pages with poppler's ``pdftoppm`` into ``preview/page-NN.png`` and writes
``<asset>.preview.json`` in the core document shape. ``verify`` counts the
pages, ``preview`` re-rasterizes a placed PDF, and ``doctor`` reports the
host application and TechDraw.

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
from typing import Any

#: The host application's manifest values, repeated where the runner needs them.
APP = "freecad"
CONFIG_KEY = "freecad.path"
ENV = "FREECAD_EXE"
MIN_VERSION = "1.1.4"
CAPABILITY = "freecad.plano"
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
#: The verbs that need the host binary; verify, preview and doctor answer without it.
NEEDS_HOST = ("run",)
#: The only failure worth a second launch: WSL interop failing the first accept.
INTEROP_MARKER = "UtilAcceptVsock"
ATTEMPTS = 2
TAIL_CHARS = 2000
WSLPATH_TIMEOUT_S = 10.0
PROBE_TIMEOUT_S = 30.0
#: Preview PNGs land here, under the run's output dir.
PREVIEW_DIR = "preview"
POPPLER_MISSING = (
    "pdftoppm is required to rasterize the drawing's pages (sudo apt install poppler-utils)"
)
PDFINFO_MISSING = "pdfinfo is required to count the drawing's pages"
VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")
PAGES_RE = re.compile(r"^Pages:\s*(\d+)", re.MULTILINE)
UNSAFE_NAME = re.compile(r"[^a-z0-9-]+")
#: ``C:\`` or ``C:/``: a path the Windows build already understands.
DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")
#: ``("/", "mnt", "<drive>")``: the WSL mount point's own components.
MOUNT_PARTS = 3
#: ``("", "", "server", "share")``: a UNC path's own leading components.
UNC_PARTS = 4
#: ``("wsl.localhost", "<distro>")``: the share prefix a WSL UNC path carries.
WSL_UNC_SKIP = 2
#: ``("C:", ...)``: a drive letter's own length.
DRIVE_LETTER = 2
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
    elif freecad is None and verb in NEEDS_HOST:
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


# --- freecad.plano: the guion, its PDF and its pages.


def _run(request: dict[str, Any]) -> dict[str, Any]:
    """Execute the guion on the part and report the drawing it wrote."""
    params = dict(request.get("inputs") or {})
    piece_dir = str(request.get("piece_dir") or "")
    guion = _resolve(_required(params, "guion"), piece_dir)
    pieza = _resolve(_required(params, "pieza"), piece_dir)
    name = _asset_name(guion)
    windows = _on_windows()
    out_dir = _host_path(str(request["out_dir"]), windows)
    prefix = posixpath.join(out_dir, name)
    _execute(_host_path(guion, windows), prefix, _host_path(pieza, windows))
    pdf = Path(f"{prefix}.pdf")
    if not pdf.is_file():
        raise RuntimeError(f"guion wrote no {name}.pdf")
    pages = _rasterize(pdf, Path(out_dir))
    _write_preview(pdf, pages, Path(out_dir))
    return {
        "tool": _tool(),
        "assets": [
            {
                "file": pdf.name,
                "name": name,
                "kind": "document",
                "mime": "application/pdf",
                "properties": {"page_count": len(pages)},
                "params": params,
                "seed": None,
                "inputs": [guion, pieza],
            }
        ],
    }


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


def _asset_name(guion: str) -> str:
    """``dibujo.py`` -> ``dibujo``: the asset base name, sanitized."""
    base = guion.replace("\\", "/")
    stem = posixpath.splitext(posixpath.basename(base))[0].lower()
    safe = UNSAFE_NAME.sub("-", stem).strip("-")
    return safe or "plano"


def _execute(guion: str, prefix: str, pieza: str) -> None:
    """Run the guion with the lab's argv and surface any failure loudly."""
    sys.argv = [guion, prefix, pieza]
    try:
        runpy.run_path(guion, run_name="__main__")
    except SystemExit as exit_request:
        code = exit_request.code
        if code not in (None, 0):
            raise RuntimeError(f"guion exited {code}") from None
    except BaseException:
        raise RuntimeError(f"guion failed:\n{traceback.format_exc()}") from None


def _tool() -> dict[str, str]:
    """The manifest's tool identity, so records name the real tool."""
    manifest = tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


# --- the pages: pdftoppm's PNGs, normalized like the deck runner's.


def _rasterize(pdf: Path, out_dir: Path) -> list[str]:
    """Rasterize the PDF into ``preview/page-NN.png`` and return their names."""
    folder = out_dir / PREVIEW_DIR
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    done = subprocess.run(
        _poppler_command("pdftoppm", ["-png", str(pdf), str(folder / "page")]),
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"pdftoppm exited {done.returncode}: {_tail(done.stdout + done.stderr)}")
    names = _normalize(folder)
    if not names:
        raise RuntimeError(f"pdftoppm wrote no page PNGs for {pdf.name}")
    return [f"{PREVIEW_DIR}/{name}" for name in names]


def _poppler_command(tool: str, args: list[str]) -> list[str]:
    """``tool args``: native on ``PATH``, else ``wsl -e`` from a Windows host.

    The verbs run inside the host application, and a Windows FreeCAD cannot
    see WSL's poppler-utils, so the tools are called back through WSL interop
    with the arguments translated to WSL paths.
    """
    exe = shutil.which(tool)
    if exe is not None:
        return [exe, *args]
    if _on_windows():
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if wsl is not None:
            return [wsl, "-e", tool, *[_wsl_arg(arg) for arg in args]]
    missing = POPPLER_MISSING if tool == "pdftoppm" else PDFINFO_MISSING
    raise RuntimeError(missing)


def _wsl_arg(arg: str) -> str:
    """A path argument in WSL form; a flag passes through unchanged."""
    if "/" not in arg and "\\" not in arg and not DRIVE_RE.match(arg):
        return arg
    return _wsl_path(arg)


def _wsl_path(value: str) -> str:
    """The WSL path of a Windows one: a WSL UNC share or a drive letter."""
    if value.startswith("/"):
        return value
    parts = [part for part in value.replace("\\", "/").split("/") if part]
    if not parts:
        return value
    if parts[0] in ("wsl.localhost", "wsl$"):
        return "/" + "/".join(parts[WSL_UNC_SKIP:])
    head = parts[0]
    if len(head) == DRIVE_LETTER and head[1] == ":" and head[0].isalpha():
        rest = "/".join(parts[1:])
        return f"/mnt/{head[0].lower()}/{rest}" if rest else f"/mnt/{head[0].lower()}"
    return value


def _normalize(folder: Path) -> list[str]:
    """Rename pdftoppm's ``page-1.png`` to ``page-01.png`` and sort numerically."""
    found: list[tuple[int, Path]] = []
    for path in folder.glob("page-*.png"):
        number = path.stem.removeprefix("page-")
        if number.isdigit():
            found.append((int(number), path))
    if not found:
        return []
    width = max(2, *(len(str(number)) for number, _ in found))
    names: list[str] = []
    for number, path in sorted(found):
        name = f"page-{number:0{width}d}.png"
        if path.name != name:
            path.rename(folder / name)
        names.append(name)
    return names


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
    """Rasterize each placed PDF and write its preview file."""
    out_dir = Path(_host_path(str(request["out_dir"]), _on_windows()))
    entries: list[dict[str, Any]] = []
    for item in request.get("assets") or []:
        pdf = Path(_host_path(str(item), _on_windows()))
        pages = _rasterize(pdf, out_dir)
        name = _write_preview(pdf, pages, out_dir)
        entries.append({"file": pdf.name, "preview": name, "images": []})
    return {"assets": entries}


def _verify(request: dict[str, Any]) -> dict[str, Any]:
    """One verdict per PDF: it must have at least one page."""
    return {
        "assets": [
            _verdict(Path(_host_path(str(item), _on_windows())))
            for item in request.get("assets") or []
        ]
    }


def _verdict(pdf: Path) -> dict[str, Any]:
    """A PDF's page count, from its rendered pages or its own ``pdfinfo``."""
    count = _page_count(pdf)
    return {
        "file": pdf.name,
        "passed": count > 0,
        "metrics": {"page_count": count},
        "thresholds": {"page_count_min": 1},
        "verifier": "pdfinfo",
    }


def _page_count(pdf: Path) -> int:
    """The rendered pages beside the asset, else ``pdfinfo``'s ``Pages:`` line."""
    folder = pdf.parent / PREVIEW_DIR
    rendered = len(list(folder.glob("page-*.png"))) if folder.is_dir() else 0
    if rendered:
        return rendered
    command = _poppler_command("pdfinfo", [str(pdf)])
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    match = PAGES_RE.search(done.stdout)
    if done.returncode != 0 or match is None:
        raise RuntimeError(f"pdfinfo could not count the pages of {pdf.name}")
    return int(match.group(1))


# --- the doctor: the host application and TechDraw.


def _doctor(request: dict[str, Any]) -> dict[str, Any]:
    """The host application, at least 1.1.4; TechDraw on a full probe."""
    check = _host_check()
    checks = [check]
    if request.get("depth") == "full" and check["ok"] and _freecad() is not None:
        checks.append(_techdraw_check())
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


def _check(ok: bool, detail: str) -> dict[str, Any]:
    """One doctor check; a failure carries the fix facet prints."""
    return {"name": APP, "ok": ok, "detail": detail, "fix": "" if ok else FIX}


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
    for key in ("guion", "pieza"):
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
