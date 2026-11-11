"""The texforge package runner: long LaTeX documents to a verified PDF.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` stages a scratch build dir and shells out to
the person-installed ``texforge`` binary, ``verify`` lints the project and
counts the PDF's pages, ``preview`` rasterizes the PDF into per-page PNGs,
``doctor`` proves the binary is on ``PATH`` and recent enough.

The runner never installs or bundles texforge, never runs the interactive
``texforge init`` and never touches the texforge config directory or the
host's ``~/.local/bin``: it writes ``project.toml`` itself, so a pull is only
the environment and the binary is the machine's own.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from facet_runner_sdk import Request, Runner

runner = Runner()

#: The one capability this package serves.
CAPABILITY = "texforge.document"
#: The template texforge embeds; it is offline, so no network is ever needed.
TEMPLATE = "general"
#: The minimum ``texforge`` the runner drives, as a semver tuple.
MIN_TEXFORGE = (0, 10, 0)
MIN_TEXFORGE_TEXT = "0.10.0"
#: A build may compile a long document; the lint and the PDF probes are quick.
BUILD_TIMEOUT_S = 900
PROBE_TIMEOUT_S = 120
#: How many trailing log lines a failed build keeps in its message.
LOG_TAIL_LINES = 40
#: The install line a machine without texforge is told to run.
DEFAULT_HOST_HINT = (
    "curl -fsSL https://raw.githubusercontent.com/UniverLab/texforge/main/scripts/install.sh | sh"
)
#: Asset base names, the manifest's own pattern, checked again runner-side.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_PAGES_RE = re.compile(r"^pages:\s*(\d+)", re.MULTILINE)
_WARNINGS_RE = re.compile(r"WARNINGS \((\d+)\)")
#: Preview PNGs land here, under the run's output dir.
PREVIEW_DIR = "preview"


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity and the host hint."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    """The manifest's tool identity, so records name the real tool."""
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _host_hint() -> str:
    """What the manifest tells a machine missing texforge."""
    try:
        return str(_manifest()["requirements"]["host_hint"]) or DEFAULT_HOST_HINT
    except (OSError, ValueError, KeyError):
        return DEFAULT_HOST_HINT


def _required(inputs: dict[str, Any], key: str) -> str:
    """One required input as non-empty text; a piece missing it is refused."""
    value = inputs.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key}: required")
    return value


def _params(inputs: dict[str, Any]) -> dict[str, str]:
    """The document's fields, with the manifest's name pattern enforced."""
    params = {
        "main": _required(inputs, "main"),
        "name": _required(inputs, "name"),
        "author": _required(inputs, "author"),
    }
    if not NAME_RE.fullmatch(params["name"]):
        raise ValueError(f"name: {params['name']!r} must match {NAME_RE.pattern}")
    return params


def _main(req: Request, params: dict[str, str]) -> Path:
    """The main .tex file, resolved relative to the piece."""
    raw = Path(params["main"])
    main = raw if raw.is_absolute() else req.piece_dir / raw
    if not main.is_file():
        raise ValueError(f"main: {params['main']} is not a file beside the piece")
    return main


def _sanitize(title: str) -> str:
    """texforge's own title-to-filename rule, so the PDF is found by name."""
    folded = "".join(char if char.isalnum() else "-" for char in title.lower())
    return "-".join(part for part in folded.split("-") if part)


def _toml_string(value: str) -> str:
    """A TOML basic string, escaped the way JSON escapes one."""
    return json.dumps(value, ensure_ascii=False)


def _bib_name(source: Path) -> str | None:
    """The top-level ``.bib`` beside the piece, when there is one."""
    found = sorted(entry.name for entry in source.iterdir() if entry.suffix == ".bib")
    return found[0] if found else None


def _is_out_dir(entry: Path, out_dir: Path) -> bool:
    """Whether ``entry`` is the runner's own output dir, never a source."""
    try:
        return entry.resolve() == out_dir.resolve()
    except OSError:
        return False


def _copy_sources(source: Path, stage: Path, out_dir: Path) -> None:
    """Copy the main's sibling sources into the scratch stage.

    When the main sits beside the piece file, the core places the output
    dir inside the piece (``.facet-tmp-*``); copying it would copy the runner's
    own files — and, before the stage moved out of ``out_dir``, the stage into
    itself — so it is skipped.
    """
    for entry in source.iterdir():
        if _is_out_dir(entry, out_dir):
            continue
        target = stage / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        elif entry.is_file():
            shutil.copy2(entry, target)


def _write_project(stage: Path, params: dict[str, str], entry: str, bib: str | None) -> None:
    """Write the project.toml texforge reads, instead of running ``init``."""
    lines = [
        "[document]",
        f"title = {_toml_string(params['name'])}",
        f"author = {_toml_string(params['author'])}",
        f"template = {_toml_string(TEMPLATE)}",
        "",
        "[build]",
        f"entry = {_toml_string(entry)}",
    ]
    if bib is not None:
        lines.append(f"bibliography = {_toml_string(bib)}")
    (stage / "project.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


@contextmanager
def _staged(req: Request, params: dict[str, str]) -> Iterator[tuple[Path, str]]:
    """Stage the piece's sources and project.toml in a scratch dir, then clean up."""
    main = _main(req, params)
    source = main.parent
    with tempfile.TemporaryDirectory(prefix="texforge-stage-") as folder:
        stage = Path(folder)
        _copy_sources(source, stage, req.out_dir)
        _write_project(stage, params, main.name, _bib_name(source))
        yield stage, main.name


def _run_tool(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """One texforge invocation in the stage; an absent binary is a failure."""
    try:
        return subprocess.run(
            ["texforge", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=BUILD_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"texforge {args[0]} cannot run: {exc}") from exc


def _output(done: subprocess.CompletedProcess[str]) -> str:
    """Everything texforge printed, both streams, in order-free concatenation."""
    return f"{done.stdout}{done.stderr}"


def _tail(text: str) -> str:
    """The last lines of a tool's output, for a plain failure message."""
    return "\n".join(text.strip().splitlines()[-LOG_TAIL_LINES:])


def _require_ok(done: subprocess.CompletedProcess[str], what: str) -> None:
    """A non-zero texforge exit becomes a runner error carrying the log tail."""
    if done.returncode != 0:
        raise RuntimeError(
            f"{what} failed (texforge exited {done.returncode}):\n{_tail(_output(done))}"
        )


def _built_pdf(stage: Path, name: str) -> Path:
    """The PDF texforge wrote: it names the build after the sanitized title."""
    path = stage / f"{_sanitize(name)}.pdf"
    if not path.is_file():
        raise RuntimeError(f"texforge build wrote no {path.name} in the stage")
    return path


def _place_pdf(asset: Path, stage: Path, name: str) -> None:
    """Put the built PDF where ``texforge pdf`` and ``preview`` look for it."""
    shutil.copy2(asset, stage / f"{_sanitize(name)}.pdf")


def _parse_pages(text: str) -> int | None:
    """The ``pages: N`` line ``texforge pdf info`` prints, or ``None``."""
    match = _PAGES_RE.search(text)
    return int(match.group(1)) if match else None


def _warnings(text: str) -> int:
    """How many warnings ``texforge pdf check`` reported."""
    match = _WARNINGS_RE.search(text)
    if match is not None:
        return int(match.group(1))
    return sum(1 for line in text.splitlines() if line.strip().startswith("WARNING"))


def _fidelity(stage: Path) -> tuple[int, int]:
    """The source-to-PDF fidelity check: its warning count and exit, never gating."""
    done = _run_tool(["pdf", "check"], stage)
    return _warnings(_output(done)), done.returncode


def _asset(params: dict[str, str], path: Path) -> dict[str, Any]:
    """The run's document record for the built PDF."""
    return {
        "file": path.name,
        "name": params["name"],
        "kind": "document",
        "mime": "application/pdf",
        "properties": {},
        "params": dict(params),
        "seed": None,
        "inputs": [params["main"]],
    }


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    if req.capability != CAPABILITY:
        raise ValueError(f"unknown capability: {req.capability}")
    params = _params(dict(req.inputs))
    target = req.out_dir / f"{params['name']}.pdf"
    with _staged(req, params) as (stage, _entry):
        _require_ok(_run_tool(["build"], stage), "texforge build")
        shutil.copy2(_built_pdf(stage, params["name"]), target)
    return {"tool": _tool(), "assets": [_asset(params, target)]}


def _verdict(path: Path, page_count: int, warnings: int, exit_code: int) -> dict[str, Any]:
    """One PDF's verdict: the lint and the page count gate, fidelity only records."""
    return {
        "file": path.name,
        "passed": page_count > 0,
        "metrics": {
            "page_count": page_count,
            "fidelity_warnings": warnings,
            "fidelity_exit": exit_code,
        },
        "thresholds": {"page_count_min": 1},
        "verifier": "texforge-check-pdf-info",
    }


def _verify_one(req: Request, params: dict[str, str], path: Path) -> dict[str, Any]:
    """Lint, then count pages; a broken ref/cite or no page is a runner failure."""
    with _staged(req, params) as (stage, _entry):
        _place_pdf(path, stage, params["name"])
        _require_ok(_run_tool(["check"], stage), "texforge check")
        info = _run_tool(["pdf", "info"], stage)
        _require_ok(info, "texforge pdf info")
        page_count = _parse_pages(_output(info))
        if page_count is None or page_count <= 0:
            raise RuntimeError(f"texforge pdf info reported no pages:\n{_tail(_output(info))}")
        warnings, exit_code = _fidelity(stage)
    return _verdict(path, page_count, warnings, exit_code)


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    params = _params(dict(req.inputs))
    return {"assets": [_verify_one(req, params, path) for path in req.assets]}


def _preview_data(path: Path, pages: list[str]) -> dict[str, Any]:
    """The core document preview shape, pages relative to the asset's dir."""
    count = len(pages)
    plural = "" if count == 1 else "s"
    return {
        "preview": 1,
        "kind": "document",
        "summary": f"{path.name} · {count} page{plural}",
        "page_count": count,
        "pages": pages,
    }


@contextmanager
def _preview_staged(params: dict[str, str], asset: Path) -> Iterator[Path]:
    """The minimal project ``texforge preview`` reads: project.toml and the PDF.

    The core runs ``preview`` from the asset's own directory, so the original
    sources need not sit beside it; only the compiled PDF and its title matter.
    """
    with tempfile.TemporaryDirectory(prefix="texforge-preview-") as folder:
        stage = Path(folder)
        _write_project(stage, params, Path(params["main"]).name, None)
        _place_pdf(asset, stage, params["name"])
        yield stage


def _preview_one(req: Request, params: dict[str, str], path: Path) -> dict[str, Any]:
    """Rasterize the PDF into per-page PNGs and write its preview file."""
    out_dir = req.out_dir / PREVIEW_DIR
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    with _preview_staged(params, path) as stage:
        _require_ok(_run_tool(["preview", "--out", str(out_dir)], stage), "texforge preview")
    names = sorted(entry.name for entry in out_dir.glob("page-*.png"))
    if not names:
        raise RuntimeError("texforge preview wrote no page PNGs")
    pages = [f"{PREVIEW_DIR}/{name}" for name in names]
    preview_name = f"{path.name}.preview.json"
    data = _preview_data(path, pages)
    (req.out_dir / preview_name).write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"file": path.name, "preview": preview_name, "images": []}


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = _params(dict(req.inputs))
    return {"assets": [_preview_one(req, params, path) for path in req.assets]}


def _doctor_check(ok: bool, detail: str, fix: str) -> dict[str, Any]:
    """One doctor check; a failure names what fixes the machine."""
    return {"name": "texforge", "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _parse_version(text: str) -> tuple[int, int, int] | None:
    """The first semver triple in ``texforge --version``'s output."""
    match = _VERSION_RE.search(text)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    """The binary on PATH, at least 0.10.0; otherwise the host hint installs it."""
    hint = _host_hint()
    exe = shutil.which("texforge")
    if exe is None:
        return {
            "checks": [
                _doctor_check(False, f"texforge {MIN_TEXFORGE_TEXT}+ not found on PATH", hint)
            ]
        }
    try:
        done = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"checks": [_doctor_check(False, f"texforge --version cannot run: {exc}", hint)]}
    text = _output(done)
    version = _parse_version(text)
    if version is None:
        return {
            "checks": [
                _doctor_check(False, f"texforge --version printed no version: {text.strip()}", hint)
            ]
        }
    found = ".".join(str(part) for part in version)
    if version < MIN_TEXFORGE:
        return {
            "checks": [
                _doctor_check(False, f"texforge {found} is older than {MIN_TEXFORGE_TEXT}", hint)
            ]
        }
    return {"checks": [_doctor_check(True, f"texforge {found} at {exe}", "")]}


runner.main()
