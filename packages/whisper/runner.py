"""The whisper package runner: transcription on CPU, judged by confidence.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` transcribes the audio with faster-whisper
``small`` on CPU and writes the transcript, the subtitles and the timed JSON
sidecar; ``verify`` judges the transcript by the model's own confidence and,
when the piece carries the reference text, by the word error rate against it;
``preview`` writes the generic preview file; ``doctor`` checks the tool at
``quick`` and ``full`` depth.

Heavy imports go through ``importlib`` inside the functions: the pure side
(``textnorm``, ``formats``) is stdlib-only, so a broken environment still
lets the doctor report *which* import fails instead of dying on a top-level
import.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import sys
import tempfile
import time
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import formats
import textnorm
from facet_runner_sdk import Request, Runner

runner = Runner()

#: The manifest's model id and what verify measured with, named for the record.
MODEL_ID = "faster-whisper-small-transcribe"
VERIFIER = "faster-whisper-small@536b0662"
#: The tool is pinned by the manifest and the lock.
TOOL = {"name": "faster-whisper", "version": "1.2.1"}
#: The manifest's verify thresholds, repeated here so a run never drifts from them.
MIN_AVG_LOGPROB = -1.0
MAX_NO_SPEECH_SHARE = 0.2
WER_MAX = 0.10
#: A segment above this ``no_speech_prob`` is the model hearing non-speech.
NO_SPEECH_PROB = 0.6
THRESHOLDS = {
    "min_avg_logprob": MIN_AVG_LOGPROB,
    "max_no_speech_share": MAX_NO_SPEECH_SHARE,
    "wer_max": WER_MAX,
}
#: ``language`` values that let the model detect the language itself.
AUTO_LANGUAGES = frozenset({"", "auto"})
#: Imports the doctor proves, with the distribution each comes from.
DOCTOR_IMPORTS = (
    ("faster_whisper", "faster-whisper"),
    ("ctranslate2", "ctranslate2"),
    ("av", "av"),
)
#: The doctor's throwaway clip: one second of digital silence.
DOCTOR_RATE_HZ = 16000
DOCTOR_SECONDS_S = 1.0


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the doctor's model byte sizes."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _model(req: Request) -> Any:
    """faster-whisper small on CPU int8, loaded once per verb that needs it."""
    faster_whisper = importlib.import_module("faster_whisper")
    return faster_whisper.WhisperModel(
        str(req.model_path(MODEL_ID)), device="cpu", compute_type="int8"
    )


def _transcribe(model: Any, path: Path, language: str) -> tuple[list[dict[str, Any]], Any]:
    """The audio's segments and info: beam 5, VAD and word timestamps on."""
    segments, info = model.transcribe(
        str(path),
        language=None if language in AUTO_LANGUAGES else language,
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
    )
    return [_segment(segment) for segment in segments], info


def _segment(segment: Any) -> dict[str, Any]:
    """One faster-whisper segment as plain data for the format writers."""
    words = getattr(segment, "words", None) or []
    return {
        "start_s": float(segment.start),
        "end_s": float(segment.end),
        "text": str(segment.text),
        "avg_logprob": float(segment.avg_logprob),
        "no_speech_prob": float(segment.no_speech_prob),
        "words": [
            {
                "start_s": float(word.start),
                "end_s": float(word.end),
                "word": str(word.word),
                "probability": float(word.probability),
            }
            for word in words
        ],
    }


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    audio = Path(str(params["audio"]))
    name = str(params["name"])
    language = str(params.get("language", "auto"))
    segments, info = _transcribe(_model(req), audio, language)
    transcript = "\n".join(str(segment["text"]).strip() for segment in segments).strip()
    sidecar = formats.to_json(
        str(info.language),
        float(info.language_probability),
        float(info.duration or 0.0),
        segments,
    )
    _write(req.out_dir, name, transcript, formats.to_srt(segments), sidecar)
    return {"tool": dict(TOOL), "assets": _assets(params, segments, sidecar, audio)}


def _write(out_dir: Path, name: str, transcript: str, srt: str, sidecar: dict[str, Any]) -> None:
    """The three assets: one segment per line, the cues, and the timed sidecar."""
    text = f"{transcript}\n" if transcript else ""
    (out_dir / f"{name}.txt").write_text(text, encoding="utf-8")
    (out_dir / f"{name}.srt").write_text(srt, encoding="utf-8")
    body = json.dumps(sidecar, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (out_dir / f"{name}.json").write_text(body, encoding="utf-8")


def _assets(
    params: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    sidecar: Mapping[str, Any],
    audio: Path,
) -> list[dict[str, Any]]:
    """The transcript, the subtitles and the sidecar, each with its record data."""
    name = str(params["name"])
    properties = {
        "language": sidecar["language"],
        "language_probability": sidecar["language_probability"],
        "duration_s": sidecar["duration_s"],
        "segments": len(segments),
        "words": _word_count(segments),
    }
    shared = {
        "name": name,
        "properties": properties,
        "params": _params(params),
        "seed": None,
        "inputs": [str(audio)],
    }
    return [
        {**shared, "file": f"{name}.txt", "kind": "text", "mime": "text/plain"},
        {**shared, "file": f"{name}.srt", "kind": "text", "mime": "application/x-subrip"},
        {**shared, "file": f"{name}.json", "kind": "text", "mime": "application/json"},
    ]


def _params(params: Mapping[str, Any]) -> dict[str, Any]:
    """The piece's fields under their manifest names, reference text included."""
    resolved = {
        "audio": str(params["audio"]),
        "language": str(params.get("language", "auto")),
        "name": str(params["name"]),
    }
    expect = _expect_text(params)
    if expect is not None:
        resolved["expect-text"] = expect
    return resolved


def _expect_text(params: Mapping[str, Any]) -> str | None:
    """What was said, when the piece knows it; ``None`` when it does not."""
    value = params.get("expect-text")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _language(params: Mapping[str, Any]) -> str:
    """The piece's language, defaulted the way the manifest does."""
    return str(params.get("language") or "auto")


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    expect = _expect_text(params)
    requested = _language(params)
    return {"assets": [_verify_asset(path, expect, requested) for path in req.assets]}


def _verify_asset(path: Path, expect: str | None, requested: str) -> dict[str, Any]:
    """The transcript carries the verification; the derived files must parse."""
    if path.suffix.lower() == ".txt":
        return _verify_transcript(path, expect, requested)
    return _verify_derived(path)


def _verify_transcript(path: Path, expect: str | None, requested: str) -> dict[str, Any]:
    """Judge the transcript: not empty, confident, mostly speech, WER under max."""
    try:
        transcript = path.read_text(encoding="utf-8").strip()
        sidecar = _sidecar(path)
    except (OSError, ValueError) as exc:
        return _verdict(path.name, False, {"error": str(exc)})
    metrics = _metrics(transcript, sidecar, expect, requested)
    return {
        "file": path.name,
        "passed": _passed(metrics, bool(transcript)),
        "metrics": metrics,
        "thresholds": dict(THRESHOLDS),
        "verifier": VERIFIER,
    }


def _verdict(file: str, passed: bool, metrics: dict[str, Any]) -> dict[str, Any]:
    """One verdict, for a transcript whose sidecar could not be read."""
    return {
        "file": file,
        "passed": passed,
        "metrics": metrics,
        "thresholds": dict(THRESHOLDS),
        "verifier": VERIFIER,
    }


def _verify_derived(path: Path) -> dict[str, Any]:
    """The subtitles and the sidecar pass when they parse to at least one unit."""
    try:
        units = _units(path)
    except (OSError, ValueError) as exc:
        metrics: dict[str, Any] = {"error": str(exc)}
        return _derived_verdict(path.name, False, metrics)
    return _derived_verdict(path.name, bool(units), {"units": len(units)})


def _derived_verdict(file: str, passed: bool, metrics: dict[str, Any]) -> dict[str, Any]:
    """One verdict for a derived asset: nothing to measure beyond its shape."""
    return {
        "file": file,
        "passed": passed,
        "metrics": metrics,
        "thresholds": {},
        "verifier": VERIFIER,
    }


def _units(path: Path) -> list[Any]:
    """The cues of an SRT file, or the segments of the JSON sidecar."""
    if path.suffix.lower() == ".json":
        segments = _sidecar_data(path).get("segments")
        return segments if isinstance(segments, list) else []
    blocks = path.read_text(encoding="utf-8").split("\n\n")
    return [block for block in blocks if "-->" in block]


def _sidecar(path: Path) -> dict[str, Any]:
    """The sidecar beside a transcript: ``<name>.json`` next to ``<name>.txt``."""
    return _sidecar_data(path.with_name(f"{path.stem}.json"))


def _sidecar_data(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name}: the sidecar is not a JSON object")
    return loaded


def _segments(sidecar: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The sidecar's segments, ignoring anything that is not a JSON object."""
    raw = sidecar.get("segments")
    if not isinstance(raw, list):
        return []
    return [segment for segment in raw if isinstance(segment, dict)]


def _metrics(
    transcript: str, sidecar: Mapping[str, Any], expect: str | None, requested: str
) -> dict[str, Any]:
    """What verify reports: the model's confidence, the speech share, the WER."""
    segments = _segments(sidecar)
    language = str(sidecar.get("language") or "")
    duration = float(sidecar.get("duration_s") or 0.0)
    words = _word_count(segments)
    minutes = duration / 60.0 if duration else 0.0
    wer = None
    if expect is not None:
        normalise = _normalisation_language(requested, language)
        wer = _wer(transcript, expect, normalise)
    return {
        "language": language,
        "language_probability": round(float(sidecar.get("language_probability") or 0.0), 4),
        "avg_logprob": _avg_logprob(segments),
        "no_speech_share": _no_speech_share(segments),
        "words": words,
        "words_per_minute": round(words / minutes) if minutes else 0,
        "wer": wer,
    }


def _normalisation_language(requested: str, detected: str) -> str:
    """The language whose rules normalise the reference: the piece's when named.

    Kokoro normalises the reference with the piece's language; here ``auto``
    means the piece names none, so the detected one is the only evidence. A
    named language wins even when the model heard another: the reference text
    is known to be in the caller's language.
    """
    return detected if requested in AUTO_LANGUAGES else requested


def _avg_logprob(segments: Sequence[Mapping[str, Any]]) -> float | None:
    """The mean of the segments' ``avg_logprob``, or ``None`` with no segments."""
    values = [float(segment.get("avg_logprob") or 0.0) for segment in segments]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _no_speech_share(segments: Sequence[Mapping[str, Any]]) -> float:
    """The share of segments the model thought were not speech."""
    if not segments:
        return 0.0
    quiet = sum(
        1 for segment in segments if float(segment.get("no_speech_prob") or 0.0) > NO_SPEECH_PROB
    )
    return round(quiet / len(segments), 4)


def _word_count(segments: Sequence[Mapping[str, Any]]) -> int:
    """Timed words across every segment."""
    return sum(len(segment.get("words") or []) for segment in segments)


def _wer(transcript: str, expect: str, language: str) -> float:
    """Word error rate against the reference, normalised as kokoro does."""
    reference = textnorm.words(expect, language)
    heard = textnorm.words(transcript, language)
    return round(textnorm.wer(reference, heard), 4)


def _passed(metrics: Mapping[str, Any], has_text: bool) -> bool:
    """The manifest's four conditions, in order; the first failure decides."""
    if not has_text:
        return False
    logprob = metrics["avg_logprob"]
    if logprob is None or float(logprob) < MIN_AVG_LOGPROB:
        return False
    if float(metrics["no_speech_share"]) > MAX_NO_SPEECH_SHARE:
        return False
    wer = metrics["wer"]
    return wer is None or float(wer) <= WER_MAX


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    expect = _expect_text(params)
    requested = _language(params)
    entries = []
    for path in req.assets:
        if path.suffix.lower() != ".txt":
            raise ValueError(f"{path.name}: preview the transcript (.txt), not this file")
        preview_name = f"{path.name}.preview.json"
        data = _preview_data(path, expect, requested)
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _preview_data(path: Path, expect: str | None, requested: str) -> dict[str, Any]:
    """The generic preview: the properties and metrics, never the timed segments."""
    transcript = path.read_text(encoding="utf-8").strip()
    sidecar = _sidecar(path)
    metrics = _metrics(transcript, sidecar, expect, requested)
    fields = {
        "language": metrics["language"],
        "language_probability": metrics["language_probability"],
        "duration_s": round(float(sidecar.get("duration_s") or 0.0), 3),
        "segments": len(_segments(sidecar)),
        "words": metrics["words"],
        "avg_logprob": metrics["avg_logprob"],
        "no_speech_share": metrics["no_speech_share"],
        "words_per_minute": metrics["words_per_minute"],
        "wer": metrics["wer"],
    }
    return {"preview": 1, "kind": "text", "summary": _summary(fields), "fields": fields}


def _summary(fields: Mapping[str, Any]) -> str:
    """One line for an agent: duration, language and confidence, words, WER."""
    parts = [
        f"{float(fields['duration_s']):.1f} s",
        f"{fields['language']} ({float(fields['language_probability']):.2f})",
        f"{fields['words']} words",
    ]
    if fields["wer"] is not None:
        parts.append(f"WER {float(fields['wer']) * 100:.0f} %")
    return " · ".join(parts)


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_imports(), _doctor_models(req)]
    if req.depth == "full":
        checks.append(_doctor_transcribe(req))
    return {"checks": checks}


def _doctor_verdict(name: str, ok: bool, detail: str) -> dict[str, Any]:
    """One doctor check; every failure names the pull that fixes the env."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else "facet pull whisper"}


def _doctor_imports() -> dict[str, Any]:
    """The three imports the runner leans on, each with its version."""
    found: list[str] = []
    broken: list[str] = []
    for module_name, distribution in DOCTOR_IMPORTS:
        try:
            module = importlib.import_module(module_name)
            found.append(f"{module_name} {getattr(module, '__version__', _version(distribution))}")
        except Exception as exc:  # catch-all: one broken import must not hide the rest
            broken.append(f"{module_name}: {exc}")
    if broken:
        return _doctor_verdict("imports", False, "; ".join(broken))
    return _doctor_verdict("imports", True, ", ".join(found))


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _doctor_models(req: Request) -> dict[str, Any]:
    """The model directory exists with the byte size the manifest claims."""
    expected = {str(model["id"]): int(model["bytes"]) for model in _manifest().get("models", [])}
    problems: list[str] = []
    found: list[str] = []
    for model_id, want in sorted(expected.items()):
        try:
            path = req.model_path(model_id)
        except KeyError:
            problems.append(f"{model_id}: not in this request")
            continue
        actual = _tree_bytes(path)
        if actual is None:
            problems.append(f"{model_id}: missing at {path}")
        elif actual != want:
            problems.append(f"{model_id}: {actual} bytes, manifest says {want}")
        else:
            found.append(f"{model_id} {actual} B")
    if problems:
        return _doctor_verdict("models", False, "; ".join(problems))
    return _doctor_verdict("models", True, ", ".join(found))


def _tree_bytes(path: Path) -> int | None:
    """A file's size, a directory's summed sizes, or ``None`` when absent."""
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    return None


def _doctor_transcribe(req: Request) -> dict[str, Any]:
    """Full depth: the model loads on CPU int8 and hears a second of silence."""
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "doctor.wav"
            _write_silence(path)
            segments, _info = _transcribe(_model(req), path, "auto")
    except Exception as exc:  # catch-all: the check reports, the verb survives
        elapsed = time.monotonic() - started
        return _doctor_verdict(
            "transcribe", False, f"transcription failed after {elapsed:.1f} s: {exc}"
        )
    elapsed = time.monotonic() - started
    detail = (
        f"{DOCTOR_SECONDS_S:.0f} s of silence at {DOCTOR_RATE_HZ} Hz: "
        f"{len(segments)} segment(s) in {elapsed:.1f} s"
    )
    return _doctor_verdict("transcribe", True, detail)


def _write_silence(path: Path) -> None:
    """A one-second 16 kHz mono WAV of digital silence."""
    soundfile = importlib.import_module("soundfile")
    numpy = importlib.import_module("numpy")
    samples = numpy.zeros(int(DOCTOR_SECONDS_S * DOCTOR_RATE_HZ), dtype="float32")
    soundfile.write(str(path), samples, DOCTOR_RATE_HZ, subtype="PCM_16")


runner.main()
