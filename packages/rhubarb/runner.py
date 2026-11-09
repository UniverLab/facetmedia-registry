"""The rhubarb package runner: mouth cues for a drawn character.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` extracts the pinned Rhubarb Lip Sync 1.14.0 zip
once, runs its ELF with the phonetic recognizer and JSON output, and reads the
``bocas.json`` it writes back as one ``text`` asset; ``verify`` judges that
file's mouth cues; ``preview`` writes the generic mouth-timeline preview;
``doctor`` checks the zip and the extracted binary at ``quick`` depth.

The Rhubarb CLI does not speak the runner protocol — its argv is
``rhubarb [options] <wav> -o file``, never ``run --input/--result`` — so the
package is a python-env subprocess client, not a ``[engine.binary]`` package.
The default recognizer is English-only (pocketSphinx); every run passes
``-r phonetic``, and :func:`check_phonetic` refuses an argv that lost it, so a
Spanish piece cannot silently come out with English mouths.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tomllib
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from facet_runner_sdk import Request, Runner

runner = Runner()

#: The manifest's model id and the tool version it pins, named for the record.
MODEL_ID = "rhubarb-lip-sync-1.14.0-linux"
TOOL = {"name": "rhubarb-lip-sync", "version": "1.14.0"}
VERIFIER = "rhubarb-lip-sync-1.14.0"
#: The one asset a run writes, and the mouth alphabet Rhubarb emits.
OUT_NAME = "bocas.json"
MOUTH_VALUES = "XABCDEFGH"
#: The recognizer and output flags every run carries. ``phonetic`` is the
#: Spanish-capable recognizer; the default is English-only.
RECOGNIZER_ARGS = ("-r", "phonetic")
FORMAT_ARGS = ("-f", "json")
#: The zip's inner layout: one top directory holding the ELF with ``res/``
#: beside it, which the binary reads from its own directory.
TOP_DIR = "Rhubarb-Lip-Sync-1.14.0-Linux"
ELF_NAME = "rhubarb"
#: Where the zip is unpacked: beside this runner, once per zip hash.
EXTRACT_DIRNAME = "_rhubarb-lip-sync-1.14.0-linux"
MARKER_NAME = "zip.sha256"
#: The extraction directory's override, for a host that keeps the package
#: directory read-only or an operator testing a spare zip.
EXTRACT_ENV = "RHUBARB_HOME"
#: The manifest's verify threshold, repeated here so a run never drifts from it.
CUES_MIN = 1
THRESHOLDS = {"cues_min": float(CUES_MIN)}
#: Rhubarb takes about a second; the probe is only a platform check.
RUN_TIMEOUT_S = 120
PROBE_TIMEOUT_S = 15
PHONETIC_TRAP = (
    "rhubarb argv lacks -r phonetic: the default recognizer is English-only "
    "(pocketSphinx), so a Spanish dialog would come out with English mouths"
)


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the doctor's model byte size."""
    return tomllib.loads((Path(__file__).resolve().parent / "package.toml").read_text("utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_dir() -> Path:
    """The extraction lives beside this runner, so ``res/`` travels with the ELF."""
    override = os.environ.get(EXTRACT_ENV, "").strip()
    base = Path(override) if override else Path(__file__).resolve().parent
    return base / EXTRACT_DIRNAME


def _elf_path(root: Path) -> Path:
    return root / TOP_DIR / ELF_NAME


def _elf(archive: Path) -> Path:
    """The pinned ELF, unpacking the zip once and again whenever its hash changes."""
    if not archive.is_file():
        raise RuntimeError(f"{archive}: the Rhubarb zip is missing; run facet pull rhubarb")
    digest = _sha256(archive)
    root = _extract_dir()
    marker = root / MARKER_NAME
    elf = _elf_path(root)
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest and elf.is_file():
        return elf
    _unpack(archive, root, digest)
    return elf


def _unpack(archive: Path, root: Path, digest: str) -> None:
    """Extract the whole zip, make the ELF executable, and mark it with its hash."""
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(root)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"{archive}: cannot extract the Rhubarb zip: {exc}") from exc
    elf = _elf_path(root)
    if not elf.is_file():
        raise RuntimeError(f"{archive}: the zip has no {TOP_DIR}/{ELF_NAME}")
    elf.chmod(0o755)
    (root / MARKER_NAME).write_text(digest + "\n", encoding="utf-8")


def command(elf: Path, voz: Path, dialogo: Path, out: Path) -> list[str]:
    """The argv Rhubarb takes: options, then the dialog, the voice and ``-o``."""
    return [
        str(elf),
        *RECOGNIZER_ARGS,
        *FORMAT_ARGS,
        "--dialogFile",
        str(dialogo),
        str(voz),
        "-o",
        str(out),
    ]


def check_phonetic(argv: Sequence[str]) -> None:
    """Refuse an argv without ``-r phonetic``, naming the English-default trap."""
    for index, token in enumerate(argv):
        if token == "-r" and list(argv[index + 1 : index + 2]) == ["phonetic"]:
            return
    raise RuntimeError(PHONETIC_TRAP)


def _execute(argv: Sequence[str], cwd: Path) -> None:
    """Run Rhubarb from the job out dir; a non-zero exit fails the run.

    The out dir and the ``-o`` path arrive absolute, so this cwd only picks where
    Rhubarb's relative work happens. A relative ``-o`` combined with a changed
    cwd writes nowhere and dies with ``basic_ios::clear: iostream error`` after
    100% progress; an absolute ``-o`` passes from any cwd. The ELF is absolute,
    so ``res/`` still resolves.
    """
    try:
        done = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"rhubarb could not run: {exc}") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-3:]
        raise RuntimeError(f"rhubarb exited {done.returncode}: {' / '.join(tail)}")


def _read_bocas(path: Path) -> dict[str, Any]:
    """Parse Rhubarb's JSON: the duration and the X..H mouth cues."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path.name}: cannot read the mouth JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name}: the mouth JSON is not an object")
    raw = loaded.get("mouthCues")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path.name}: no mouthCues")
    cues = [_cue(item, path.name) for item in raw]
    metadata = loaded.get("metadata")
    duration = metadata.get("duration") if isinstance(metadata, dict) else None
    duration_s = round(float(duration), 3) if _number(duration) else cues[-1]["end"]
    return {"duration_s": duration_s, "cues": cues}


def _cue(item: object, name: str) -> dict[str, Any]:
    """One mouth cue: an X..H letter and a start/end span in seconds."""
    if not isinstance(item, dict):
        raise ValueError(f"{name}: a mouth cue is not an object")
    value = str(item.get("value", ""))
    if len(value) != 1 or value not in MOUTH_VALUES:
        raise ValueError(f"{name}: {value!r} is not one of the mouths {MOUTH_VALUES}")
    start, end = item.get("start"), item.get("end")
    if not _number(start) or not _number(end) or float(end) < float(start):
        raise ValueError(f"{name}: the {value} cue spans {start!r}..{end!r}")
    return {"start": round(float(start), 3), "end": round(float(end), 3), "value": value}


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _mouths(cues: Sequence[Mapping[str, Any]]) -> list[str]:
    """The distinct mouths the cues use, in the alphabet's order."""
    used = {str(cue["value"]) for cue in cues}
    return [letter for letter in MOUTH_VALUES if letter in used]


def _properties(data: Mapping[str, Any]) -> dict[str, Any]:
    cues = data["cues"]
    return {
        "duration_s": data["duration_s"],
        "cues": len(cues),
        "mouths": len(_mouths(cues)),
    }


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    voz = Path(str(params["voz"]))
    dialogo = Path(str(params["dialogo"]))
    out_dir = Path(os.path.abspath(req.out_dir))
    out = out_dir / OUT_NAME
    elf = _elf(req.model_path(MODEL_ID))
    argv = command(elf, voz, dialogo, out)
    check_phonetic(argv)
    _execute(argv, out_dir)
    data = _read_bocas(out)
    return {"tool": dict(TOOL), "assets": [_asset(params, voz, dialogo, data)]}


def _asset(
    params: Mapping[str, Any], voz: Path, dialogo: Path, data: Mapping[str, Any]
) -> dict[str, Any]:
    """The one ``text`` asset: bocas.json with its mouth-timeline properties."""
    return {
        "file": OUT_NAME,
        "name": "bocas",
        "kind": "text",
        "mime": "application/json",
        "properties": _properties(data),
        "params": {"voz": str(voz), "dialogo": str(dialogo)},
        "seed": None,
        "inputs": [str(voz), str(dialogo)],
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    return {"assets": [_verdict(path) for path in req.assets]}


def _verdict(path: Path) -> dict[str, Any]:
    """Judge one bocas.json: it parses, its mouths are X..H, and it is ordered."""
    try:
        data = _read_bocas(path)
    except ValueError as exc:
        return _entry(path.name, False, {"error": str(exc)})
    cues = data["cues"]
    starts = [cue["start"] for cue in cues]
    ordered = starts == sorted(starts)
    metrics = {**_properties(data), "ordered": ordered}
    return _entry(path.name, len(cues) >= CUES_MIN and ordered, metrics)


def _entry(file: str, passed: bool, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "file": file,
        "passed": passed,
        "metrics": metrics,
        "thresholds": dict(THRESHOLDS),
        "verifier": VERIFIER,
    }


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    entries = []
    for path in req.assets:
        if path.suffix.lower() != ".json":
            raise ValueError(f"{path.name}: preview bocas.json, not this file")
        name = f"{path.name}.preview.json"
        data = _preview(path)
        body = json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n"
        (req.out_dir / name).write_text(body, encoding="utf-8")
        entries.append({"file": path.name, "preview": name, "images": []})
    return {"assets": entries}


def _preview(path: Path) -> dict[str, Any]:
    """The generic preview: the mouth timeline as text, never the cue list."""
    data = _read_bocas(path)
    cues = data["cues"]
    mouths = _mouths(cues)
    fields = {
        **_properties(data),
        "recognizer": "phonetic",
        "mouths_used": "".join(mouths),
    }
    summary = (
        f"{float(data['duration_s']):.1f} s · {len(cues)} mouth cues · "
        f"{len(mouths)} mouths ({''.join(mouths)})"
    )
    return {"preview": 1, "kind": "text", "summary": summary, "fields": fields}


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    return {"checks": [_doctor_zip(req), _doctor_binary(req)]}


def _pull_fix(ok: bool) -> str:
    return "" if ok else "facet pull rhubarb"


def _doctor_zip(req: Request) -> dict[str, Any]:
    """The pinned zip sits under models/direct with the manifest's byte size."""
    expected = {str(model["id"]): int(model["bytes"]) for model in _manifest().get("models", [])}
    want = expected.get(MODEL_ID, 0)
    try:
        archive = req.model_path(MODEL_ID)
    except KeyError:
        return _check("zip", False, f"{MODEL_ID}: not in this request", _pull_fix(False))
    if not archive.is_file():
        return _check("zip", False, f"{archive}: missing", _pull_fix(False))
    actual = archive.stat().st_size
    if actual != want:
        return _check(
            "zip", False, f"{archive}: {actual} bytes, manifest says {want}", _pull_fix(False)
        )
    return _check("zip", True, f"{MODEL_ID} {actual} B", "")


def _doctor_binary(req: Request) -> dict[str, Any]:
    """The extracted ELF is executable and can start on this machine.

    A missing or corrupt zip is pull-fixable; a verified extraction that cannot
    run — a binary built for another platform — is ``machine_cannot`` instead,
    so its fix is empty.
    """
    try:
        elf = _elf(req.model_path(MODEL_ID))
    except (KeyError, OSError, RuntimeError) as exc:
        return _check("binary", False, str(exc), _pull_fix(False))
    if not os.access(elf, os.X_OK):
        return _check("binary", False, f"{elf}: the extracted ELF is not executable", "")
    problem = _probe(elf, req.out_dir)
    if problem is not None:
        return _check("binary", False, f"{elf}: {problem}", "")
    return _check("binary", True, f"{elf}: starts on this machine", "")


def _probe(elf: Path, cwd: Path) -> str | None:
    """Ask the binary for its usage; ``None`` when the kernel can start it.

    Any exit code is fine: Rhubarb answers usage with one. Only a failure to
    start — ``ENOEXEC``, the wrong architecture, a missing dynamic loader —
    makes this return a problem.
    """
    try:
        subprocess.run(
            [str(elf), "--help"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"cannot run on this machine ({exc})"
    return None


def _check(name: str, ok: bool, detail: str, fix: str) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "fix": fix}


if __name__ == "__main__":
    runner.main()
