"""The kokoro package runner: CPU narration checked by transcription.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` synthesises the clips with Kokoro-82M ONNX
and normalises their loudness, ``verify`` transcribes each clip with
faster-whisper ``small`` on CPU and measures the word error rate,
``preview`` writes the audio preview file, ``doctor`` checks the tool at
``quick`` and ``full`` depth.

Heavy imports go through ``importlib`` inside the functions: the pure-text
side (``textnorm``) is stdlib-only, so a broken environment still lets the
doctor report *which* import fails instead of dying on a top-level import.
"""

from __future__ import annotations

import ctypes
import importlib
import importlib.metadata
import json
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import espeakpath
import textnorm
from facet_runner_sdk import Request, Runner

runner = Runner()

#: The word error rate a clip must stay at or under (manifest threshold).
WER_MAX = 0.05
#: A clip whose peak sits at or below this is silence, not narration.
SILENT_PEAK_DBFS = -40.0
#: What verify measured with, named for the record.
VERIFIER = "faster-whisper-small@536b0662"
#: Kokoro is deterministic, and its versions are pinned by the manifest.
TOOL = {"name": "kokoro-onnx", "version": "0.6.1"}
#: Kokoro always renders at this rate; the manifest and spec pin it.
SAMPLE_RATE_HZ = 24000
#: The letter a voice must start with per language (e → es, a → en-us, b → en-gb).
VOICE_PREFIX = {"es": "e", "en-us": "a", "en-gb": "b"}
#: What faster-whisper understands for each narration language.
WHISPER_LANGUAGE = {"es": "es", "en-us": "en", "en-gb": "en"}
#: Model ids the request carries (manifest ids).
ONNX_MODEL = "kokoro-82m-v1.0-onnx"
VOICES_MODEL = "kokoro-voices-v1.0"
WHISPER_MODEL = "faster-whisper-small"
#: Imports the doctor proves, with the distribution each comes from.
DOCTOR_IMPORTS = (
    ("kokoro_onnx", "kokoro-onnx"),
    ("faster_whisper", "faster-whisper"),
    ("pyloudnorm", "pyloudnorm"),
    ("soundfile", "soundfile"),
    ("av", "av"),
)


def _audio() -> Any:
    """The package's audio helpers, imported only when a verb needs them."""
    return importlib.import_module("audiopreview")


def _tool() -> dict[str, str]:
    return dict(TOOL)


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the doctor's model byte sizes."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _clips(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Every clip with the piece defaults resolved into its own fields."""
    language = str(params.get("language", "es"))
    voice = str(params.get("voice", "ef_dora"))
    speed = float(params.get("speed", 1.0))
    target_lufs = float(params.get("target-lufs", -16.0))
    clips: list[dict[str, Any]] = []
    for raw in params.get("clip", []):
        clip = {
            "name": str(raw["name"]),
            "text": str(raw["text"]),
            "voice": str(raw.get("voice") or voice),
            "speed": float(raw.get("speed") or speed),
            "language": language,
            "target_lufs": target_lufs,
        }
        clips.append(clip)
    return clips


def _params(clip: dict[str, Any]) -> dict[str, Any]:
    """The clip's effective piece fields, under their manifest names.

    ``target-lufs`` is hyphenated in the manifest: the core's field names
    never carry an underscore (``manifest._NAME_RE``), so the piece field
    cannot be spelled ``target_lufs``.
    """
    return {
        "name": clip["name"],
        "text": clip["text"],
        "voice": clip["voice"],
        "speed": clip["speed"],
        "language": clip["language"],
        "target-lufs": clip["target_lufs"],
    }


def _require_matching_voice(voice: str, language: str) -> None:
    """Reject a voice whose first letter names a different language."""
    expected = VOICE_PREFIX.get(language)
    if expected is None:
        known = ", ".join(sorted(VOICE_PREFIX))
        raise ValueError(f"unknown language {language!r} (known: {known})")
    if not voice.startswith(expected):
        raise ValueError(
            f"voice {voice!r} does not match language {language!r}: "
            f"{language} narrates with voices starting with {expected!r} "
            "(e → es, a → en-us, b → en-gb)"
        )


def _whisper_language(language: str) -> str:
    return WHISPER_LANGUAGE.get(language, "en")


def _espeak_data() -> str:
    """espeakng-loader's data directory, through a short copy when its path is long."""
    espeakng_loader = importlib.import_module("espeakng_loader")
    return espeakpath.short_data_path(
        str(espeakng_loader.get_data_path()), Path(tempfile.gettempdir())
    )


def _kokoro(req: Request) -> Any:
    """Kokoro loaded once per run; the two files are the manifest models."""
    kokoro_onnx = importlib.import_module("kokoro_onnx")
    config = importlib.import_module("kokoro_onnx.config")
    return kokoro_onnx.Kokoro(
        str(req.model_path(ONNX_MODEL)),
        str(req.model_path(VOICES_MODEL)),
        espeak_config=config.EspeakConfig(data_path=_espeak_data()),
    )


def _whisper(req: Request) -> Any:
    """faster-whisper small on CPU int8, loaded once per verify/preview."""
    faster_whisper = importlib.import_module("faster_whisper")
    return faster_whisper.WhisperModel(
        str(req.model_path(WHISPER_MODEL)), device="cpu", compute_type="int8"
    )


def _transcribe(model: Any, path: Path, language: str) -> str:
    """The clip's transcript: beam 5 with VAD, one space-joined string."""
    segments, _info = model.transcribe(
        str(path),
        language=_whisper_language(language),
        beam_size=5,
        vad_filter=True,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    clips = _clips(dict(req.inputs))
    for clip in clips:
        _require_matching_voice(clip["voice"], clip["language"])
    kokoro = _kokoro(req)
    assets = [_speak(kokoro, clip, req.out_dir) for clip in clips]
    return {"tool": _tool(), "assets": assets}


def _speak(kokoro: Any, clip: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    """One clip: synthesise, normalise, write PCM 16-bit, describe it."""
    audio = _audio()
    samples, rate = kokoro.create(clip["text"], clip["voice"], clip["speed"], clip["language"])
    samples = audio.normalize(samples, int(rate), clip["target_lufs"])
    path = out_dir / f"{clip['name']}.wav"
    audio.write_wav(path, samples, int(rate))
    return {
        "file": path.name,
        "name": clip["name"],
        "kind": "audio",
        "mime": "audio/wav",
        "properties": {
            "duration_s": round(audio.duration_s(samples, int(rate)), 3),
            "sample_rate_hz": int(rate),
            "lufs": round(audio.integrated_lufs(samples, int(rate)), 2),
            "peak_dbfs": round(audio.peak_dbfs(samples), 2),
            "voice": clip["voice"],
            "language": clip["language"],
        },
        "params": _params(clip),
        "seed": None,
        "inputs": [],
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    clips = {clip["name"]: clip for clip in _clips(params)}
    model = _whisper(req)
    audio = _audio()
    entries = []
    for path in req.assets:
        clip = _clip_for(clips, path)
        entries.append(_verify_clip(model, audio, path, clip))
    return {"assets": entries}


def _clip_for(clips: dict[str, dict[str, Any]], path: Path) -> dict[str, Any]:
    """The clip that produced this asset; the stem is the clip's name."""
    clip = clips.get(path.stem)
    if clip is None:
        raise ValueError(f"{path.name}: no clip named {path.stem!r} in the piece")
    return clip


def _verify_clip(model: Any, audio: Any, path: Path, clip: dict[str, Any]) -> dict[str, Any]:
    """Transcribe one clip, score it against its text, judge it."""
    samples, rate = audio.read_wav(path)
    transcript = _transcribe(model, path, clip["language"])
    reference = textnorm.words(clip["text"], clip["language"])
    heard = textnorm.words(transcript, clip["language"])
    score = textnorm.wer(reference, heard)
    duration = audio.duration_s(samples, rate)
    peak = audio.peak_dbfs(samples)
    lufs = audio.integrated_lufs(samples, rate)
    minutes = duration / 60.0 if duration else 0.0
    passed = score <= WER_MAX and peak > SILENT_PEAK_DBFS
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {
            "wer": round(score, 4),
            "words": len(reference),
            "words_per_minute": round(len(reference) / minutes) if minutes else 0,
            "lufs": round(lufs, 2),
            "peak_dbfs": round(peak, 2),
            "transcript": transcript,
        },
        "thresholds": {"wer_max": WER_MAX},
        "verifier": VERIFIER,
    }


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    params = dict(req.inputs)
    clips = {clip["name"]: clip for clip in _clips(params)}
    model = _whisper(req)
    entries = []
    for path in req.assets:
        clip = _clip_for(clips, path)
        preview_name = f"{path.name}.preview.json"
        data = _preview_data(model, path, clip)
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _preview_data(model: Any, path: Path, clip: dict[str, Any]) -> dict[str, Any]:
    """The audio preview file: signal, loudness, and the speech judgement."""
    audio = _audio()
    samples, rate = audio.read_wav(path)
    language = clip["language"]
    text = clip["text"]
    voice = clip["voice"]
    transcript = _transcribe(model, path, language)
    reference = textnorm.words(text, language)
    heard = textnorm.words(transcript, language)
    score = textnorm.wer(reference, heard)
    lufs = audio.integrated_lufs(samples, rate)
    duration = audio.duration_s(samples, rate)
    return {
        "preview": 1,
        "kind": "audio",
        "summary": f"{duration:.1f} s · {lufs:.1f} LUFS · WER {score * 100:.0f} % · {voice}",
        "duration_s": round(duration, 3),
        "sample_rate_hz": int(rate),
        "channels": 1 if samples.ndim == 1 else int(samples.shape[1]),
        "waveform": audio.waveform(samples),
        "loudness": {
            "integrated_lufs": round(lufs, 2),
            "peak_dbfs": round(audio.peak_dbfs(samples), 2),
            "target_lufs": float(clip["target_lufs"]),
            "momentary": {
                "step_s": 0.1,
                "window_s": 0.4,
                "lufs": audio.momentary(samples, int(rate)),
            },
        },
        "silences": audio.silences(samples, int(rate)),
        "clipped_samples": audio.clipped_samples(samples),
        "speech": {
            "text": text,
            "transcript": transcript,
            "wer": round(score, 4),
            "alignment": textnorm.align(reference, heard),
        },
    }


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_imports(), _doctor_espeak(), _doctor_models(req)]
    if req.depth == "full":
        checks.extend(_doctor_full(req))
    return {"checks": checks}


def _verdict(name: str, ok: bool, detail: str) -> dict[str, Any]:
    """One doctor check; every failure names the pull that fixes the env."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else "facet pull kokoro"}


def _doctor_imports() -> dict[str, Any]:
    """The five imports the runner leans on, each with its version."""
    found: list[str] = []
    broken: list[str] = []
    for module_name, distribution in DOCTOR_IMPORTS:
        try:
            module = importlib.import_module(module_name)
            found.append(f"{module_name} {getattr(module, '__version__', _version(distribution))}")
        except Exception as exc:  # catch-all: one broken import must not hide the rest
            broken.append(f"{module_name}: {exc}")
    if broken:
        return _verdict("imports", False, "; ".join(broken))
    return _verdict("imports", True, ", ".join(found))


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _doctor_espeak() -> dict[str, Any]:
    """The espeak-ng library bundled by espeakng-loader loads and finds its data."""
    try:
        espeakng_loader = importlib.import_module("espeakng_loader")
        library = Path(espeakng_loader.get_library_path())
        ctypes.CDLL(str(library))
        data = _espeak_data()
    except Exception as exc:  # catch-all: report whatever went wrong
        return _verdict("espeak", False, f"the bundled espeak-ng does not load: {exc}")
    if not (Path(data) / "phontab").is_file():
        return _verdict("espeak", False, f"espeak-ng data has no phontab at {data}")
    return _verdict("espeak", True, f"espeak-ng loads from {library.name}, data at {data}")


def _doctor_models(req: Request) -> dict[str, Any]:
    """The three model files exist with the byte sizes the manifest claims."""
    expected = {str(m["id"]): int(m["bytes"]) for m in _manifest().get("models", [])}
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
        return _verdict("models", False, "; ".join(problems))
    return _verdict("models", True, ", ".join(found))


def _tree_bytes(path: Path) -> int | None:
    """A file's size, a directory's summed sizes, or ``None`` when absent."""
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    return None


def _doctor_full(req: Request) -> list[dict[str, Any]]:
    """Full depth: synthesise one word, then let whisper hear it, both timed."""
    started = time.monotonic()
    try:
        kokoro = _kokoro(req)
        samples, rate = kokoro.create("facet", "ef_dora", 1.0, "es")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "doctor.wav"
            _audio().write_wav(path, samples, int(rate))
            size = path.stat().st_size
            elapsed = time.monotonic() - started
            synth = _verdict(
                "synth", size > 0 and rate == SAMPLE_RATE_HZ, _synth_detail(size, rate, elapsed)
            )
            if not synth["ok"]:
                return [synth, _verdict("transcribe", False, "no clip from the synth check")]
            heard, heard_elapsed = _timed_transcribe(req, path)
    except Exception as exc:  # catch-all: the check reports, the verb survives
        elapsed = time.monotonic() - started
        synth = _verdict("synth", False, f"synthesis failed after {elapsed:.1f} s: {exc}")
        return [synth, _verdict("transcribe", False, "no clip from the synth check")]
    transcribe = _verdict(
        "transcribe",
        bool(heard),
        f"whisper small heard {heard!r} in {heard_elapsed:.1f} s"
        if heard
        else f"whisper small returned no text in {heard_elapsed:.1f} s",
    )
    return [synth, transcribe]


def _synth_detail(size: int, rate: int, elapsed: float) -> str:
    detail = f"'facet' → {size} B WAV at {rate} Hz in {elapsed:.1f} s"
    if size > 0 and rate == SAMPLE_RATE_HZ:
        return detail
    return f"{detail} (expected a non-empty {SAMPLE_RATE_HZ} Hz WAV)"


def _timed_transcribe(req: Request, path: Path) -> tuple[str, float]:
    """Transcribe the doctor's own clip; returns the text and the seconds."""
    started = time.monotonic()
    heard = _transcribe(_whisper(req), path, "es")
    return heard, time.monotonic() - started


runner.main()
