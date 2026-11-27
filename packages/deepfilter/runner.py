"""The deepfilter package runner: neural voice denoising with DeepFilterNet3.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` decodes the input to a 48 kHz mono WAV with the
bundled imageio-ffmpeg binary, executes the pinned ``deep-filter`` static
binary (DeepFilterNet3, no PyTorch) on it, and moves the enhanced WAV it
writes back as one ``audio`` asset; ``verify`` re-measures the output against
the source; ``preview`` writes the audio preview file; ``doctor`` checks the
binary and the imports at ``quick`` depth and enhances a synthetic noisy clip
at ``full`` depth.

The ``deep-filter`` CLI does not speak the runner protocol — its argv is
``deep-filter [options] -o <dir> <wav>``, never ``run --input/--result`` — so
the package is a python-env subprocess client, not an ``[engine.binary]``
package. Heavy imports go through ``importlib`` inside the functions, so a
broken environment still lets the doctor report *which* import fails instead
of dying on a top-level import.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from facet_lib import audiopreview
from facet_runner_sdk import Request, Runner

runner = Runner()

#: The manifest's model id and the tool version it pins, named for the record.
MODEL_ID = "deep-filter-0.5.6-linux-x86_64"
TOOL = {"name": "DeepFilterNet3", "version": "0.5.6"}
VERIFIER = "deep-filter-0.5.6"
#: DeepFilterNet3 always writes 48 kHz; the decode matches it.
RATE_HZ = 48000
#: auto channel: how far the 2-channel L/R RMS levels must differ to pick a side.
SIDE_ISOLATION_DB = 18.0
#: The channel count the auto detector treats as stereo.
STEREO_CHANNELS = 2
#: verify: the output duration must track the source within this, in seconds.
DURATION_TOL_S = 0.15
#: verify: the manifest's peak ceiling, in dBFS.
PEAK_CEILING_DBFS = 0.0
#: verify: an output at or below this LUFS counts as silent (mirrors the
#: audiopreview momentary floor); only a failure when the source has signal.
SILENCE_LUFS = -70.0
#: deep-filter takes about a second per clip; the probe is only a platform check.
RUN_TIMEOUT_S = 120
PROBE_TIMEOUT_S = 15
#: Every ffmpeg call: its own process group, no stdin, banners off, overwrite.
FFMPEG_FLAGS = ("-nostdin", "-hide_banner", "-y")
#: The stderr tail a failed ffmpeg call reports as the runner error.
STDERR_TAIL_CHARS = 2000
#: The doctor's throwaway roundtrip: one second of noisy 440 Hz sine at 48 kHz.
DOCTOR_SINE_HZ = 440.0
DOCTOR_SECONDS = 1.0
DOCTOR_NOISE_AMPLITUDE = 0.08
#: Imports the doctor proves, with the distribution each comes from.
DOCTOR_IMPORTS = (
    ("numpy", "numpy"),
    ("pyloudnorm", "pyloudnorm"),
    ("soundfile", "soundfile"),
)


def _exe() -> str:
    """The bundled static FFmpeg binary (imageio-ffmpeg ships it in its wheel)."""
    imageio_ffmpeg = importlib.import_module("imageio_ffmpeg")
    return str(imageio_ffmpeg.get_ffmpeg_exe())


def _ffmpeg(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """One ffmpeg call in its own process group; a non-zero exit is the runner error."""
    done = subprocess.run(
        [_exe(), *FFMPEG_FLAGS, *args],
        capture_output=True,
        text=True,
        start_new_session=True,
        check=False,
    )
    if done.returncode != 0:
        tail = (done.stderr or "")[-STDERR_TAIL_CHARS:].strip()
        raise RuntimeError(f"ffmpeg exited {done.returncode}: {tail}")
    return done


def _binary(req: Request) -> Path:
    """The pinned deep-filter binary, executable; the pull lays it down read-only."""
    binary = req.model_path(MODEL_ID)
    if not binary.is_file():
        raise RuntimeError(f"{binary}: the deep-filter binary is missing; facet pull deepfilter")
    if not _executable(binary):
        binary.chmod(0o755)
    return binary


def _executable(path: Path) -> bool:
    """Whether the current process can execute this file."""
    return os.access(path, os.X_OK)


def _rms_db(channel: Any) -> float:
    """One channel's RMS in dBFS, floored so digital silence stays finite."""
    numpy = importlib.import_module("numpy")
    rms = float(numpy.sqrt(numpy.mean(numpy.square(channel))))
    return 20.0 * math.log10(rms + 1e-12)


def _detect_channel(source: Path, tmp: Path) -> str:
    """``left``/``right`` when a mono mic landed on one side only, else ``mix``."""
    tmp.mkdir(parents=True, exist_ok=True)
    decoded = tmp / "detect.measure.wav"
    _ffmpeg(["-i", str(source), "-acodec", "pcm_s16le", str(decoded)])
    samples, _rate = audiopreview.read_wav(decoded)
    count = audiopreview.channels(samples)
    if count != STEREO_CHANNELS:
        return "mix"
    left, right = _rms_db(samples[:, 0]), _rms_db(samples[:, 1])
    if left - right >= SIDE_ISOLATION_DB:
        return "left"
    if right - left >= SIDE_ISOLATION_DB:
        return "right"
    return "mix"


def _channel_filter(resolved: str) -> list[str]:
    """The ffmpeg audio filter behind a resolved channel choice."""
    if resolved == "left":
        return ["-af", "pan=mono|c0=c0"]
    if resolved == "right":
        return ["-af", "pan=mono|c0=c1"]
    return ["-af", "aformat=channel_layouts=mono"]


def _decode(source: Path, out: Path, channel: str, tmp: Path) -> str:
    """Decode the source to a 48 kHz mono WAV, resolving ``auto`` by measurement."""
    resolved = _detect_channel(source, tmp) if channel == "auto" else channel
    _ffmpeg(
        [
            "-i",
            str(source),
            *_channel_filter(resolved),
            "-ar",
            str(RATE_HZ),
            "-ac",
            "1",
            "-acodec",
            "pcm_s16le",
            str(out),
        ]
    )
    return resolved


def command(
    binary: Path, atten_lim_db: float, post_filter: bool, out_dir: Path, wav: Path
) -> list[str]:
    """The argv deep-filter takes: denoise flag, attenuation, post-filter, out dir, wav."""
    argv = [str(binary), "-D", "-a", str(float(atten_lim_db))]
    if post_filter:
        argv.append("--pf")
    argv.extend(["-o", str(out_dir), str(wav)])
    return argv


def _execute(argv: Sequence[str], cwd: Path) -> None:
    """Run deep-filter; a non-zero exit fails the run with the tool's own tail."""
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
        raise RuntimeError(f"deep-filter could not run: {exc}") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-3:]
        raise RuntimeError(f"deep-filter exited {done.returncode}: {' / '.join(tail)}")


def _enhanced_wav(out_dir: Path, in_wav: Path) -> Path:
    """The enhanced WAV deep-filter wrote: beside the input name, else the sole wav."""
    first = out_dir / in_wav.name
    if first.is_file():
        return first
    wavs = sorted(out_dir.glob("*.wav"))
    if len(wavs) == 1:
        return wavs[0]
    raise RuntimeError(f"{out_dir}: deep-filter wrote no {in_wav.name} and no single *.wav to take")


def _measure_wav(path: Path) -> dict[str, Any]:
    """The asset properties straight from the enhanced 48 kHz WAV."""
    samples, rate = audiopreview.read_wav(path)
    return {
        "duration_s": round(audiopreview.duration_s(samples, rate), 3),
        "sample_rate_hz": rate,
        "channels": audiopreview.channels(samples),
        "lufs": round(audiopreview.integrated_lufs(samples, rate), 2),
        "peak_dbfs": round(audiopreview.peak_dbfs(samples), 2),
    }


def _measure_source(source: Path, tmp: Path) -> dict[str, Any]:
    """The source decoded to 48 kHz mono, measured the same way as the output."""
    tmp.mkdir(parents=True, exist_ok=True)
    decoded = tmp / "source.measure.wav"
    _ffmpeg(
        [
            "-i",
            str(source),
            "-af",
            "aformat=channel_layouts=mono",
            "-ar",
            str(RATE_HZ),
            "-ac",
            "1",
            "-acodec",
            "pcm_s16le",
            str(decoded),
        ]
    )
    return _measure_wav(decoded)


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    """Denoise the input clip and return the one enhanced ``audio`` asset."""
    params = dict(req.inputs)
    source = Path(str(params["audio"]))
    name = str(params["name"])
    channel = str(params.get("channel", "auto"))
    atten = float(params.get("atten-lim-db", 100.0))
    post_filter = bool(params.get("post-filter", True))
    binary = _binary(req)
    out = Path(str(req.out_dir)) / f"{name}.wav"
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        in_wav = tmp / f"{name}.in.wav"
        resolved = _decode(source, in_wav, channel, tmp / "detect")
        enhanced_dir = tmp / "enhanced"
        enhanced_dir.mkdir()
        _execute(command(binary, atten, post_filter, enhanced_dir, in_wav), tmp)
        # move, not rename: /tmp may be another filesystem than the out dir.
        shutil.move(str(_enhanced_wav(enhanced_dir, in_wav)), str(out))
        properties = _measure_wav(out)
    asset = _asset(name, out.name, properties, params, resolved, source)
    return {"tool": dict(TOOL), "assets": [asset]}


def _asset(
    name: str,
    file: str,
    properties: Mapping[str, Any],
    params: Mapping[str, Any],
    channel: str,
    source: Path,
) -> dict[str, Any]:
    """The one ``audio`` asset: the measured properties and the resolved piece fields."""
    return {
        "file": file,
        "name": name,
        "kind": "audio",
        "mime": "audio/wav",
        "properties": dict(properties),
        "params": {
            "audio": str(params["audio"]),
            "name": str(params["name"]),
            "channel": channel,
            "atten-lim-db": float(params.get("atten-lim-db", 100.0)),
            "post-filter": bool(params.get("post-filter", True)),
        },
        "seed": None,
        "inputs": [str(source)],
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    """Re-measure every asset against the source clip it was denoised from."""
    params = dict(req.inputs)
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        source = _measure_source(Path(str(params["audio"])), tmp / "src")
        entries = [
            _verdict(path, params, source, tmp / f"asset{index}")
            for index, path in enumerate(req.assets)
        ]
    return {"assets": entries}


def _verdict(
    path: Path, params: Mapping[str, Any], source: Mapping[str, Any], tmp: Path
) -> dict[str, Any]:
    """Judge one enhanced WAV: 48 kHz, duration kept, peak at or under 0, finite loudness."""
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        props = _measure_wav(path)
    except (OSError, ValueError) as exc:
        return _entry(path.name, False, {"error": f"{path.name}: cannot parse: {exc}"})
    if int(props["sample_rate_hz"]) != RATE_HZ:
        rate = props["sample_rate_hz"]
        return _entry(path.name, False, {**props, "error": f"rate is {rate}, not {RATE_HZ}"})
    if not props["duration_s"]:
        return _entry(path.name, False, {**props, "error": "the enhanced WAV is empty"})
    error = round(abs(float(props["duration_s"]) - float(source["duration_s"])), 3)
    lufs = float(props["lufs"])
    source_lufs = float(source["lufs"])
    problems: list[str] = []
    if error > DURATION_TOL_S:
        problems.append(f"duration drifted {error} s from the source")
    if float(props["peak_dbfs"]) > PEAK_CEILING_DBFS:
        problems.append(f"peak {props['peak_dbfs']} dBFS is above {PEAK_CEILING_DBFS}")
    source_has_signal = math.isfinite(source_lufs) and source_lufs > SILENCE_LUFS
    if not math.isfinite(lufs) or (source_has_signal and lufs <= SILENCE_LUFS):
        problems.append("integrated loudness is not finite: the output is silent")
    metrics = {**props, "duration_error_s": error}
    if problems:
        return _entry(path.name, False, {**metrics, "error": "; ".join(problems)})
    return _entry(path.name, True, metrics)


def _entry(file: str, passed: bool, metrics: Mapping[str, Any]) -> dict[str, Any]:
    """One verify entry: the measured metrics, the thresholds, and what measured them."""
    return {
        "file": file,
        "passed": passed,
        "metrics": dict(metrics),
        "thresholds": {"duration_tol_s": DURATION_TOL_S, "peak_ceiling_dbfs": PEAK_CEILING_DBFS},
        "verifier": VERIFIER,
    }


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    """Write ``<asset>.preview.json`` for every asset, decoded through the bundled ffmpeg."""
    params = dict(req.inputs)
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        entries = []
        for index, path in enumerate(req.assets):
            preview_name = f"{path.name}.preview.json"
            data = _preview_data(params, path, tmp / f"asset{index}")
            (Path(str(req.out_dir)) / preview_name).write_text(
                json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
            )
            entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _summary(name: object, duration: float, lufs: float, peak: float) -> str:
    """One line like ``enhance · 2.0 s · -19.3 LUFS · peak -6.0 dBFS · take``."""
    return f"enhance · {duration:.1f} s · {lufs:.1f} LUFS · peak {peak:.1f} dBFS · {name}"[:160]


def _preview_data(params: Mapping[str, Any], path: Path, tmp: Path) -> dict[str, Any]:
    """The audio preview file: waveform, loudness and silences, no speech section."""
    tmp.mkdir(parents=True, exist_ok=True)
    decoded = tmp / "preview.measure.wav"
    _ffmpeg(["-i", str(path), "-acodec", "pcm_s16le", str(decoded)])
    samples, rate = audiopreview.read_wav(decoded)
    lufs = audiopreview.integrated_lufs(samples, rate)
    peak = audiopreview.peak_dbfs(samples)
    duration = audiopreview.duration_s(samples, rate)
    name = params.get("name", path.stem)
    return {
        "preview": 1,
        "kind": "audio",
        "summary": _summary(name, duration, lufs, peak),
        "duration_s": round(duration, 3),
        "sample_rate_hz": rate,
        "channels": audiopreview.channels(samples),
        "waveform": audiopreview.waveform(samples),
        "loudness": {
            "integrated_lufs": round(lufs, 2),
            "peak_dbfs": round(peak, 2),
            "target_lufs": None,
            "momentary": {
                "step_s": 0.1,
                "window_s": 0.4,
                "lufs": audiopreview.momentary(samples, rate),
            },
        },
        "silences": audiopreview.silences(samples, rate),
        "clipped_samples": audiopreview.clipped_samples(samples),
    }


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    """Quick: the binary, its --help, the imports. Full: enhance a synthetic noisy clip."""
    checks = [_doctor_binary(req), _doctor_imports()]
    if req.depth == "full":
        checks.append(_doctor_roundtrip(req))
    return {"checks": checks}


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    """One doctor check; every failure names the pull that fixes the env."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else "facet pull deepfilter"}


def _doctor_binary(req: Request) -> dict[str, Any]:
    """The pinned binary exists, is executable, and answers ``--help`` on this machine."""
    try:
        binary = req.model_path(MODEL_ID)
    except KeyError:
        return _check("binary", False, f"{MODEL_ID}: not in this request")
    if not binary.is_file():
        return _check("binary", False, f"{binary}: missing")
    try:
        binary = _binary(req)
    except (OSError, RuntimeError) as exc:
        return _check("binary", False, str(exc))
    problem = _probe(binary)
    if problem is not None:
        return _check("binary", False, f"{binary}: {problem}")
    return _check("binary", True, f"{MODEL_ID}: starts on this machine")


def _probe(binary: Path) -> str | None:
    """Ask the binary for its help; ``None`` when it answers with exit 0.

    Only exit 0 counts: a usage error from a broken binary must fail the
    check, not pass it. A failure to start at all — ``ENOEXEC``, the wrong
    architecture, a missing loader — is a problem the same way.
    """
    try:
        done = subprocess.run(
            [str(binary), "--help"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"cannot run on this machine ({exc})"
    if done.returncode != 0:
        return f"--help exited {done.returncode}"
    return None


def _doctor_imports() -> dict[str, Any]:
    """The measurement imports, each with its version."""
    found: list[str] = []
    broken: list[str] = []
    for module_name, distribution in DOCTOR_IMPORTS:
        try:
            module = importlib.import_module(module_name)
            found.append(f"{module_name} {getattr(module, '__version__', _version(distribution))}")
        except Exception as exc:  # catch-all: one broken import must not hide the rest
            broken.append(f"{module_name}: {exc}")
    if broken:
        return _check("imports", False, "; ".join(broken))
    return _check("imports", True, ", ".join(found))


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _doctor_roundtrip(req: Request) -> dict[str, Any]:
    """Full depth: enhance a 1 s synthetic noisy 48 kHz WAV and confirm it parses."""
    started = time.monotonic()
    try:
        binary = _binary(req)
    except (KeyError, OSError, RuntimeError) as exc:
        return _check("roundtrip", False, f"the binary is missing: {exc}")
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            source = tmp / "noisy.wav"
            _write_noisy_sine(source)
            in_wav = tmp / "noisy.in.wav"
            _ffmpeg(
                [
                    "-i",
                    str(source),
                    "-ar",
                    str(RATE_HZ),
                    "-ac",
                    "1",
                    "-acodec",
                    "pcm_s16le",
                    str(in_wav),
                ]
            )
            enhanced_dir = tmp / "enhanced"
            enhanced_dir.mkdir()
            _execute(command(binary, 100.0, True, enhanced_dir, in_wav), tmp)
            out = _enhanced_wav(enhanced_dir, in_wav)
            props = _measure_wav(out)
            if not props["duration_s"] or int(props["sample_rate_hz"]) != RATE_HZ:
                raise ValueError(f"the enhanced WAV does not parse: {props}")
    except Exception as exc:  # catch-all: the check reports, the verb survives
        elapsed = time.monotonic() - started
        elapsed_s = round(elapsed, 1)
        return _check("roundtrip", False, f"the noisy roundtrip failed after {elapsed_s} s: {exc}")
    elapsed = time.monotonic() - started
    return _check(
        "roundtrip", True, f"1 s noisy sine enhanced to {props['duration_s']} s in {elapsed:.1f} s"
    )


def _write_noisy_sine(path: Path) -> None:
    """A 1 s 440 Hz sine with a deterministic noise floor at 48 kHz mono."""
    numpy = importlib.import_module("numpy")
    count = int(DOCTOR_SECONDS * RATE_HZ)
    tone = 0.5 * numpy.sin(2 * numpy.pi * DOCTOR_SINE_HZ * numpy.arange(count) / RATE_HZ)
    state = 12345
    noise = numpy.empty(count)
    for index in range(count):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        noise[index] = state / 0x3FFFFFFF - 1.0
    samples = (tone + DOCTOR_NOISE_AMPLITUDE * noise).astype(numpy.float64)
    audiopreview.write_wav(path, samples, RATE_HZ)


runner.main()
