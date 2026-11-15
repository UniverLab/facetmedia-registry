"""The blender package runner: the agent's own Blender script, facet's output.

facet drives a ``host-app`` package through the host binary, so this entry is
Blender's script: ``blender -b --factory-startup --python-exit-code 1 --python
runner.py -- <verb> --input <request> --result <result>``. Inside Blender the
scripted capabilities run the piece's own ``.py`` script through
``scene_script.py``: the script builds the scene, sets ``scene.camera`` and owns
every creative choice, and the runner applies facet's output settings — the
resolution, the engine and its samples, the seed, the exposure, and for an
animation the frame range and rate — over whatever the script set.
``verify`` measures the PNG header or the MP4's boxes, ``preview`` writes the
kind's preview file, and ``doctor`` reports the Blender-side modules.
``blender.assets`` fetches Poly Haven files and needs no Blender at all.

Started with plain Python — ``python runner.py run ...``, as the tests and a
manual paste-back do — the same entry is the launcher the lab's
``tools/blender.sh`` is: it resolves the host Blender (``BLENDER_EXE``, then
``PATH``), converts paths to Windows form when the binary is a ``.exe`` under
WSL, drives it with the lab's flags, and retries once only on a WSL interop
failure (``UtilAcceptVsock``); anything else fails with the tail of its output.
``verify`` and ``preview`` need no Blender and answer directly.
"""

from __future__ import annotations

import importlib
import json
import os
import posixpath
import re
import struct
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import polyhaven
import scene_script

#: The lab's headless flags; the exit-code flag must precede ``--python``.
HOST_FLAGS = ("-b", "--factory-startup", "--python-exit-code", "1", "--python")
#: The verbs that need Blender; verify and preview read the output directly.
NEEDS_BLENDER = ("run", "doctor")
#: The only failure worth a second launch: WSL interop failing the first accept.
INTEROP_MARKER = "UtilAcceptVsock"
ATTEMPTS = 2
TAIL_CHARS = 2000
WSLPATH_TIMEOUT_S = 10.0
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: A PNG header is its 8-byte signature plus a 16-byte IHDR chunk.
PNG_HEADER_BYTES = 24
PNG_SIZE_OFFSET = (16, 24)
#: ``("/", "mnt", "<drive>")``: the WSL mount point's own components.
MOUNT_PARTS = 3
#: ``("", "", "server", "share")``: a UNC path's own leading components.
UNC_PARTS = 4
#: The UNC mount point of WSL's filesystem, discovered from the request's path.
_UNC_ROOT: list[str] = [""]
#: ``C:\`` or ``C:/``: a path the Windows build already understands.
DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")


def main(argv: list[str] | None = None) -> int:
    """Run the verb named on the command line, inside Blender or beside it."""
    verb, input_path, result_path = _parse_argv(sys.argv[1:] if argv is None else argv)
    request = json.loads(Path(input_path).read_text(encoding="utf-8"))
    _remember_root(str(input_path))
    if request.get("capability") == "blender.assets" and verb in ASSET_VERBS:
        result = _assets_verb(verb, request)
    else:
        bpy = _bpy()
        if bpy is None and verb in NEEDS_BLENDER:
            _launch_host(verb, input_path, result_path)
            return 0
        table = _verbs(str(request.get("capability") or ""))
        result = table[verb](bpy, request)
    Path(result_path).write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


def _verbs(capability: str) -> dict[str, Any]:
    """The verb table of the capability the request names.

    ``blender.assets`` runs its own verbs and needs no Blender, but ``doctor``
    still answers for it — ``facet describe`` asks per capability, and the
    check is bpy's alone either way.
    """
    if capability in scene_script.CAPABILITIES:
        return scene_script.verbs(capability, _script_host())
    return {"doctor": scene_script.verbs("blender.scene", _script_host())["doctor"]}


def _script_host() -> scene_script.Host:
    """The runner's helpers a scripted scene borrows instead of reimplementing."""
    return scene_script.Host(
        lambda value: _host_path(value, _on_windows()),
        _cycles,
        _png_size,
        _polyhaven_root,
    )


def _bpy() -> Any:
    """Blender's module when this entry runs inside it, else ``None``."""
    try:
        return importlib.import_module("bpy")
    except ImportError:
        return None


def _parse_argv(argv: list[str]) -> tuple[str, Path, Path]:
    """``(verb, request, result)`` from ``[--] VERB --input P --result P``.

    Blender keeps its own flags in ``sys.argv`` and passes what follows ``--``
    through, so the marker is skipped when present.
    """
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


def _cycles(bpy: Any, scene: Any) -> None:
    """Cycles on the first GPU device it finds: OPTIX, then CUDA, else CPU."""
    scene.render.engine = "CYCLES"
    preferences = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA"):
        try:
            preferences.compute_device_type = kind
            preferences.get_devices()
            devices = [device for device in preferences.devices if device.type == kind]
        except TypeError:
            continue
        if devices:
            for device in preferences.devices:
                device.use = device.type == kind
            scene.cycles.device = "GPU"
            break
    scene.cycles.use_denoising = True


# --- blender.assets: Poly Haven skies, textures and models, fetched once.
#
# The capability is kind text and needs no Blender: ``run`` downloads the
# piece's asset list into the shared models dir and writes one receipt,
# ``<name>.assets.json``; ``verify`` re-checks every listed file's size and
# ``preview`` writes the generic kind's preview beside the receipt.

ASSET_VERBS = ("run", "verify", "preview")


def _assets_verb(verb: str, request: dict[str, Any]) -> dict[str, Any]:
    return {"run": _assets_run, "verify": _assets_verify, "preview": _assets_preview}[verb](request)


def _assets_run(request: dict[str, Any]) -> dict[str, Any]:
    """Fetch the piece's Poly Haven list once and report the receipt asset."""
    params = dict(request.get("inputs") or {})
    name = str(params["name"])
    root = _polyhaven_root()
    receipts = [
        polyhaven.fetch(str(entry["id"]), entry.get("res"), root)
        for entry in params.get("assets") or []
    ]
    receipt = {"receipt": 1, "name": name, "assets": receipts}
    path = Path(_open_path(str(request["out_dir"]))) / f"{name}.assets.json"
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    entries = [entry for item in receipts for entry in item["files"]]
    return {
        "tool": _manifest_tool(),
        "assets": [
            {
                "file": f"{name}.assets.json",
                "name": name,
                "kind": "text",
                "mime": "application/json",
                "properties": {
                    "assets": len(receipts),
                    "files": len(entries),
                    "bytes": sum(int(entry["bytes"]) for entry in entries),
                },
                "params": params,
                "seed": None,
                "inputs": [],
            }
        ],
    }


def _assets_verify(request: dict[str, Any]) -> dict[str, Any]:
    """One verdict per receipt: every listed file present at its recorded size."""
    return {"assets": [_receipt_verdict(str(item)) for item in request.get("assets") or []]}


def _receipt_verdict(path: str) -> dict[str, Any]:
    """The receipt's files re-measured on disk; no network, no Blender."""
    file_name = posixpath.basename(path)
    try:
        receipt = json.loads(Path(_open_path(path)).read_text(encoding="utf-8"))
        total, present, missing = _receipt_files(receipt)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _receipt_asset_verdict(file_name, False, {"error": str(exc)})
    metrics: dict[str, Any] = {"files": total, "present": present}
    passed = not missing
    if missing:
        metrics["error"] = f"missing or resized: {', '.join(missing)}"
    return _receipt_asset_verdict(file_name, passed, metrics)


def _receipt_files(receipt: dict[str, Any]) -> tuple[int, int, list[str]]:
    """``(listed, present, missing)`` for every file a receipt names."""
    root = _polyhaven_root()
    total = present = 0
    missing: list[str] = []
    for item in receipt.get("assets") or []:
        folder = root / str(item.get("id"))
        for entry in item.get("files") or []:
            total += 1
            target = folder / str(entry.get("path"))
            if target.is_file() and target.stat().st_size == entry.get("bytes"):
                present += 1
            else:
                missing.append(str(entry.get("path")))
    return total, present, missing


def _receipt_asset_verdict(file_name: str, passed: bool, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "file": file_name,
        "passed": passed,
        "metrics": metrics,
        "thresholds": {},
        "verifier": "polyhaven-receipt",
    }


def _assets_preview(request: dict[str, Any]) -> dict[str, Any]:
    """The generic kind's preview file beside each receipt asset."""
    entries: list[dict[str, Any]] = []
    for item in request.get("assets") or []:
        path = str(item)
        file_name = posixpath.basename(path)
        data = _receipt_preview(path)
        preview_name = f"{file_name}.preview.json"
        directory = posixpath.dirname(path)
        preview_path = f"{directory}/{preview_name}" if directory else preview_name
        with open(_open_path(preview_path), "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
        entries.append({"file": file_name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _receipt_preview(path: str) -> dict[str, Any]:
    """The generic schema's scalars for one receipt: counts and total bytes."""
    receipt = json.loads(Path(_open_path(path)).read_text(encoding="utf-8"))
    assets = receipt.get("assets") or []
    files = [entry for item in assets for entry in item.get("files") or []]
    total = sum(int(entry.get("bytes") or 0) for entry in files)
    name = str(receipt.get("name") or posixpath.basename(path))
    ids = ", ".join(str(item.get("id")) for item in assets)
    summary = f"{name} · {len(assets)} assets · {len(files)} files · {total / 1e6:.1f} MB"
    return {
        "preview": 1,
        "kind": "text",
        "summary": summary[:160],
        "fields": {"assets": len(assets), "files": len(files), "bytes": total, "ids": ids},
    }


def _polyhaven_root() -> Path:
    """``<home>/models/blender/polyhaven``; FACET_MODELS is ``<home>/models/direct``."""
    return Path(
        _open_path(
            str(Path(os.environ["FACET_MODELS"]).parent.parent / "models" / "blender" / "polyhaven")
        )
    )


def _manifest_tool() -> dict[str, str]:
    """The manifest's tool identity, like the other runners report it."""
    manifest = tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))
    return {"name": str(manifest["name"]), "version": str(manifest["version"])}


# --- the PNG: measured from its header, which needs no third-party module.


def _png_size(value: str) -> tuple[int, int]:
    """A PNG's pixel size from its IHDR, so verify needs no Pillow in Blender."""
    with open(_open_path(value), "rb") as handle:
        header = handle.read(PNG_HEADER_BYTES)
    if len(header) < PNG_HEADER_BYTES or header[:8] != PNG_SIGNATURE:
        raise ValueError(f"{posixpath.basename(value)}: not a PNG")
    start, end = PNG_SIZE_OFFSET
    width, height = struct.unpack(">II", header[start:end])
    return int(width), int(height)


def _open_path(value: str) -> str:
    """The path ``open`` accepts when this entry runs inside the Windows build."""
    return _host_path(value, _on_windows())


# --- the host launch, for the WSL Windows Blender the lab runs.


def _on_windows() -> bool:
    """True inside the Windows build of Blender, where POSIX paths do not open."""
    return sys.platform.startswith("win")


def _host_path(value: str, windows: bool, root: str | None = None) -> str:
    """The path the Windows build can open; unchanged everywhere else.

    String work only: ``pathlib`` inside the Windows build reads ``/mnt/c/x``
    as ``\\mnt\\c\\x``, and ``wslpath`` is a WSL executable it cannot run,
    so the launcher resolves WSL's own root once and passes it down.
    """
    if not windows or not value or _is_windows(value):
        return value
    mapped = _drive_path(value)
    if mapped is not None:
        return mapped
    anchor = (root if root is not None else _wsl_root()).rstrip("\\")
    if anchor and value.startswith("/"):
        return f"{anchor}\\{value.lstrip('/').replace('/', chr(92))}"
    return value


def _wsl_root() -> str:
    """WSL's own root as a Windows UNC path, discovered from the request's path.

    facet converts ``--input`` with ``wslpath -w`` before the host launches,
    so inside the Windows build that argument already reads
    ``\\\\wsl.localhost\\<distro>\\...``; its server and share are the
    mount point every POSIX path in the request belongs to.
    """
    return _UNC_ROOT[0]


def _remember_root(value: str) -> None:
    """Record the UNC mount point of a path the host already converted."""
    if not value.startswith("\\\\"):
        return
    parts = value.split("\\")
    if len(parts) >= UNC_PARTS:
        _UNC_ROOT[0] = "\\".join(parts[:UNC_PARTS])


def _is_windows(value: str) -> bool:
    """``C:\\x`` or ``\\\\server\\share``: already a path the Windows build opens."""
    return bool(DRIVE_RE.match(value) or value.startswith("\\\\"))


def _drive_path(value: str) -> str | None:
    """``/mnt/c/Users/x`` -> ``C:\\Users\\x``; ``None`` for anything else."""
    parts = value.split("/")
    # ``["", "mnt", "<drive>", ...]``: the WSL mount point's own shape.
    if len(parts) < MOUNT_PARTS or parts[:2] != ["", "mnt"] or len(parts[2]) != 1:
        return None
    drive = parts[2].upper()
    rest = "\\".join(parts[3:])
    return f"{drive}:\\{rest}" if rest else f"{drive}:\\"


def _wsl_unc_root() -> str:
    """The Windows UNC path of WSL's own ``/``, from ``wslpath -w /``."""
    converted = _wslpath("/")
    return converted.rstrip("\\") if converted else ""


def _wslpath(value: str) -> str:
    """``wslpath -w`` of a path the drive mapping does not cover; ``""`` if it cannot."""
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


def _blender_binary() -> str:
    """The host binary the launcher drives: ``BLENDER_EXE``, then ``PATH``."""
    configured = os.environ.get("BLENDER_EXE", "")
    if configured:
        return configured
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / "blender"
        if candidate.is_file():
            return str(candidate)
    return ""


def _launch_host(verb: str, input_path: Path, result_path: Path) -> None:
    """Drive the host Blender with the lab's flags, retrying interop once."""
    binary = _blender_binary()
    if not binary:
        raise RuntimeError(
            "blender not found (set BLENDER_EXE or put blender on PATH); "
            "facet resolves blender.path"
        )
    windows = binary.lower().endswith(".exe")
    root = _wsl_unc_root() if windows else ""
    command = [
        binary,
        *HOST_FLAGS,
        _host_path(str(Path(__file__).resolve()), windows, root),
        "--",
        verb,
        "--input",
        _host_path(str(input_path), windows, root),
        "--result",
        _host_path(str(result_path), windows, root),
    ]
    _run_host(command)


def _run_host(command: list[str]) -> None:
    """Launch once, and once more only when WSL interop failed."""
    for attempt in range(1, ATTEMPTS + 1):
        done = subprocess.run(command, capture_output=True, text=True, check=False)
        output = f"{done.stdout or ''}{done.stderr or ''}"
        if done.returncode == 0:
            print(output, end="")
            return
        if INTEROP_MARKER not in output or attempt == ATTEMPTS:
            raise RuntimeError(f"blender exited {done.returncode}: {_tail(output)}")
        print(
            f"blender exited {done.returncode} after a WSL interop failure (attempt {attempt})",
            file=sys.stderr,
        )


def _tail(text: str) -> str:
    return text[-TAIL_CHARS:].strip()


if __name__ == "__main__":
    raise SystemExit(main())
