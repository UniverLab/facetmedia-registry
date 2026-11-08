"""The freecad runner: path conversion, the wrapper, the pages and the doctor.

No real FreeCAD runs here. A stub ``freecadcmd.exe`` stands where the host
binary does: it answers ``--version`` and executes the package wrapper, which
in turn executes ``runner.py`` with a stub ``FreeCAD`` module on its path, so
the entry takes its in-FreeCAD branch. Stub ``wslpath``, ``pdftoppm`` and
``pdfinfo`` record the arguments and write the pages, proving the lab's
argument conversion, the swallowed-failure wrapper, the exact preview shape
and the missing-host doctor without FreeCAD or poppler.
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
PAGE_COUNT = 2
PREVIEW_KEYS = {"preview", "kind", "summary", "page_count", "pages"}
PAGE_NAMES = ["preview/page-01.png", "preview/page-02.png"]
NOT_FOUND = (
    "freecad 1.1.4+ not found (config freecad.path, env FREECAD_EXE, PATH all empty); "
    "fix: facet config set freecad.path /path/to/freecad"
)
FIX = "facet config set freecad.path /path/to/freecad"

STUB_FREECAD = '"""A stub FreeCAD module: the runner only imports it."""\n'

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

PDFTOPPM_STUB = """#!/bin/sh
pages="${STUB_PAGES:-2}"
i=1
while [ "$i" -le "$pages" ]; do
  printf '\\211PNG\\r\\n' > "$3-$i.png"
  i=$((i + 1))
done
"""

PDFINFO_STUB = """#!/bin/sh
echo "Pages: ${STUB_PAGES:-2}"
"""

GUION = """import json
import os
import sys
from pathlib import Path

Path(os.environ["GUION_LOG"]).write_text(json.dumps(sys.argv))
Path(sys.argv[1] + ".pdf").write_bytes(b"%PDF-1.4\\n")
"""

FAILING_GUION = 'raise RuntimeError("boom")\n'


def _stubs(tmp_path: Path) -> tuple[Path, Path]:
    """The stub bin directory and the stub FreeCAD module directory."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = {
        "freecadcmd.exe": STUB_FREECADCMD.replace("{python}", sys.executable),
        "wslpath": WSLPATH_STUB,
        "pdftoppm": PDFTOPPM_STUB,
        "pdfinfo": PDFINFO_STUB,
    }
    for name, text in scripts.items():
        path = bin_dir / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)
    freecad = tmp_path / "stub-freecad"
    freecad.mkdir()
    (freecad / "FreeCAD.py").write_text(STUB_FREECAD, encoding="utf-8")
    return bin_dir, freecad


def _environment(tmp_path: Path, bin_dir: Path, freecad: Path, **extra: str) -> dict[str, str]:
    env = {
        **os.environ,
        "PATH": str(bin_dir),
        "FREECAD_EXE": str(bin_dir / "freccadcmd-placeholder"),
        "STUB_FREECAD": str(freecad),
        "STUB_PAGES": str(PAGE_COUNT),
        "WSLPATH_LOG": str(tmp_path / "wslpath.log"),
        "GUION_LOG": str(tmp_path / "guion.log"),
    }
    env.pop("FACET_HOME", None)
    env.pop("PYTHONPATH", None)
    env.update(extra)
    env["FREECAD_EXE"] = extra.get("FREECAD_EXE", str(bin_dir / "freecadcmd.exe"))
    return env


def _piece(tmp_path: Path, guion: str = GUION) -> tuple[Path, Path, Path]:
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


def _run(tmp_path: Path, out: Path, piece: Path, env: dict[str, str]):
    inputs = {"guion": f"{PDF_NAME}.py", "pieza": "pieza.step"}
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
    assert asset["properties"] == {"page_count": PAGE_COUNT}
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
    assert data["page_count"] == PAGE_COUNT
    assert data["pages"] == PAGE_NAMES
    assert all((out / name).is_file() for name in data["pages"])


def test_run_surfaces_a_guion_failure_instead_of_a_swallowed_zero(tmp_path: Path) -> None:
    """freecadcmd exits 0 on a raise; the wrapper's exit 1 must reach the launcher."""
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path, FAILING_GUION)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)

    done, result = _run(tmp_path, out, piece, env)

    assert done.returncode != 0
    assert result is None
    assert "boom" in done.stdout + done.stderr
    assert "freecadcmd exited" in done.stdout + done.stderr


def test_verify_counts_the_rendered_pages(tmp_path: Path) -> None:
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)
    _done, _result = _run(tmp_path, out, piece, env)

    request = _request("verify", out, piece, assets=[str(out / f"{PDF_NAME}.pdf")])
    done, result = _call(tmp_path, "verify", request, env)

    assert done.returncode == 0, done.stdout + done.stderr
    assert result["assets"][0] == {
        "file": f"{PDF_NAME}.pdf",
        "passed": True,
        "metrics": {"page_count": PAGE_COUNT},
        "thresholds": {"page_count_min": 1},
        "verifier": "pdfinfo",
    }


def test_preview_rasterizes_again_and_writes_the_core_shape(tmp_path: Path) -> None:
    bin_dir, freecad = _stubs(tmp_path)
    piece, _script, _part = _piece(tmp_path)
    out = _out(tmp_path)
    env = _environment(tmp_path, bin_dir, freecad)
    _done, _result = _run(tmp_path, out, piece, env)
    for page in (out / "preview").glob("page-*.png"):
        page.unlink()

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
    assert data["pages"] == PAGE_NAMES
    assert all((out / name).is_file() for name in data["pages"])


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


def test_poppler_falls_back_to_wsl_interop_inside_a_windows_host(monkeypatch: Any) -> None:
    """A Windows FreeCAD cannot see WSL's poppler: the tools go through wsl.exe."""
    spec = importlib.util.spec_from_file_location("freecad_runner_wsl", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._wsl_path("\\\\wsl.localhost\\Ubuntu\\home\\x\\out") == "/home/x/out"
    assert module._wsl_path("\\\\wsl$\\Ubuntu\\home\\x") == "/home/x"
    assert module._wsl_path("C:\\Users\\x\\out") == "/mnt/c/Users/x/out"
    assert module._wsl_path("/home/x") == "/home/x"

    def which(name: str) -> str | None:
        return {"wsl.exe": "C:\\Windows\\System32\\wsl.exe"}.get(name)

    monkeypatch.setattr(module.shutil, "which", which)
    monkeypatch.setattr(module, "_on_windows", lambda: True)
    command = module._poppler_command(
        "pdftoppm", ["-png", "\\\\wsl.localhost\\Ubuntu\\home\\x\\a.pdf", "C:\\tmp\\page"]
    )
    assert command == [
        "C:\\Windows\\System32\\wsl.exe",
        "-e",
        "pdftoppm",
        "-png",
        "/home/x/a.pdf",
        "/mnt/c/tmp/page",
    ]

    monkeypatch.setattr(module, "_on_windows", lambda: False)
    try:
        module._poppler_command("pdftoppm", ["-png", "/x/a.pdf", "/x/page"])
    except RuntimeError as exc:
        assert "pdftoppm" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a missing pdftoppm off Windows must fail")
