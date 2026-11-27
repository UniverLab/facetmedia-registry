"""The pdf-ops package runner: deterministic CPU PDF manipulation.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` executes ``merge``, ``split``, ``compress``
or ``rasterize`` with pikepdf and pypdfium2; ``verify`` re-opens produced
PDFs with pikepdf and checks the exact expected page count, or checks the
PNG count and Pillow dimensions for rasterize; ``preview`` writes the
document preview shape (per-page PNGs rendered with pypdfium2) or the
image kind's fields per PNG; ``doctor`` proves the imports work and, at
``full`` depth, runs a tiny 2-page split-and-rasterize roundtrip.
"""

from __future__ import annotations

import importlib
import json
import re
import tempfile
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from facet_runner_sdk import Request, Runner

runner = Runner()

#: Asset base names, the manifest's own pattern, checked again runner-side.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
#: The render resolution when the piece names none.
DEFAULT_DPI = 150
#: Preview PNGs land here, under the run's output dir.
PREVIEW_DIR = "preview"
#: One-line preview summaries stay within the schema's limit.
SUMMARY_MAX = 160
#: A US Letter page, in points, for the fixtures doctor builds.
PAGE_SIZE = [612, 792]
#: A range token splits into exactly its two bounds.
RANGE_BOUNDS = 2
#: Merge needs at least two PDFs; one PDF is a copy, not a merge.
MERGE_MIN_ITEMS = 2
#: The render resolution bounds, in dots per inch.
DPI_MIN = 72
DPI_MAX = 300
#: The pages of the tiny PDF the full doctor check builds.
DOCTOR_PAGES = 2
MIME = {
    "pdf": "application/pdf",
    "png": "image/png",
}


def _tool() -> dict[str, str]:
    """The manifest's tool identity, so records name the real tool."""
    manifest = tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _pikepdf() -> Any:
    """Lazily import pikepdf so doctor reports a broken environment."""
    return importlib.import_module("pikepdf")


def _pypdfium2() -> Any:
    """Lazily import pypdfium2 so doctor reports a broken environment."""
    return importlib.import_module("pypdfium2")


def _pil_image() -> Any:
    """Lazily import PIL.Image so doctor reports a broken environment."""
    return importlib.import_module("PIL.Image")


def _capability(req: Request) -> str:
    """The bare capability name (merge, split, compress, rasterize)."""
    return req.capability.rsplit(".", 1)[-1]


def _resolve_path(piece_dir: Path, raw: object) -> Path:
    """Resolve a piece path input relative to ``piece_dir`` when relative."""
    path = Path(str(raw))
    return path if path.is_absolute() else (piece_dir / path)


def _checked_name(params: Mapping[str, Any]) -> str:
    """The asset base name, matching the manifest's pattern."""
    value = params.get("name")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("name: required")
    if not NAME_RE.fullmatch(value):
        raise ValueError(f"name: {value!r} must match {NAME_RE.pattern}")
    return value


def _page_count(path: Path) -> int:
    """The number of pages in a PDF, read with pikepdf."""
    pikepdf = _pikepdf()
    with pikepdf.open(path) as pdf:
        return len(pdf.pages)


def _parse_pages(spec: str, total: int) -> list[int]:
    """Parse ``1-3,5`` (1-based inclusive) into 0-based indices, deduped in order."""
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("pages: required")
    if total <= 0:
        raise ValueError("pages: the PDF has no pages")
    selected: list[int] = []
    for part in spec.split(","):
        selected.extend(_parse_token(part.strip(), spec, total))
    ordered = list(dict.fromkeys(selected))
    if not ordered:
        raise ValueError(f"pages: {spec!r} selects no pages")
    return ordered


def _parse_token(token: str, spec: str, total: int) -> list[int]:
    """One ``N`` or ``A-B`` token of a page selection into 0-based indices."""
    if not token:
        raise ValueError(f"pages: empty entry in {spec!r}")
    if "-" in token:
        return _parse_range(token, spec, total)
    return [_parse_number(token, spec, total)]


def _parse_number(token: str, spec: str, total: int) -> int:
    """One ``N`` token (1-based) into a 0-based index, range-checked."""
    try:
        number = int(token)
    except ValueError:
        raise ValueError(f"pages: {token!r} in {spec!r} is not a page number") from None
    if number < 1 or number > total:
        raise ValueError(f"pages: {token!r} in {spec!r} is outside 1-{total}")
    return number - 1


def _parse_range(token: str, spec: str, total: int) -> list[int]:
    """One ``A-B`` token (1-based inclusive) into 0-based indices, range-checked."""
    bounds = token.split("-")
    if len(bounds) != RANGE_BOUNDS:
        raise ValueError(f"pages: {token!r} in {spec!r} is not a page range")
    try:
        start, end = int(bounds[0]), int(bounds[1])
    except ValueError:
        raise ValueError(f"pages: {token!r} in {spec!r} is not a page range") from None
    if start < 1 or end < 1 or start > end or end > total:
        raise ValueError(f"pages: {token!r} in {spec!r} is outside 1-{total}")
    return list(range(start - 1, end))


def _asset(
    name: str,
    file: str,
    kind: str,
    mime: str,
    properties: Mapping[str, Any],
    params: Mapping[str, Any],
    inputs: list[Path],
) -> dict[str, Any]:
    """Build one asset record."""
    return {
        "file": file,
        "name": name,
        "kind": kind,
        "mime": mime,
        "properties": dict(properties),
        "params": dict(params),
        "seed": None,
        "inputs": [str(path) for path in inputs],
    }


def _run_merge(params: Mapping[str, Any], out_dir: Path, piece_dir: Path) -> list[dict[str, Any]]:
    """Combine two or more PDFs into one, in the given order."""
    raw = params.get("pdf")
    if not isinstance(raw, list) or len(raw) < MERGE_MIN_ITEMS:
        raise ValueError("merge: pdf needs at least two PDFs")
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("path")).strip():
            raise ValueError("merge: every pdf entry needs a path")
    sources = [_resolve_path(piece_dir, str(item["path"])) for item in raw]
    for source in sources:
        if not source.is_file():
            raise ValueError(f"merge: {source} is not a file")
    name = _checked_name(params)
    pikepdf = _pikepdf()
    out = out_dir / f"{name}.pdf"
    merged = pikepdf.Pdf.new()
    for source in sources:
        with pikepdf.open(source) as pdf:
            merged.pages.extend(pdf.pages)
    merged.save(out, linearize=True)
    properties = {"page_count": len(merged.pages)}
    resolved = {"pdf": [{"path": str(source)} for source in sources], "name": name}
    return [_asset(name, out.name, "document", MIME["pdf"], properties, resolved, sources)]


def _run_split(params: Mapping[str, Any], out_dir: Path, piece_dir: Path) -> list[dict[str, Any]]:
    """Extract a page range or selection from a PDF into a new PDF."""
    source = _resolve_path(piece_dir, params.get("pdf"))
    if not source.is_file():
        raise ValueError(f"split: {source} is not a file")
    name = _checked_name(params)
    spec = params.get("pages")
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("pages: required")
    pikepdf = _pikepdf()
    out = out_dir / f"{name}.pdf"
    with pikepdf.open(source) as pdf:
        selection = _parse_pages(spec, len(pdf.pages))
        trimmed = pikepdf.Pdf.new()
        for index in selection:
            trimmed.pages.append(pdf.pages[index])
        trimmed.save(out, linearize=True)
    properties = {"page_count": len(selection)}
    resolved = {"pdf": str(source), "pages": spec, "name": name}
    return [_asset(name, out.name, "document", MIME["pdf"], properties, resolved, [source])]


def _run_compress(
    params: Mapping[str, Any], out_dir: Path, piece_dir: Path
) -> list[dict[str, Any]]:
    """Recompress a PDF's streams and linearize it for fast web viewing."""
    source = _resolve_path(piece_dir, params.get("pdf"))
    if not source.is_file():
        raise ValueError(f"compress: {source} is not a file")
    name = _checked_name(params)
    pikepdf = _pikepdf()
    out = out_dir / f"{name}.pdf"
    with pikepdf.open(source) as pdf:
        count = len(pdf.pages)
        pdf.save(out, linearize=True, recompress_flate=True)
    properties = {"page_count": count}
    resolved = {"pdf": str(source), "name": name}
    return [_asset(name, out.name, "document", MIME["pdf"], properties, resolved, [source])]


def _render_page(doc: Any, index: int, dpi: int, target: Path) -> tuple[int, int]:
    """Render one PDF page to a PNG; return its pixel size."""
    page = doc[index]
    try:
        bitmap = page.render(scale=dpi / 72)
        image = bitmap.to_pil()
        image.save(target)
        return int(image.width), int(image.height)
    finally:
        page.close()


def _run_rasterize(
    params: Mapping[str, Any], out_dir: Path, piece_dir: Path
) -> list[dict[str, Any]]:
    """Render PDF pages to one PNG per page for visual inspection."""
    source = _resolve_path(piece_dir, params.get("pdf"))
    if not source.is_file():
        raise ValueError(f"rasterize: {source} is not a file")
    name = _checked_name(params)
    dpi = int(params.get("dpi", DEFAULT_DPI))
    if dpi < DPI_MIN or dpi > DPI_MAX:
        raise ValueError(f"rasterize: dpi {dpi} is outside {DPI_MIN}-{DPI_MAX}")
    pdfium = _pypdfium2()
    doc = pdfium.PdfDocument(str(source))
    try:
        total = len(doc)
        raw_pages = params.get("pages")
        selection = list(range(total)) if raw_pages is None else _parse_pages(str(raw_pages), total)
        assets: list[dict[str, Any]] = []
        for index in selection:
            target = out_dir / f"{name}-page-{index + 1:02d}.png"
            width, height = _render_page(doc, index, dpi, target)
            properties = {"page": index + 1, "width": width, "height": height, "dpi": dpi}
            resolved = {"pdf": str(source), "name": name, "dpi": dpi}
            if raw_pages is not None:
                resolved["pages"] = str(raw_pages)
            assets.append(
                _asset(
                    target.stem, target.name, "image", MIME["png"], properties, resolved, [source]
                )
            )
        return assets
    finally:
        doc.close()


CAPABILITY_VERBS: dict[str, Callable[[Mapping[str, Any], Path, Path], list[dict[str, Any]]]] = {
    "merge": _run_merge,
    "split": _run_split,
    "compress": _run_compress,
    "rasterize": _run_rasterize,
}


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    """Execute the requested pdf-ops capability."""
    req.out_dir.mkdir(parents=True, exist_ok=True)
    verb = CAPABILITY_VERBS.get(_capability(req))
    if verb is None:
        known = ", ".join(sorted(CAPABILITY_VERBS))
        raise ValueError(f"{req.capability}: unknown capability (this runner has: {known})")
    return {"tool": _tool(), "assets": verb(dict(req.inputs), req.out_dir, req.piece_dir)}


def _expected_pages(cap: str, params: Mapping[str, Any], piece_dir: Path) -> int:
    """The page count verify demands, derived from the piece's own inputs."""
    if cap == "merge":
        raw = params.get("pdf")
        if not isinstance(raw, list):
            raise ValueError("merge: pdf must be an array")
        return sum(_page_count(_resolve_path(piece_dir, str(item["path"]))) for item in raw)
    source = _resolve_path(piece_dir, params.get("pdf"))
    total = _page_count(source)
    if cap == "split":
        return len(_parse_pages(str(params.get("pages")), total))
    if cap == "compress":
        return total
    raise ValueError(f"{cap}: no document verifier for this capability")


def _verify_document(path: Path, expected: int) -> dict[str, Any]:
    """Re-open a produced PDF with pikepdf and demand its exact page count."""
    actual = _page_count(path)
    return {
        "file": path.name,
        "passed": actual == expected and actual > 0,
        "metrics": {"page_count": actual, "expected_page_count": expected},
        "thresholds": {"page_count_min": 1},
        "verifier": "pikepdf",
    }


def _image_size(path: Path) -> tuple[int, int]:
    """Open an image with Pillow and return ``(width, height)``."""
    image_mod = _pil_image()
    with image_mod.open(path) as img:
        img.load()
        width, height = img.size
    return int(width), int(height)


def _verify_rasterize(
    assets: list[Path], params: Mapping[str, Any], piece_dir: Path
) -> list[dict[str, Any]]:
    """Demand the expected PNG count with positive Pillow dimensions each."""
    source = _resolve_path(piece_dir, params.get("pdf"))
    total = _page_count(source)
    raw_pages = params.get("pages")
    expected = total if raw_pages is None else len(_parse_pages(str(raw_pages), total))
    verdicts: list[dict[str, Any]] = []
    for path in assets:
        try:
            width, height = _image_size(path)
        except Exception as exc:  # corrupt PNGs fail verification, never the verb
            verdicts.append(_failed_png(path, expected, str(exc)))
            continue
        verdicts.append(
            {
                "file": path.name,
                "passed": len(assets) == expected and width > 0 and height > 0,
                "metrics": {
                    "page_count": len(assets),
                    "expected_page_count": expected,
                    "width": width,
                    "height": height,
                },
                "thresholds": {"page_count_min": 1},
                "verifier": "pillow",
            }
        )
    return verdicts


def _failed_png(path: Path, expected: int, error: str) -> dict[str, Any]:
    """A PNG Pillow cannot read fails verification with the reason kept."""
    return {
        "file": path.name,
        "passed": False,
        "metrics": {"page_count": 1, "expected_page_count": expected, "error": error},
        "thresholds": {"page_count_min": 1},
        "verifier": "pillow",
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    """Verify every generated asset for the requested capability."""
    cap = _capability(req)
    if cap not in CAPABILITY_VERBS:
        raise ValueError(f"{req.capability}: no verifier for this capability")
    params = dict(req.inputs)
    if cap == "rasterize":
        return {"assets": _verify_rasterize(list(req.assets), params, req.piece_dir)}
    expected = _expected_pages(cap, params, req.piece_dir)
    return {"assets": [_verify_document(path, expected) for path in req.assets]}


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


def _preview_one(req: Request, path: Path) -> dict[str, Any]:
    """Render a PDF's pages into per-page PNGs and write its preview file."""
    out_dir = req.out_dir / PREVIEW_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    pdfium = _pypdfium2()
    doc = pdfium.PdfDocument(str(path))
    try:
        names: list[str] = []
        for index in range(len(doc)):
            target = out_dir / f"page-{index + 1:02d}.png"
            _render_page(doc, index, DEFAULT_DPI, target)
            names.append(target.name)
    finally:
        doc.close()
    if not names:
        raise RuntimeError(f"{path.name}: the PDF has no pages to preview")
    pages = [f"{PREVIEW_DIR}/{name}" for name in names]
    preview_name = f"{path.name}.preview.json"
    data = _preview_data(path, pages)
    (req.out_dir / preview_name).write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"file": path.name, "preview": preview_name, "images": []}


def _image_preview_data(path: Path, prompt: str) -> dict[str, Any]:
    """Build preview JSON matching the image preview schema."""
    width, height = _image_size(path)
    return {
        "preview": 1,
        "kind": "image",
        "summary": f"rasterize · {width}x{height}"[:SUMMARY_MAX],
        "name": _preview_name(path.stem),
        "prompt": prompt,
        "seed": 0,
        "width": width,
        "height": height,
    }


def _preview_name(raw: str) -> str:
    """Normalize an asset stem to match ``^[a-z0-9][a-z0-9-]*$``."""
    cleaned = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")
    return cleaned or "asset"


def _preview_png(req: Request, path: Path) -> dict[str, Any]:
    """Write the image kind's preview fields for one rasterized PNG."""
    preview_name = f"{path.name}.preview.json"
    data = _image_preview_data(path, f"pdf-ops rasterize of {path.stem}")
    (req.out_dir / preview_name).write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"file": path.name, "preview": preview_name, "images": []}


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    """Write ``<asset>.preview.json`` for every asset."""
    req.out_dir.mkdir(parents=True, exist_ok=True)
    cap = _capability(req)
    if cap not in CAPABILITY_VERBS:
        raise ValueError(f"{req.capability}: no preview for this capability")
    if cap == "rasterize":
        entries = [_preview_png(req, path) for path in req.assets]
    else:
        entries = [_preview_one(req, path) for path in req.assets]
    return {"assets": entries}


def _doctor_check(ok: bool, detail: str, fix: str, name: str = "pdf-ops") -> dict[str, Any]:
    """One doctor check; a failure names what fixes the machine."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _quick_checks() -> list[dict[str, Any]]:
    """Prove the three heavy imports resolve."""
    checks: list[dict[str, Any]] = []
    for module in ("pikepdf", "pypdfium2", "PIL"):
        try:
            importlib.import_module(module)
        except ImportError as exc:
            checks.append(
                _doctor_check(False, f"{module} cannot be imported: {exc}", "facet pull", module)
            )
        else:
            checks.append(_doctor_check(True, f"{module} imports cleanly", "", module))
    return checks


def _blank_pdf(path: Path, pages: int) -> None:
    """Write a tiny blank PDF with ``pages`` pages for the full roundtrip."""
    pikepdf = _pikepdf()
    pdf = pikepdf.Pdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=PAGE_SIZE)
    pdf.save(path)


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    """Check imports quickly; at full depth run a split-and-rasterize roundtrip."""
    checks = _quick_checks()
    if req.depth != "full":
        return {"checks": checks}
    if not all(check["ok"] for check in checks):
        return {"checks": checks}
    with tempfile.TemporaryDirectory(prefix="pdf-ops-doctor-") as folder:
        tmp = Path(folder)
        source = tmp / "doctor.pdf"
        _blank_pdf(source, DOCTOR_PAGES)
        if _page_count(source) != DOCTOR_PAGES:
            return {"checks": [*checks, _doctor_check(False, "blank PDF has no 2 pages", "")]}
        params: dict[str, Any] = {"pdf": source.name, "pages": "1", "name": "doctor-split"}
        split_assets = _run_split(params, tmp, tmp)
        raster_params: dict[str, Any] = {
            "pdf": Path(split_assets[0]["file"]).name,
            "name": "doctor-page",
            "dpi": DEFAULT_DPI,
        }
        png_assets = _run_rasterize(raster_params, tmp, tmp)
        width, height = _image_size(tmp / png_assets[0]["file"])
        detail = f"2-page PDF splits to 1 page and rasterizes to {width}x{height} PNG"
        checks.append(_doctor_check(width > 0 and height > 0, detail, ""))
    return {"checks": checks}


runner.main()
