"""The whisper-subs package runner: validated subtitles from a sidecar.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` reads the piece's ``origen`` — a whisper
``<name>.json`` sidecar whose ``segments`` carry ``start_s``, ``end_s``
and ``text`` — validates the cues in order and writes
``<origen-stem>.srt`` (comma times) or ``.vtt`` (``WEBVTT``, dot times)
beside the piece; ``verify`` re-parses the written file and judges cue
count, duration, monotonic order and header; ``preview`` writes the
generic viewer's fields; ``doctor`` checks the package files and the
timestamp formats at quick depth and builds both formats from a stub
sidecar at full depth. There is no model and nothing heavy: the whole
package is stdlib, so a broken environment is not a question here.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import formats
from facet_runner_sdk import Request, Runner

runner = Runner()

#: The formats the manifest's ``formato`` enum allows, with their mimes.
FORMATS = ("srt", "vtt")
MIME = {"srt": "application/x-subrip", "vtt": "text/vtt"}
#: The manifest's verify threshold, repeated so run never drifts from it.
CUES_MIN = 1
#: The doctor's stub sidecar: two cues, the second touching the first.
SIDECAR_STUB = {
    "segments": [
        {"start_s": 0.0, "end_s": 1.5, "text": "Hola."},
        {"start_s": 1.5, "end_s": 2.25, "text": "Mundo."},
    ]
}
PACKAGE_FILES = ("package.toml", "formats.py", "skill/SKILL.md")


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    """The manifest's tool name and version, named for the record."""
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _origen(params: dict[str, Any], req: Request) -> Path:
    """The piece's whisper sidecar, resolved against the piece directory."""
    raw = params.get("origen")
    if not raw:
        raise ValueError("the piece has no origen")
    path = Path(str(raw))
    if not path.is_absolute():
        path = req.piece_dir / path
    if not path.is_file():
        raise ValueError(f"{raw}: no such origen")
    return path


def _formato(params: dict[str, Any]) -> str:
    """The output format, defaulted to ``srt`` the way the manifest does."""
    formato = str(params.get("formato", "srt"))
    if formato not in FORMATS:
        raise ValueError(f"formato desconocido {formato!r}: usa srt o vtt")
    return formato


def _formato_of(path: Path) -> str:
    """The format an asset file carries, named by its suffix."""
    return path.suffix.lower().removeprefix(".")


def _asset_name(stem: str) -> str:
    """A stem folded into the record's ``[a-z0-9][a-z0-9-]*`` name shape."""
    name = re.sub(r"[^a-z0-9-]+", "-", stem.lower()).strip("-")
    return name or "subtitulos"


def _asset(
    origen: Path, formato: str, path: Path, cues: Sequence[formats.Cue], params: dict[str, Any]
) -> dict[str, Any]:
    """One subtitle record: text kind, the monotonically checked timings."""
    return {
        "file": path.name,
        "name": _asset_name(origen.stem),
        "kind": "text",
        "mime": MIME[formato],
        "properties": {
            "cues": len(cues),
            "duration_s": round(cues[-1].end_s, 3),
            "formato": formato,
        },
        "params": {"origen": str(params.get("origen", "")), "formato": formato},
        "seed": None,
        "inputs": [str(params.get("origen", ""))],
    }


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    """Validate the sidecar and write the subtitle file beside the piece."""
    params = dict(req.inputs)
    origen = _origen(params, req)
    formato = _formato(params)
    cues = formats.read_sidecar(origen)
    formats.validate_cues(cues)
    body = formats.to_vtt(cues) if formato == "vtt" else formats.to_srt(cues)
    path = req.out_dir / f"{origen.stem}.{formato}"
    path.write_text(body, encoding="utf-8")
    return {"tool": _tool(), "assets": [_asset(origen, formato, path, cues, params)]}


def _verdict(file: str, passed: bool, metrics: dict[str, Any]) -> dict[str, Any]:
    """One verdict; the manifest's threshold stands even on a broken file."""
    return {
        "file": file,
        "passed": passed,
        "metrics": metrics,
        "thresholds": {"cues_min": CUES_MIN},
        "verifier": "whisper-subs",
    }


def _subtitle_metrics(text: str, formato: str) -> dict[str, Any]:
    """What verify reports: the cues, the last end, the order, the header."""
    timings = formats.parse_timings(text)
    return {
        "cues": len(timings),
        "duration_s": round(timings[-1][1] / formats.MILLISECONDS_PER_SECOND, 3)
        if timings
        else 0.0,
        "monotonic": _monotonic(timings),
        "header": _header_ok(text, formato),
    }


def _monotonic(timings: Sequence[tuple[int, int]]) -> bool:
    """Each cue starts at or after the previous one ends; touching is fine."""
    return all(
        current[0] >= previous[1] for previous, current in zip(timings, timings[1:], strict=False)
    )


def _header_ok(text: str, formato: str) -> bool:
    """SRT opens on cue ``1``; VTT opens on the ``WEBVTT`` header line."""
    if formato == "vtt":
        return text.startswith("WEBVTT")
    first = text.splitlines()[0].strip() if text else ""
    return first == "1"


def _verify_asset(path: Path) -> dict[str, Any]:
    """The file re-parses: cues over the minimum, in order, headered."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return _verdict(path.name, False, {"error": str(exc), "cues": 0, "monotonic": False})
    metrics = _subtitle_metrics(text, _formato_of(path))
    passed = metrics["cues"] >= CUES_MIN and metrics["monotonic"] and metrics["header"]
    return _verdict(path.name, passed, metrics)


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    return {"assets": [_verify_asset(path) for path in req.assets]}


def _preview_data(path: Path) -> dict[str, Any]:
    """The generic preview: cue count, last cue's end, the format."""
    formato = _formato_of(path)
    metrics = _subtitle_metrics(path.read_text(encoding="utf-8"), formato)
    fields = {
        "cues": metrics["cues"],
        "duration_s": metrics["duration_s"],
        "formato": formato,
    }
    summary = f"{fields['cues']} cues \u00b7 {fields['duration_s']:.1f} s \u00b7 {formato}"
    return {"preview": 1, "kind": "text", "summary": summary, "fields": fields}


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    """One generic preview file per asset, like the viewer expects."""
    entries = []
    for path in req.assets:
        preview_name = f"{path.name}.preview.json"
        data = _preview_data(path)
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names the pull that fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_files() -> dict[str, Any]:
    """The package's files are pulled: manifest, formats and skill."""
    package = Path(__file__).resolve().parent
    missing = [name for name in PACKAGE_FILES if not (package / name).is_file()]
    if missing:
        return _check("files", False, f"missing: {', '.join(missing)}", "facet pull whisper-subs")
    return _check("files", True, ", ".join(PACKAGE_FILES))


def _doctor_formats() -> dict[str, Any]:
    """One offset through both separators: comma for SRT, dot for VTT."""
    comma = formats.format_timestamp(1.5, sep=",")
    dot = formats.format_timestamp(1.5, sep=".")
    if comma != "00:00:01,500" or dot != "00:00:01.500":
        detail = f"got {comma!r} and {dot!r}"
        return _check("formats", False, detail, "facet pull whisper-subs")
    return _check("formats", True, f"srt {comma} \u00b7 vtt {dot}")


def _doctor_bytes_ok(srt_text: str, vtt_text: str) -> None:
    """Both builds carry the stub's times in their own separator."""
    if "00:00:01,500 --> 00:00:02,250" not in srt_text:
        raise ValueError(f"the .srt build is wrong: {srt_text!r}")
    if not vtt_text.startswith("WEBVTT\n\n") or "00:00:01.500 --> 00:00:02.250" not in vtt_text:
        raise ValueError(f"the .vtt build is wrong: {vtt_text!r}")


def _doctor_subtitulos(req: Request) -> dict[str, Any]:
    """Full depth: the stub sidecar builds both formats in the out dir."""
    sidecar = req.out_dir / "doctor.origen.json"
    srt = req.out_dir / "doctor.srt"
    vtt = req.out_dir / "doctor.vtt"
    try:
        sidecar.write_text(json.dumps(SIDECAR_STUB, ensure_ascii=False), encoding="utf-8")
        cues = formats.read_sidecar(sidecar)
        formats.validate_cues(cues)
        string_by_file = {
            srt: formats.to_srt(cues),
            vtt: formats.to_vtt(cues),
        }
        _doctor_bytes_ok(string_by_file[srt], string_by_file[vtt])
    except (OSError, ValueError) as exc:
        return _check("subtitulos", False, str(exc), "facet pull whisper-subs")
    finally:
        sidecar.unlink(missing_ok=True)
        srt.unlink(missing_ok=True)
        vtt.unlink(missing_ok=True)
    return _check("subtitulos", True, "2 cues \u2192 doctor.srt + doctor.vtt beside the piece")


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    """Quick: the files and the timestamp formats. Full: also the build."""
    checks = [_doctor_files(), _doctor_formats()]
    if req.depth == "full":
        checks.append(_doctor_subtitulos(req))
    return {"checks": checks}


runner.main()
