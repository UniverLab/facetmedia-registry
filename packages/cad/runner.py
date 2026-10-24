"""The cad package runner: 3D parts and 2D plans from scripts, checked.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` executes the caller's CadQuery or ezdxf
script unchanged inside the package environment, completes the exports the
script left out and reports every file as a ``cad`` asset; ``verify``
re-imports the STEP (valid, one solid, volume and bounding box against the
piece's expectations) or audits the DXF (zero errors, zero fixes, every
expected layer present); ``preview`` writes the CAD preview file with a
shaded view; ``doctor`` checks the tools at ``quick`` and ``full`` depth.

The script is code chosen by the caller and runs with the caller's rights
inside the package environment, exactly as ``uv run`` would; facet does not
sandbox it further.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import occlab
from facet_runner_sdk import Request, Runner

runner = Runner()

#: The tool each capability runs, pinned by the manifest and the lock.
TOOLS: dict[str, dict[str, str]] = {
    "cad.solid": {"name": "cadquery", "version": "2.8.0"},
    "cad.drawing": {"name": "ezdxf", "version": "1.4.4"},
}
#: What each capability writes: extension -> mime, in asset order.
SOLID_FILES: dict[str, str] = {"step": "model/step", "stl": "model/stl", "svg": "image/svg+xml"}
DRAWING_FILES: dict[str, str] = {
    "dxf": "image/vnd.dxf",
    "svg": "image/svg+xml",
    "png": "image/png",
}
#: The STEP asset's own properties; the derived views repeat them.
SOLID_PROPERTIES = ("volume_mm3", "bbox_mm", "faces", "solids")
#: The stderr tail a failed script reports as the runner error.
STDERR_TAIL_CHARS = 2000
#: The manifest's host hint, repeated for a broken environment.
DEFAULT_HOST_HINT = "sudo apt install libgl1 libx11-6"


def _tool(capability: str) -> dict[str, str]:
    """The record's tool: the kernel the capability actually ran."""
    return dict(TOOLS[capability])


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the doctor's host hint."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _host_hint() -> str:
    """What the manifest tells a machine missing a host library."""
    try:
        return str(_manifest()["requirements"]["host_hint"]) or DEFAULT_HOST_HINT
    except (OSError, ValueError, KeyError):
        return DEFAULT_HOST_HINT


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    if req.capability == "cad.solid":
        return _run_solid(req, params)
    if req.capability == "cad.drawing":
        return _run_drawing(req, params)
    raise ValueError(f"unknown capability: {req.capability}")


def _execute(script: Path, stem: Path) -> subprocess.CompletedProcess[str]:
    """Run the caller's script unchanged: env interpreter, isolated, own group.

    The script's prints go to the log; a non-zero exit is a runner error
    carrying the script's stderr tail.
    """
    done = subprocess.run(
        [sys.executable, "-I", str(script), str(stem)],
        cwd=script.parent,
        capture_output=True,
        text=True,
        start_new_session=True,
        check=False,
    )
    if done.stdout:
        print(done.stdout, end="")
    if done.returncode != 0:
        raise RuntimeError(f"{script.name} exited {done.returncode}: {_tail(done.stderr)}")
    return done


def _tail(text: str | None) -> str:
    """The last STDERR_TAIL_CHARS of a script's stderr, stripped."""
    return (text or "")[-STDERR_TAIL_CHARS:].strip()


def _require(stem: Path, extension: str, done: subprocess.CompletedProcess[str]) -> Path:
    """A file the script had to write; missing is a runner error with its stderr."""
    path = stem.with_suffix(f".{extension}")
    if not path.is_file():
        raise RuntimeError(f"{stem.name}.script wrote no .{extension}: {_tail(done.stderr)}")
    return path


def _run_solid(req: Request, params: dict[str, Any]) -> dict[str, Any]:
    """The script's STEP, then the STL and SVG views it left out."""
    script = Path(str(params["script"]))
    stem = req.out_dir / str(params["name"])
    done = _execute(script, stem)
    step = _require(stem, "step", done)
    shape = occlab.import_step(step)
    stl = stem.with_suffix(".stl")
    if not stl.is_file():
        occlab.export_stl(shape, stl)
    svg = stem.with_suffix(".svg")
    if not svg.is_file():
        occlab.export_svg(shape, svg)
    measured = occlab.measure(shape)
    properties = {key: measured[key] for key in SOLID_PROPERTIES}
    files = [
        (extension, stem.with_suffix(f".{extension}"), mime)
        for extension, mime in SOLID_FILES.items()
    ]
    return {"tool": _tool(req.capability), "assets": _assets(params, files, properties, script)}


def _run_drawing(req: Request, params: dict[str, Any]) -> dict[str, Any]:
    """The script's DXF, then the SVG and PNG views it left out."""
    script = Path(str(params["script"]))
    stem = req.out_dir / str(params["name"])
    done = _execute(script, stem)
    dxf = _require(stem, "dxf", done)
    document = occlab.read_dxf(dxf)
    svg = stem.with_suffix(".svg")
    if not svg.is_file():
        occlab.render_dxf_svg(document, svg)
    png = stem.with_suffix(".png")
    if not png.is_file():
        occlab.render_dxf_png(document, png)
    properties = occlab.dxf_data(document, occlab.audit_dxf(document))
    files = [
        (extension, stem.with_suffix(f".{extension}"), mime)
        for extension, mime in DRAWING_FILES.items()
    ]
    return {"tool": _tool(req.capability), "assets": _assets(params, files, properties, script)}


def _assets(
    params: Mapping[str, Any],
    files: Sequence[tuple[str, Path, str]],
    properties: Mapping[str, Any],
    script: Path,
) -> list[dict[str, Any]]:
    """One record per file: kind cad, the script as the hashed input."""
    base = {
        "name": str(params["name"]),
        "kind": "cad",
        "properties": dict(properties),
        "params": dict(params),
        "seed": None,
        "inputs": [str(script)],
    }
    return [{**base, "file": path.name, "mime": mime} for _extension, path, mime in files]


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    return {"assets": [_verify_asset(params, path) for path in req.assets]}


def _verify_asset(params: Mapping[str, Any], path: Path) -> dict[str, Any]:
    """The STEP or the DXF carries the verification; the views must parse."""
    checks = {
        ".step": lambda: _verify_step(params, path),
        ".dxf": lambda: _verify_dxf(params, path),
        ".stl": lambda: _verify_stl(path),
        ".svg": lambda: _verify_svg(path),
        ".png": lambda: _verify_png(path),
    }
    check = checks.get(path.suffix.lower())
    if check is None:
        return _verdict(
            path.name, False, {"error": f"unknown file type {path.suffix}"}, "cad-derived"
        )
    return check()


def _verdict(
    file: str, passed: bool, metrics: dict[str, Any], verifier: str, thresholds: Any = None
) -> dict[str, Any]:
    """One asset's verdict."""
    return {
        "file": file,
        "passed": passed,
        "metrics": metrics,
        "thresholds": thresholds or {},
        "verifier": verifier,
    }


def _verify_step(params: Mapping[str, Any], path: Path) -> dict[str, Any]:
    """Re-import the STEP: valid, one solid, volume and bbox as expected."""
    try:
        shape = occlab.import_step(path)
        measured = occlab.measure(shape)
    except Exception as exc:  # catch-all: an unreadable STEP is a failed verdict
        return _verdict(path.name, False, {"error": str(exc)}, "cadquery")
    passed = bool(shape.isValid()) and int(measured["solids"]) >= 1
    metrics = dict(measured)
    thresholds: dict[str, Any] = {"volume_rel_tol": None, "bbox_abs_tol_mm": None}
    expect_volume = params.get("expect-volume-mm3")
    if expect_volume is not None:
        wanted_volume = float(expect_volume)
        if wanted_volume <= 0:
            problem = "expect-volume-mm3 must be positive"
            return _verdict(path.name, False, {**metrics, "error": problem}, "cadquery", thresholds)
        tolerance = float(params.get("volume-rel-tol", 0.001))
        difference = abs(float(measured["volume_mm3"]) - wanted_volume) / wanted_volume
        metrics["volume_diff_rel"] = round(difference, 6)
        thresholds["volume_rel_tol"] = tolerance
        passed = passed and difference <= tolerance
    expect_bbox = params.get("expect-bbox-mm")
    if expect_bbox is not None:
        wanted = _expected_bbox(expect_bbox)
        if wanted is None:
            problem = "expect-bbox-mm must be one {x, y, z} item"
            return _verdict(path.name, False, {**metrics, "error": problem}, "cadquery", thresholds)
        tolerance = float(params.get("bbox-abs-tol-mm", 0.01))
        differences = [
            abs(float(side) - want) for side, want in zip(measured["bbox_mm"], wanted, strict=True)
        ]
        metrics["bbox_diff_mm"] = [round(difference, 6) for difference in differences]
        thresholds["bbox_abs_tol_mm"] = tolerance
        passed = passed and all(difference <= tolerance for difference in differences)
    return _verdict(path.name, passed, metrics, "cadquery", thresholds)


def _expected_bbox(value: Any) -> tuple[float, float, float] | None:
    """The piece's expected bbox as ``[x, y, z]``; ``None`` when malformed.

    The manifest's schema language only describes an array as a list of
    objects (core ``docs/registry.md``), so a validated piece carries
    ``[{x, y, z}]`` and never a flat ``[x, y, z]``.
    """
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], Mapping):
        return None
    item = value[0]
    try:
        return (float(item["x"]), float(item["y"]), float(item["z"]))
    except (KeyError, TypeError, ValueError):
        return None


def _verify_dxf(params: Mapping[str, Any], path: Path) -> dict[str, Any]:
    """Audit the DXF: zero errors, zero fixes, every expected layer present."""
    try:
        document = occlab.read_dxf(path)
        audit = occlab.audit_dxf(document)
        defined = occlab.layer_names(document)
    except Exception as exc:  # catch-all: an unreadable DXF is a failed verdict
        return _verdict(path.name, False, {"error": str(exc)}, "ezdxf")
    expected = [str(item["layer"]) for item in params.get("expect-layers") or []]
    missing = [layer for layer in expected if layer not in defined]
    metrics = {
        "entities": int(occlab.dxf_data(document, audit)["entities"]),
        "layers": len(defined),
        "errors": audit["errors"],
        "fixes": audit["fixes"],
        "missing_layers": missing,
    }
    thresholds = {"audit_errors_max": 0, "audit_fixes_max": 0, "expect_layers": expected}
    passed = audit["errors"] == 0 and audit["fixes"] == 0 and not missing
    return _verdict(path.name, passed, metrics, "ezdxf", thresholds)


def _verify_stl(path: Path) -> dict[str, Any]:
    """An STL passes when it meshes to at least one triangle."""
    try:
        triangles = occlab.stl_triangles(path)
    except OSError as exc:
        return _verdict(path.name, False, {"error": str(exc)}, "cad-derived")
    return _verdict(path.name, triangles > 0, {"triangles": triangles}, "cad-derived")


def _verify_svg(path: Path) -> dict[str, Any]:
    """An SVG view passes when it parses as XML with an <svg> root."""
    try:
        ok = occlab.svg_ok(path)
    except (OSError, ET.ParseError) as exc:
        return _verdict(path.name, False, {"error": str(exc)}, "cad-derived")
    return _verdict(path.name, ok, {"bytes": path.stat().st_size}, "cad-derived")


def _verify_png(path: Path) -> dict[str, Any]:
    """A PNG view passes when matplotlib's image reader opens it."""
    try:
        ok = occlab.png_ok(path)
    except (OSError, ValueError) as exc:
        return _verdict(path.name, False, {"error": str(exc)}, "cad-derived")
    return _verdict(path.name, ok, {"bytes": path.stat().st_size}, "cad-derived")


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    entries = []
    for path in req.assets:
        if path.suffix.lower() == ".step":
            data, images = _preview_step(req, path)
        elif path.suffix.lower() == ".dxf":
            data, images = _preview_dxf(req, path)
        else:
            raise ValueError(f"{path.name}: preview the STEP (.step) or the DXF (.dxf), not this")
        preview_name = f"{path.name}.preview.json"
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append({"file": path.name, "preview": preview_name, "images": images})
    return {"assets": entries}


def _preview_step(req: Request, path: Path) -> tuple[dict[str, Any], list[str]]:
    """The solid's data plus a shaded isometric view of the STEP."""
    shape = occlab.import_step(path)
    measured = occlab.measure(shape)
    view_name = f"{path.stem}.view.png"
    occlab.view_png(shape, req.out_dir / view_name)
    fields: dict[str, Any] = {"valid": bool(shape.isValid())}
    fields.update({key: measured[key] for key in (*SOLID_PROPERTIES, "holes")})
    data = {
        "preview": 1,
        "kind": "cad",
        "summary": _solid_summary(path.stem, fields),
        "solid": fields,
        "views": [{"file": view_name, "label": "shaded isometric view"}],
    }
    return data, [view_name]


def _solid_summary(name: str, fields: Mapping[str, Any]) -> str:
    """``escuadra · valid · 20 806 mm³ · 2 holes Ø6.5``."""
    volume = f"{float(fields['volume_mm3']):,.0f}".replace(",", " ")
    parts = [name, "valid" if fields["valid"] else "invalid", f"{volume} mm³"]
    holes = fields["holes"]
    if holes:
        diameters = "/".join(
            sorted({f"{float(hole['diameter_mm']):g}" for hole in holes}, key=float)
        )
        suffix = "s" if len(holes) > 1 else ""
        parts.append(f"{len(holes)} hole{suffix} Ø{diameters}")
    return " · ".join(parts)


def _preview_dxf(req: Request, path: Path) -> tuple[dict[str, Any], list[str]]:
    """The drawing's data plus its PNG view, rendered beside it when missing."""
    document = occlab.read_dxf(path)
    drawing = occlab.dxf_data(document, occlab.audit_dxf(document))
    view_name = f"{path.stem}.png"
    view = req.out_dir / view_name
    if not view.is_file():
        occlab.render_dxf_png(document, view)
    data = {
        "preview": 1,
        "kind": "cad",
        "summary": _drawing_summary(path.stem, drawing),
        "drawing": drawing,
        "views": [{"file": view_name, "label": "plan view"}],
    }
    return data, [view_name]


def _drawing_summary(name: str, drawing: Mapping[str, Any]) -> str:
    """``plano-estudio · 27 entities · 5 layers · audit clean``."""
    audit = drawing["audit"]
    verdict = (
        "audit clean"
        if not audit["errors"] and not audit["fixes"]
        else f"audit {audit['errors']} errors {audit['fixes']} fixes"
    )
    return f"{name} · {drawing['entities']} entities · {len(drawing['layers'])} layers · {verdict}"


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_cadquery(), _doctor_ezdxf(), _doctor_matplotlib()]
    if req.depth == "full":
        checks += [_doctor_step(), _doctor_dxf()]
    return {"checks": checks}


def _doctor_verdict(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names what fixes the environment."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _fix_for(exc: BaseException) -> str:
    """A missing shared object names the host hint; anything else, a re-pull."""
    message = str(exc)
    if ".so" in message or "shared object" in message:
        return _host_hint()
    return "facet pull cad"


def _doctor_cadquery() -> dict[str, Any]:
    """CadQuery and its OCP kernel import, with versions."""
    try:
        cadquery = importlib.import_module("cadquery")
        importlib.import_module("OCP")
    except Exception as exc:  # catch-all: one broken import must not hide the rest
        return _doctor_verdict("cadquery", False, str(exc), _fix_for(exc))
    return _doctor_verdict(
        "cadquery", True, f"cadquery {getattr(cadquery, '__version__', 'unknown')} and OCP import"
    )


def _doctor_ezdxf() -> dict[str, Any]:
    """ezdxf imports, with its version."""
    try:
        ezdxf = importlib.import_module("ezdxf")
    except Exception as exc:  # catch-all: the check reports, the verb survives
        return _doctor_verdict("ezdxf", False, str(exc), _fix_for(exc))
    return _doctor_verdict("ezdxf", True, f"ezdxf {ezdxf.__version__} imports")


def _doctor_matplotlib() -> dict[str, Any]:
    """matplotlib imports with the Agg backend."""
    try:
        matplotlib = importlib.import_module("matplotlib")
        matplotlib.use("Agg", force=True)
        importlib.import_module("matplotlib.pyplot")
    except Exception as exc:  # catch-all: the check reports, the verb survives
        return _doctor_verdict("matplotlib", False, str(exc), _fix_for(exc))
    return _doctor_verdict("matplotlib", True, f"matplotlib {matplotlib.__version__} with Agg")


def _doctor_step() -> dict[str, Any]:
    """Full depth: a 10 mm box exports to STEP and reads back with one solid."""
    cadquery = importlib.import_module("cadquery")
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "doctor.step"
            occlab.export_step(cadquery.Workplane().box(10, 10, 10), path)
            shape = occlab.import_step(path)
            valid = bool(shape.isValid())
            solids = len(shape.Solids())
    except Exception as exc:  # catch-all: the check reports, the verb survives
        return _doctor_verdict("step", False, f"STEP roundtrip failed: {exc}", "facet pull cad")
    detail = "a 10 mm box exports to STEP and reads back valid with one solid"
    if valid and solids == 1:
        return _doctor_verdict("step", True, detail)
    return _doctor_verdict("step", False, f"{detail}: got valid={valid} solids={solids}")


def _doctor_dxf() -> dict[str, Any]:
    """Full depth: a single line exports to DXF and reads back audited clean."""
    ezdxf = importlib.import_module("ezdxf")
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "doctor.dxf"
            document = ezdxf.new("R2018")
            document.modelspace().add_line((0, 0), (10, 0))
            document.saveas(path)
            reloaded = occlab.read_dxf(path)
            audit = occlab.audit_dxf(reloaded)
            entities = len(reloaded.modelspace())
            ok = entities == 1 and audit == {"errors": 0, "fixes": 0}
    except Exception as exc:  # catch-all: the check reports, the verb survives
        return _doctor_verdict("dxf", False, f"DXF roundtrip failed: {exc}", "facet pull cad")
    audit_line = f"audit {audit['errors']}/{audit['fixes']}"
    detail = f"a line exports to DXF and reads back: {entities} entity, {audit_line}"
    return _doctor_verdict("dxf", ok, detail)


runner.main()
