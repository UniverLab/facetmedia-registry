"""The ascii package runner: image to ASCII art, figlet banners in DOS Rebel.

Written on the runner SDK (``facet_runner_sdk``, copied into every
environment). Four verbs: ``run`` writes the assets, ``verify`` judges
them, ``preview`` writes the generic preview file, ``doctor`` checks the
tool at ``quick`` and ``full`` depth.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import art
import numpy
import PIL
import PIL.ImageFont
import pyfiglet
from facet_runner_sdk import Request, Runner

runner = Runner()

SIMILARITY_MIN = 0.55
#: Ink ratio bounds every image verdict enforces.
INK_MIN = 0.02
INK_MAX = 0.98
#: Pixel size of the synthetic gradient the full doctor converts.
DOCTOR_SIZE = 8
MODEL_ID = "sometype-mono"


def _tool() -> dict[str, str]:
    """The manifest's tool identity, so records name the real tool."""
    try:
        manifest = tomllib.loads((Path(__file__).parent / "package.toml").read_text())
        return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}
    except (OSError, ValueError, KeyError):
        return {"name": "facet ascii (Pillow, NumPy, pyfiglet)", "version": "0.1.0"}


def _mono_font(req: Request) -> Path:
    """The Sometype Mono file facet downloaded for this package."""
    return req.model_path(MODEL_ID)


def _image_file(params: dict[str, Any], base: Path) -> str:
    """The piece's image path, resolved against the request's directory.

    Records keep the piece's relative image path, so a relative path
    resolves against the request's directory before loading.
    """
    raw = str(params["image"])
    candidate = Path(raw)
    if not candidate.is_absolute() and (base / candidate).is_file():
        return str(base / candidate)
    return raw


def _source_grey(params: dict[str, Any], base: Path) -> Any:
    """The source as a 0..1 grey array, flipped when ``invert`` is set."""
    grey, _ = art.load_image(_image_file(params, base))
    if bool(params.get("invert", False)):
        grey = 1.0 - grey
    return grey


def _image_lines(req: Request, params: dict[str, Any]) -> tuple[list[str], Any]:
    """Render the piece's image in its mode; also returns the grey source."""
    grey = _source_grey(params, req.piece_dir)
    width = int(params.get("width", 80))
    mode = str(params.get("mode", "forma"))
    if mode == "densidad":
        return art.to_densidad(grey, width), grey
    if mode == "trazo":
        return art.to_trazo(grey, width), grey
    if mode == "braille":
        return art.to_braille(grey, width), grey
    return art.to_forma(grey, width, art.glyph_atlas(_mono_font(req))), grey


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    if req.capability == "ascii.image":
        return _run_image(req, params)
    if req.capability == "ascii.banner":
        return _run_banner(req, params)
    raise ValueError(f"unknown capability: {req.capability}")


def _run_image(req: Request, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params["name"])
    width = int(params.get("width", 80))
    mode = str(params.get("mode", "forma"))
    font_path = _mono_font(req)
    lines, grey = _image_lines(req, params)
    columns, rows = art.grid_shape(grey.shape[1], grey.shape[0], width)
    (req.out_dir / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assets: list[dict[str, Any]] = [
        {
            "file": f"{name}.txt",
            "name": name,
            "kind": "text",
            "mime": "text/plain",
            "properties": {
                "columns": columns,
                "rows": rows,
                "mode": mode,
                "charset_size": art.charset_size(mode),
            },
            "params": params,
            "seed": None,
            "inputs": [str(params["image"])],
        }
    ]
    if str(params.get("color", "none")) == "ansi":
        _, rgb = art.load_image(_image_file(params, req.piece_dir))
        tinted = art.apply_ansi(lines, art.sample_color(rgb, width))
        (req.out_dir / f"{name}.ans").write_text("\n".join(tinted) + "\n", encoding="utf-8")
        assets.append(
            {
                "file": f"{name}.ans",
                "name": name,
                "kind": "text",
                "mime": "text/plain",
                "properties": {
                    "columns": columns,
                    "rows": rows,
                    "mode": mode,
                    "charset_size": art.charset_size(mode),
                },
                "params": params,
                "seed": None,
                "inputs": [str(params["image"])],
            }
        )
    art.render_png(lines, font_path, bool(params.get("invert", False))).save(
        req.out_dir / f"{name}.png"
    )
    assets.append(
        {
            "file": f"{name}.png",
            "name": name,
            "kind": "text",
            "mime": "image/png",
            "properties": {
                "columns": columns,
                "rows": rows,
                "mode": mode,
                "charset_size": art.charset_size(mode),
            },
            "params": params,
            "seed": None,
            "inputs": [str(params["image"])],
        }
    )
    return {"tool": _tool(), "assets": assets}


def _run_banner(req: Request, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params["name"])
    font = str(params.get("font", "dos_rebel"))
    width = int(params.get("width", 120))
    lines = art.make_banner(str(params["text"]), font, width)
    columns = max((len(line) for line in lines), default=0)
    (req.out_dir / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (req.out_dir / f"{name}.svg").write_text(art.banner_svg(lines), encoding="utf-8")
    properties = {"columns": columns, "rows": len(lines), "font": font}
    base = {
        "name": name,
        "kind": "text",
        "properties": properties,
        "params": params,
        "seed": None,
        "inputs": [],
    }
    return {
        "tool": _tool(),
        "assets": [
            {**base, "file": f"{name}.txt", "mime": "text/plain"},
            {**base, "file": f"{name}.svg", "mime": "image/svg+xml"},
        ],
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    if req.capability == "ascii.image":
        return {"assets": [_verify_image(req, params, path) for path in req.assets]}
    if req.capability == "ascii.banner":
        return {"assets": [_verify_banner(params, path) for path in req.assets]}
    raise ValueError(f"unknown capability: {req.capability}")


def _verify_image(req: Request, params: dict[str, Any], path: Path) -> dict[str, Any]:
    if path.suffix != ".txt":
        ok = path.is_file() and path.stat().st_size > 0
        return {
            "file": path.name,
            "passed": ok,
            "metrics": {},
            "thresholds": {},
            "verifier": "ascii-derived",
        }
    lines = path.read_text(encoding="utf-8").splitlines()
    columns = len(lines[0]) if lines else 0
    uniform = bool(lines) and all(len(line) == columns for line in lines)
    atlas = art.glyph_atlas(_mono_font(req))
    grey = _source_grey(params, req.piece_dir)
    re_rendered = art.render_text_bitmap(lines, atlas)
    similarity = art.pearson(
        art.downsample_to_grid(grey, columns, len(lines)),
        art.downsample_to_grid(re_rendered, columns, len(lines)),
    )
    ratio = art.ink_ratio(lines)
    passed = uniform and similarity >= SIMILARITY_MIN and INK_MIN <= ratio <= INK_MAX
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {
            "similarity": similarity,
            "ink_ratio": ratio,
            "columns": columns,
            "rows": len(lines),
        },
        "thresholds": {"similarity_min": SIMILARITY_MIN},
        "verifier": "ascii-rerender",
    }


def _verify_banner(params: dict[str, Any], path: Path) -> dict[str, Any]:
    if path.suffix != ".txt":
        ok = path.is_file() and path.stat().st_size > 0
        return {
            "file": path.name,
            "passed": ok,
            "metrics": {},
            "thresholds": {},
            "verifier": "ascii-derived",
        }
    text = path.read_text(encoding="utf-8")
    expected = art.make_banner(
        str(params["text"]), str(params.get("font", "dos_rebel")), int(params.get("width", 120))
    )
    lines = text.splitlines()
    columns = max((len(line) for line in lines), default=0)
    passed = (
        text == "\n".join(expected) + "\n"
        and all(len(line) <= int(params.get("width", 120)) for line in lines)
        and any(line.strip() for line in lines)
    )
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {"columns": columns, "rows": len(lines)},
        "thresholds": {},
        "verifier": "ascii-pyfiglet",
    }


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    entries = []
    for path in req.assets:
        preview_name = f"{path.name}.preview.json"
        if req.capability == "ascii.image":
            data = _preview_image(params, path, req)
        elif req.capability == "ascii.banner":
            data = _preview_banner(params, path)
        else:
            raise ValueError(f"unknown capability: {req.capability}")
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _read_lines(path: Path, params: dict[str, Any]) -> list[str]:
    """The text lines for an asset: itself when ``.txt``, else its sibling."""
    if path.suffix == ".txt":
        return path.read_text(encoding="utf-8").splitlines()
    sibling = path.parent / f"{params.get('name', path.stem)}.txt"
    if sibling.is_file():
        return sibling.read_text(encoding="utf-8").splitlines()
    return []


def _preview_image(params: dict[str, Any], path: Path, req: Request) -> dict[str, Any]:
    mode = str(params.get("mode", "forma"))
    lines = _read_lines(path, params)
    columns = max((len(line) for line in lines), default=0)
    fields: dict[str, Any] = {
        "columns": columns,
        "rows": len(lines),
        "mode": mode,
        "charset_size": art.charset_size(mode),
    }
    summary = f"{columns}×{len(lines)} · {mode}"
    try:
        grey = _source_grey(params, req.piece_dir)
        atlas = art.glyph_atlas(_mono_font(req))
        re_rendered = art.render_text_bitmap(lines, atlas)
        similarity = art.pearson(
            art.downsample_to_grid(grey, columns, len(lines)),
            art.downsample_to_grid(re_rendered, columns, len(lines)),
        )
        fields["similarity"] = similarity
        fields["ink_ratio"] = art.ink_ratio(lines)
        summary += f" · similarity {similarity:.2f}"
    except (OSError, ValueError, KeyError):
        pass
    return {"preview": 1, "kind": "text", "summary": summary, "fields": fields}


def _preview_banner(params: dict[str, Any], path: Path) -> dict[str, Any]:
    font = str(params.get("font", "dos_rebel"))
    lines = _read_lines(path, params)
    columns = max((len(line) for line in lines), default=0)
    return {
        "preview": 1,
        "kind": "text",
        "summary": f"{art.FONT_NAMES.get(font, font)} · {columns}×{len(lines)}",
        "fields": {"columns": columns, "rows": len(lines), "font": font},
    }


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks: list[dict[str, Any]] = [
        {
            "name": "imports",
            "ok": True,
            "detail": f"PIL {PIL.__version__}, numpy {numpy.__version__}, "
            f"pyfiglet {pyfiglet.__version__} import",
            "fix": "",
        }
    ]
    _doctor_figlet(checks)
    font_path = _doctor_font(req, checks)
    if req.depth == "full":
        _doctor_full(req, checks, font_path)
    return {"checks": checks}


def _doctor_figlet(checks: list[dict[str, Any]]) -> None:
    """Append the figlet-font check; it never depends on the model."""
    present = "dos_rebel" in pyfiglet.FigletFont.getFonts()
    checks.append(
        {
            "name": "figlet_font",
            "ok": present,
            "detail": "dos_rebel is installed with pyfiglet"
            if present
            else "dos_rebel is not in pyfiglet's fonts",
            "fix": "" if present else "facet pull ascii",
        }
    )


def _doctor_font(req: Request, checks: list[dict[str, Any]]) -> Path | None:
    try:
        font_path = _mono_font(req)
    except KeyError:
        checks.append(
            {
                "name": "mono_font",
                "ok": False,
                "detail": "sometype-mono model is missing",
                "fix": "facet pull ascii",
            }
        )
        return None
    try:
        manifest = tomllib.loads((Path(__file__).parent / "package.toml").read_text())
        expected = int(manifest["models"][0]["bytes"])
    except (OSError, ValueError, KeyError, IndexError):
        expected = 64308
    try:
        size = font_path.stat().st_size
        font = PIL.ImageFont.truetype(str(font_path), 32)
        font.getmetrics()
        ok = size == expected
        checks.append(
            {
                "name": "mono_font",
                "ok": ok,
                "detail": f"sometype-mono {size} bytes, opens with Pillow"
                if ok
                else f"sometype-mono is {size} bytes, expected {expected}",
                "fix": "" if ok else "facet pull ascii",
            }
        )
    except OSError as exc:
        checks.append(
            {
                "name": "mono_font",
                "ok": False,
                "detail": f"sometype-mono unreadable: {exc}",
                "fix": "facet pull ascii",
            }
        )
        return None
    return font_path


def _doctor_full(req: Request, checks: list[dict[str, Any]], font_path: Path | None) -> None:
    try:
        lines = art.make_banner("A", "dos_rebel", 120)
        ok = bool(lines) and any(line.strip() for line in lines)
        checks.append(
            {
                "name": "banner",
                "ok": ok,
                "detail": f"rendering 'A' in dos_rebel gives {len(lines)} lines"
                if ok
                else "rendering 'A' in dos_rebel gave nothing",
                "fix": "" if ok else "facet pull ascii",
            }
        )
    except (OSError, ValueError) as exc:
        checks.append(
            {
                "name": "banner",
                "ok": False,
                "detail": f"banner render failed: {exc}",
                "fix": "facet pull ascii",
            }
        )
    if font_path is None:
        checks.append(
            {
                "name": "image",
                "ok": False,
                "detail": "no mono font, cannot convert a gradient",
                "fix": "facet pull ascii",
            }
        )
        return
    try:
        gradient = numpy.tile(numpy.linspace(0.0, 1.0, DOCTOR_SIZE), (DOCTOR_SIZE, 1))
        grid = art.to_forma(gradient, DOCTOR_SIZE, art.glyph_atlas(font_path))
        ok = len(grid) > 0 and all(len(line) == DOCTOR_SIZE for line in grid)
        detail = (
            "an 8x8 gradient converts to an 8-column grid"
            if ok
            else "gradient conversion gave the wrong grid"
        )
        checks.append(
            {"name": "image", "ok": ok, "detail": detail, "fix": "" if ok else "facet pull ascii"}
        )
    except (OSError, ValueError) as exc:
        checks.append(
            {
                "name": "image",
                "ok": False,
                "detail": f"gradient conversion failed: {exc}",
                "fix": "facet pull ascii",
            }
        )


runner.main()
