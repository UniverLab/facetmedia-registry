"""The rhubarb package runner: mouth cues for a drawn character.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` extracts the pinned Rhubarb Lip Sync 1.14.0 zip
once, runs its ELF with the phonetic recognizer and JSON output, and reads the
``mouths.json`` it writes back as one ``text`` asset; ``verify`` judges that
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
import wave
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
OUT_NAME = "mouths.json"
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
#: Rhubarb emits cues in hundredths of a second; the last cue ends at the voice.
VOICE_END_TOLERANCE_S = 0.01
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


def command(elf: Path, voice: Path, dialogue: Path, out: Path) -> list[str]:
    """The argv Rhubarb takes: options, then the dialog, the voice and ``-o``."""
    return [
        str(elf),
        *RECOGNIZER_ARGS,
        *FORMAT_ARGS,
        "--dialogFile",
        str(dialogue),
        str(voice),
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


def _read_mouths(path: Path) -> dict[str, Any]:
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
    voice = Path(str(params["voice"]))
    dialogue = Path(str(params["dialogue"]))
    out_dir = Path(os.path.abspath(req.out_dir))
    out = out_dir / OUT_NAME
    elf = _elf(req.model_path(MODEL_ID))
    argv = command(elf, voice, dialogue, out)
    check_phonetic(argv)
    _execute(argv, out_dir)
    data = _read_mouths(out)
    return {"tool": dict(TOOL), "assets": [_asset(params, voice, dialogue, data)]}


def _asset(
    params: Mapping[str, Any], voice: Path, dialogue: Path, data: Mapping[str, Any]
) -> dict[str, Any]:
    """The one ``text`` asset: mouths.json with its mouth-timeline properties."""
    return {
        "file": OUT_NAME,
        "name": "mouths",
        "kind": "text",
        "mime": "application/json",
        "properties": _properties(data),
        "params": {"voice": str(voice), "dialogue": str(dialogue)},
        "seed": None,
        "inputs": [str(voice), str(dialogue)],
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    return {"assets": [_verdict(path, req) for path in req.assets]}


def _voice_duration(path: Path) -> float:
    """The voice file's measured seconds: WAV via the header, Ogg via last page."""
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return _wav_duration(path)
    if suffix == ".ogg":
        return _ogg_duration(path)
    raise ValueError(f"{path.name}: voice must be WAV or Ogg Vorbis, got {suffix or 'no suffix'}")


def _wav_duration(path: Path) -> float:
    """The WAV header's frames over its rate, matching the voice the cues follow."""
    try:
        with wave.open(str(path), "rb") as reader:
            rate = reader.getframerate()
            frames = reader.getnframes()
    except (OSError, wave.Error) as exc:
        raise ValueError(f"{path.name}: cannot read the WAV header: {exc}") from exc
    if not rate:
        raise ValueError(f"{path.name}: the WAV header carries no sample rate")
    return frames / rate


def _ogg_duration(path: Path) -> float:
    """The Ogg Vorbis duration from the last page's granule over its rate."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{path.name}: cannot read the Ogg file: {exc}") from exc
    rate = _ogg_rate(raw, path)
    granule = _ogg_last_granule(raw)
    if granule is None:
        raise ValueError(f"{path.name}: the Ogg carries no Vorbis granule")
    return granule / rate


def _ogg_rate(raw: bytes, path: Path) -> int:
    """The Vorbis identification header's sample rate."""
    marker = b"\x01vorbis"
    at = raw.find(marker)
    if at == -1 or at + len(marker) + 9 > len(raw):
        raise ValueError(f"{path.name}: the Ogg has no Vorbis identification header")
    rate = int.from_bytes(raw[at + len(marker) + 5 : at + len(marker) + 9], "little")
    if not rate:
        raise ValueError(f"{path.name}: the Ogg header carries no sample rate")
    return rate


def _ogg_last_granule(raw: bytes) -> int | None:
    """The last Ogg page's granule position, walking the page segments."""
    granule: int | None = None
    at = 0
    while True:
        at = raw.find(b"OggS", at)
        if at == -1 or at + 27 > len(raw):
            return granule
        segments = raw[at + 26]
        if at + 27 + segments > len(raw):
            return granule
        table = raw[at + 27 : at + 27 + segments]
        size = sum(table)
        granule = int.from_bytes(raw[at + 6 : at + 14], "little")
        at += 27 + segments + size


def _verdict(path: Path, req: Request) -> dict[str, Any]:
    """Judge one mouths.json: parses, starts at 0, rises, ends with the voice."""
    try:
        data = _read_mouths(path)
    except ValueError as exc:
        return _entry(path.name, False, {"error": str(exc)})
    cues = data["cues"]
    problems = _start_problems(cues)
    voice_s, voice_problem = _measured_voice(req)
    if voice_problem is not None:
        problems.append(voice_problem)
    elif voice_s is not None:
        tail = _tail_problem(cues[-1]["end"], voice_s)
        if tail is not None:
            problems.append(tail)
    ordered = _strictly_ordered(cues)
    metrics = {
        **_properties(data),
        "ordered": ordered,
        "voice_s": round(voice_s, 3) if voice_s is not None else None,
    }
    if problems:
        return _entry(path.name, False, {**metrics, "error": "; ".join(problems)})
    return _entry(path.name, len(cues) >= CUES_MIN and ordered, metrics)


def _start_problems(cues: Sequence[Mapping[str, Any]]) -> list[str]:
    """Each cue that does not start after the previous one, naming its index."""
    problems: list[str] = []
    if cues[0]["start"] != 0:
        problems.append(f"cue 0 starts at {cues[0]['start']}, not 0")
    for index in range(1, len(cues)):
        if not cues[index]["start"] > cues[index - 1]["start"]:
            problems.append(
                f"cue {index} starts at {cues[index]['start']}, "
                f"not after cue {index - 1} at {cues[index - 1]['start']}"
            )
    return problems


def _strictly_ordered(cues: Sequence[Mapping[str, Any]]) -> bool:
    """True only when every cue starts after the previous one."""
    starts = [cue["start"] for cue in cues]
    return all(later > earlier for earlier, later in zip(starts, starts[1:], strict=False))


def _measured_voice(req: Request) -> tuple[float | None, str | None]:
    """The input voice's duration, or the failure naming why it cannot be tied."""
    try:
        return _voice_duration(_voice_path(req)), None
    except ValueError as exc:
        return None, str(exc)


def _tail_problem(cue_end: float, voice_s: float) -> str | None:
    """The last cue must end where the voice ends, within Rhubarb's centiseconds."""
    if abs(cue_end - voice_s) > VOICE_END_TOLERANCE_S:
        return f"the last cue ends at {cue_end}, the voice lasts {round(voice_s, 3)}"
    return None


def _voice_path(req: Request) -> Path:
    """The request's voice input, resolved against the piece dir."""
    raw = req.inputs.get("voice")
    if raw is None or str(raw) == "":
        raise ValueError("verify needs the voice input to tie the cues to the voice")
    candidate = Path(str(raw))
    base = Path(str(req.piece_dir)) if str(req.piece_dir) else Path(".")
    return candidate if candidate.is_absolute() else base / candidate


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
            raise ValueError(f"{path.name}: preview mouths.json, not this file")
        name = f"{path.name}.preview.json"
        data = _preview(path)
        body = json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n"
        (req.out_dir / name).write_text(body, encoding="utf-8")
        entries.append({"file": path.name, "preview": name, "images": []})
    return {"assets": entries}


def _preview(path: Path) -> dict[str, Any]:
    """The generic preview: the mouth timeline as text, never the cue list."""
    data = _read_mouths(path)
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
