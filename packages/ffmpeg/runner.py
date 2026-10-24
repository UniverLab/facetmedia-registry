"""The ffmpeg package runner: loudness, mixing and conversion with the bundled binary.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` executes the requested capability
(``normalize``, ``mix`` or ``convert``) with the static FFmpeg binary
imageio-ffmpeg bundles, ``verify`` re-measures the outputs with soundfile
and pyloudnorm, ``preview`` writes the audio preview file, ``doctor``
checks the tool at ``quick`` and ``full`` depth.

The command builders and the loudnorm parser live in ``graph`` (pure,
stdlib-only, unit-tested); the signal measurements live in ``audiopreview``
(a byte-identical copy of kokoro's). The bundled binary ships no ffprobe:
every measurement decodes to a 32-bit float WAV and goes through
soundfile and pyloudnorm. Heavy imports go through ``importlib`` inside
the functions, so a broken environment still lets the doctor report
*which* import fails instead of dying on a top-level import.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audiopreview
import graph
from facet_runner_sdk import Request, Runner

runner = Runner()

#: The manifest's verify thresholds, repeated here so a run never drifts from them.
LUFS_TOL = 1.0
#: verify: the measurement margin above the peak ceiling, in dBFS.
PEAK_MARGIN_DB = 0.1
#: verify: duration tolerance for normalize and convert, and for the mix.
DURATION_TOL_S = 0.02
MIX_DURATION_TOL_S = 0.05
#: verify: the mix peak ceiling in dBFS (its alimiter sits at -1 dBFS).
MIX_PEAK_CEILING_DBFS = -0.9
#: The mix's own loudnorm defaults: the normalize capability's, at 48 kHz.
MIX_TRUE_PEAK_DB = -1.5
MIX_RATE_HZ = 48000
#: The piece defaults the manifest fills (repeated here for records and verify).
DEFAULT_TARGET_LUFS = -16.0
DEFAULT_TRUE_PEAK_DB = -1.5
DEFAULT_BITRATE_KBPS = 128
#: Every ffmpeg call: its own process group, no stdin, banners off, overwrite.
FFMPEG_FLAGS = ("-nostdin", "-hide_banner", "-y")
#: The stderr tail a failed ffmpeg call reports as the runner error.
STDERR_TAIL_CHARS = 2000
#: The doctor's throwaway roundtrip: one second of 440 Hz sine via lavfi.
DOCTOR_SINE = "sine=frequency=440:duration=1"
DOCTOR_RATE_HZ = 48000
#: Imports the doctor proves, with the distribution each comes from.
DOCTOR_IMPORTS = (
    ("numpy", "numpy"),
    ("pyloudnorm", "pyloudnorm"),
    ("soundfile", "soundfile"),
)
#: Mime type per format.
MIME = {"wav": "audio/wav", "flac": "audio/flac", "mp3": "audio/mpeg", "ogg": "audio/ogg"}
#: One verb of this runner per capability; anything else is a manifest bug.
CAPABILITY_VERBS: dict[str, Callable[[dict[str, Any], Path], list[dict[str, Any]]]] = {}


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


@lru_cache(maxsize=1)
def _version_text() -> str:
    """The bundled binary's ``-version`` output, run once per process."""
    return _ffmpeg(["-version"]).stdout


def _tool() -> dict[str, str]:
    """The record's tool: the binary's own -version line, never a system ffmpeg."""
    return {"name": "ffmpeg", "version": graph.version_line(_version_text())}


def _capability(req: Request) -> str:
    """The bare capability name (normalize, mix, convert) this request asked for."""
    return req.capability.rsplit(".", 1)[-1]


def _measure(path: Path, tmp: Path, tag: str) -> dict[str, Any]:
    """Decode to 32-bit float WAV and measure: duration, rate, channels, loudness, peak."""
    tmp.mkdir(parents=True, exist_ok=True)
    decoded = tmp / f"{tag}.measure.wav"
    _ffmpeg(graph.measure_args(path, decoded))
    samples, rate = audiopreview.read_wav(decoded)
    return {
        "duration_s": round(audiopreview.duration_s(samples, rate), 3),
        "sample_rate_hz": rate,
        "channels": audiopreview.channels(samples),
        "lufs": round(audiopreview.integrated_lufs(samples, rate), 2),
        "peak_dbfs": round(audiopreview.peak_dbfs(samples), 2),
    }


def _two_pass(
    source: Path, out: Path, target_lufs: float, true_peak_db: float, rate: int, tmp: Path
) -> None:
    """The two loudnorm passes: measure the source, then apply the values linearly."""
    done = _ffmpeg(
        [
            "-i",
            str(source),
            "-af",
            graph.measure_chain(target_lufs, true_peak_db),
            "-f",
            "null",
            "-",
        ]
    )
    measured = graph.loudnorm_json(done.stderr)
    _ffmpeg(graph.normalize_args(source, out, target_lufs, true_peak_db, measured, rate))


def _asset(
    name: str,
    file: str,
    mime: str,
    properties: Mapping[str, Any],
    params: Mapping[str, Any],
    inputs: Sequence[Path],
) -> dict[str, Any]:
    """One asset record: the measured properties, the manifest-named params, the inputs."""
    return {
        "file": file,
        "name": name,
        "kind": "audio",
        "mime": mime,
        "properties": dict(properties),
        "params": dict(params),
        "seed": None,
        "inputs": [str(path) for path in inputs],
    }


def _opt_float(params: Mapping[str, Any], key: str) -> float | None:
    value = params.get(key)
    return None if value is None else float(value)


def _opt_int(params: Mapping[str, Any], key: str) -> int | None:
    value = params.get(key)
    return None if value is None else int(value)


def _opt_str(params: Mapping[str, Any], key: str) -> str | None:
    value = params.get(key)
    return None if value is None else str(value)


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    """Execute the capability: normalise, mix or convert with the bundled binary."""
    verb = CAPABILITY_VERBS.get(_capability(req))
    if verb is None:
        known = ", ".join(sorted(CAPABILITY_VERBS))
        raise ValueError(f"{req.capability}: unknown capability (this runner has: {known})")
    return {"tool": _tool(), "assets": verb(dict(req.inputs), req.out_dir)}


def _normalize_clips(params: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every clip with the piece defaults resolved into its own fields."""
    target = float(params.get("target-lufs", DEFAULT_TARGET_LUFS))
    true_peak = float(params.get("true-peak-db", DEFAULT_TRUE_PEAK_DB))
    rate = int(params.get("sample-rate-hz", MIX_RATE_HZ))
    return [
        {
            "name": str(clip["name"]),
            "audio": Path(str(clip["audio"])),
            "target_lufs": target,
            "true_peak_db": true_peak,
            "sample_rate_hz": rate,
        }
        for clip in params.get("clip", [])
    ]


def _run_normalize(params: Mapping[str, Any], out_dir: Path) -> list[dict[str, Any]]:
    return [_normalize_clip(clip, out_dir) for clip in _normalize_clips(params)]


def _normalize_clip(clip: Mapping[str, Any], out_dir: Path) -> dict[str, Any]:
    """One clip: two loudnorm passes to its target, then measured for the record."""
    audio = clip["audio"]
    name = str(clip["name"])
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        out = out_dir / f"{name}.wav"
        _two_pass(
            audio,
            out,
            float(clip["target_lufs"]),
            float(clip["true_peak_db"]),
            int(clip["sample_rate_hz"]),
            tmp,
        )
        properties = _measure(out, tmp, name)
    params = {
        "clip": [{"name": name, "audio": str(audio)}],
        "target-lufs": float(clip["target_lufs"]),
        "true-peak-db": float(clip["true_peak_db"]),
        "sample-rate-hz": str(int(clip["sample_rate_hz"])),
    }
    return _asset(name, out.name, MIME["wav"], properties, params, [audio])


def _layers(params: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The piece's layers in snake_case, as the filtergraph builders read them."""
    return [
        {
            "audio": Path(str(layer["audio"])),
            "role": str(layer["role"]),
            "gain_db": float(layer.get("gain-db", 0.0)),
            "start_s": float(layer.get("start-s", 0.0)),
        }
        for layer in params.get("layer", [])
    ]


def _run_mix(params: Mapping[str, Any], out_dir: Path) -> list[dict[str, Any]]:
    """One filtergraph to ``<name>.raw.wav``, then rename or normalise to ``<name>.wav``."""
    name = str(params["name"])
    layers = _layers(params)
    ducking = bool(params.get("ducking", True))
    duck_db = float(params.get("duck-db", -12.0))
    target = _opt_float(params, "target-lufs")
    inputs = [Path(str(layer["audio"])) for layer in layers]
    filtergraph = graph.mix_filtergraph(layers, ducking, duck_db)
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        raw = tmp / f"{name}.raw.wav"
        _ffmpeg(graph.mix_args(filtergraph, inputs, raw))
        out = out_dir / f"{name}.wav"
        if target is None:
            # move, not rename: /tmp may be another filesystem than the out dir.
            shutil.move(str(raw), str(out))
        else:
            _two_pass(raw, out, target, MIX_TRUE_PEAK_DB, MIX_RATE_HZ, tmp)
        properties = _measure(out, tmp, name)
    return [_asset(name, out.name, MIME["wav"], properties, _mix_params(params), inputs)]


def _mix_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """The mix's piece fields under their manifest names; target only when given."""
    resolved: dict[str, Any] = {
        "name": str(params["name"]),
        "layer": [
            {
                "audio": str(layer["audio"]),
                "role": str(layer["role"]),
                "gain-db": float(layer.get("gain-db", 0.0)),
                "start-s": float(layer.get("start-s", 0.0)),
            }
            for layer in params.get("layer", [])
        ],
        "ducking": bool(params.get("ducking", True)),
        "duck-db": float(params.get("duck-db", -12.0)),
    }
    target = _opt_float(params, "target-lufs")
    if target is not None:
        resolved["target-lufs"] = target
    return resolved


def _run_convert(params: Mapping[str, Any], out_dir: Path) -> list[dict[str, Any]]:
    """Cut, resample and encode with the format's encoder, straight from the source."""
    audio = Path(str(params["audio"]))
    name = str(params["name"])
    fmt = str(params.get("format", "wav"))
    cut = (_opt_float(params, "start-s"), _opt_float(params, "end-s"))
    channels = _opt_int(params, "channels")
    out = out_dir / f"{name}.{fmt}"
    _ffmpeg(
        graph.convert_args(
            audio,
            out,
            fmt,
            cut,
            _opt_int(params, "sample-rate-hz"),
            channels,
            int(params.get("bitrate-kbps", DEFAULT_BITRATE_KBPS)),
        )
    )
    with tempfile.TemporaryDirectory() as folder:
        properties = _measure(out, Path(folder), name)
    return [_asset(name, out.name, MIME[fmt], properties, _convert_params(params), [audio])]


def _convert_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """The convert piece fields under their manifest names; optionals only when given."""
    resolved: dict[str, Any] = {
        "audio": str(params["audio"]),
        "name": str(params["name"]),
        "format": str(params.get("format", "wav")),
        "bitrate-kbps": int(params.get("bitrate-kbps", DEFAULT_BITRATE_KBPS)),
    }
    for key, kind in (
        ("sample-rate-hz", _opt_int),
        ("channels", _opt_str),
        ("start-s", _opt_float),
        ("end-s", _opt_float),
    ):
        value = kind(params, key)
        if value is not None:
            resolved[key] = value
    return resolved


CAPABILITY_VERBS.update({"normalize": _run_normalize, "mix": _run_mix, "convert": _run_convert})


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    """Re-measure every asset against the capability's acceptance rule."""
    params = dict(req.inputs)
    one = _VERIFIES.get(_capability(req))
    if one is None:
        raise ValueError(f"{req.capability}: no verifier for this capability")
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        entries = [
            one(params, path, tmp / f"asset{index}") for index, path in enumerate(req.assets)
        ]
    return {"assets": entries}


def _verdict(file: str, passed: bool, metrics: Mapping[str, Any], thresholds: Mapping[str, Any]):
    """One verify entry: the four metrics, the thresholds, and what measured them."""
    return {
        "file": file,
        "passed": passed,
        "metrics": dict(metrics),
        "thresholds": dict(thresholds),
        "verifier": f"ffmpeg {graph.version_id(_version_text())} loudnorm",
    }


def _duration_error(props: Mapping[str, Any], expected: float) -> float:
    return round(abs(float(props["duration_s"]) - expected), 3)


def _verify_normalize(params: Mapping[str, Any], path: Path, tmp: Path) -> dict[str, Any]:
    """Within 1 LU of the target, at or under the true-peak ceiling, duration kept."""
    clips = {clip["name"]: clip for clip in _normalize_clips(params)}
    clip = clips.get(path.stem)
    if clip is None:
        raise ValueError(f"{path.name}: no clip named {path.stem!r} in the piece")
    props = _measure(path, tmp, "out")
    source = _measure(clip["audio"], tmp, "src")
    error = _duration_error(props, float(source["duration_s"]))
    metrics = {
        "lufs": props["lufs"],
        "peak_dbfs": props["peak_dbfs"],
        "duration_s": props["duration_s"],
        "duration_error_s": error,
    }
    passed = (
        abs(float(props["lufs"]) - float(clip["target_lufs"])) <= LUFS_TOL
        and float(props["peak_dbfs"]) <= float(clip["true_peak_db"]) + PEAK_MARGIN_DB
        and error <= DURATION_TOL_S
    )
    return _verdict(path.name, passed, metrics, {"lufs_tol": LUFS_TOL})


def _verify_mix(params: Mapping[str, Any], path: Path, tmp: Path) -> dict[str, Any]:
    """Duration from the longest delayed layer, peak at or under -0.9 dBFS, target loudness."""
    layers = _layers(params)
    ends = [
        float(layer["start_s"]) + float(_measure(Path(layer["audio"]), tmp, f"s{i}")["duration_s"])
        for i, layer in enumerate(layers)
    ]
    props = _measure(path, tmp, "out")
    error = _duration_error(props, max(ends))
    metrics = {
        "lufs": props["lufs"],
        "peak_dbfs": props["peak_dbfs"],
        "duration_s": props["duration_s"],
        "duration_error_s": error,
    }
    target = _opt_float(params, "target-lufs")
    loudness_ok = target is None or abs(float(props["lufs"]) - target) <= LUFS_TOL
    passed = (
        error <= MIX_DURATION_TOL_S
        and float(props["peak_dbfs"]) <= MIX_PEAK_CEILING_DBFS
        and loudness_ok
    )
    return _verdict(path.name, passed, metrics, {"lufs_tol": LUFS_TOL})


def _verify_convert(params: Mapping[str, Any], path: Path, tmp: Path) -> dict[str, Any]:
    """The decoded output has the requested rate and channels, and keeps the wanted span."""
    source = _measure(Path(str(params["audio"])), tmp, "src")
    props = _measure(path, tmp, "out")
    error = _duration_error(props, _wanted_duration(params, float(source["duration_s"])))
    metrics = {
        "lufs": props["lufs"],
        "peak_dbfs": props["peak_dbfs"],
        "duration_s": props["duration_s"],
        "duration_error_s": error,
    }
    fmt = str(params.get("format", "wav"))
    requested_rate = _opt_int(params, "sample-rate-hz")
    # ogg always decodes at 48000 (libopus), whatever the piece asked for.
    expected_rate = (
        MIX_RATE_HZ if fmt == "ogg" else (requested_rate or int(source["sample_rate_hz"]))
    )
    requested_channels = _opt_int(params, "channels")
    expected_channels = requested_channels or int(source["channels"])
    passed = (
        int(props["sample_rate_hz"]) == expected_rate
        and int(props["channels"]) == expected_channels
        and error <= DURATION_TOL_S
    )
    return _verdict(path.name, passed, metrics, {})


def _wanted_duration(params: Mapping[str, Any], source_s: float) -> float:
    """end_s - start_s when cut both ways, one side when cut once, else the source."""
    start_s = _opt_float(params, "start-s") or 0.0
    end_s = _opt_float(params, "end-s")
    if end_s is None:
        return max(source_s - start_s, 0.0)
    return max(end_s - start_s, 0.0)


_VERIFIES: dict[str, Callable[[Mapping[str, Any], Path, Path], dict[str, Any]]] = {
    "normalize": _verify_normalize,
    "mix": _verify_mix,
    "convert": _verify_convert,
}


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    """Write ``<asset>.preview.json`` for every asset, decoded through the bundled ffmpeg."""
    params = dict(req.inputs)
    cap = _capability(req)
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        entries = []
        for index, path in enumerate(req.assets):
            preview_name = f"{path.name}.preview.json"
            data = _preview_data(cap, params, path, tmp / f"asset{index}")
            (req.out_dir / preview_name).write_text(
                json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
            )
            entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _preview_data(cap: str, params: Mapping[str, Any], path: Path, tmp: Path) -> dict[str, Any]:
    """The audio preview file: waveform, loudness and silences, no speech section."""
    tmp.mkdir(parents=True, exist_ok=True)
    decoded = tmp / "preview.measure.wav"
    _ffmpeg(graph.measure_args(path, decoded))
    samples, rate = audiopreview.read_wav(decoded)
    lufs = audiopreview.integrated_lufs(samples, rate)
    peak = audiopreview.peak_dbfs(samples)
    duration = audiopreview.duration_s(samples, rate)
    return {
        "preview": 1,
        "kind": "audio",
        "summary": _summary(cap, params, duration, lufs, peak),
        "duration_s": round(duration, 3),
        "sample_rate_hz": rate,
        "channels": audiopreview.channels(samples),
        "waveform": audiopreview.waveform(samples),
        "loudness": {
            "integrated_lufs": round(lufs, 2),
            "peak_dbfs": round(peak, 2),
            "target_lufs": _target_lufs(cap, params),
            "momentary": {
                "step_s": 0.1,
                "window_s": 0.4,
                "lufs": audiopreview.momentary(samples, rate),
            },
        },
        "silences": audiopreview.silences(samples, rate),
        "clipped_samples": audiopreview.clipped_samples(samples),
    }


def _target_lufs(cap: str, params: Mapping[str, Any]) -> float | None:
    """The capability's target: normalize's default, mix's when given, never convert's."""
    if cap == "normalize":
        return float(params.get("target-lufs", DEFAULT_TARGET_LUFS))
    if cap == "mix":
        return _opt_float(params, "target-lufs")
    return None


def _summary(cap: str, params: Mapping[str, Any], duration: float, lufs: float, peak: float) -> str:
    """One line like ``mix · 15.0 s · -16.1 LUFS · peak -1.0 dBFS · bed ducked -12 dB``."""
    text = f"{cap} · {duration:.1f} s · {lufs:.1f} LUFS · peak {peak:.1f} dBFS"
    if cap == "mix" and _ducked(params):
        text += f" · bed ducked {float(params.get('duck-db', -12.0)):g} dB"
    return text[:160]


def _ducked(params: Mapping[str, Any]) -> bool:
    """Whether the mix really ducks: ducking on, with at least one bed and one voice."""
    if not bool(params.get("ducking", True)):
        return False
    roles = [str(layer["role"]) for layer in params.get("layer", [])]
    return "bed" in roles and "voice" in roles


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    """Quick: the binary, its encoders, the imports. Full: one normalised sine."""
    checks = [_doctor_binary(), _doctor_encoders(), _doctor_imports()]
    if req.depth == "full":
        checks.append(_doctor_roundtrip())
    return {"checks": checks}


def _verdict_check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    """One doctor check; every failure names the pull that fixes the env."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else "facet pull ffmpeg"}


def _doctor_binary() -> dict[str, Any]:
    """The bundled binary runs ``-version`` and names itself."""
    try:
        text = _version_text()
        build = graph.version_id(text)
    except Exception as exc:  # catch-all: the doctor reports, the verb survives
        return _verdict_check("binary", False, f"the bundled ffmpeg does not run: {exc}")
    if not build:
        return _verdict_check("binary", False, "ffmpeg -version printed no version line")
    return _verdict_check("binary", True, f"ffmpeg {build} at {Path(_exe()).name}")


def _doctor_encoders() -> dict[str, Any]:
    """Every encoder behind the convert format enum is listed by the binary."""
    try:
        listed = graph.encoder_names(_ffmpeg(["-encoders"]).stdout)
    except Exception as exc:  # catch-all: report whatever went wrong
        return _verdict_check("encoders", False, f"ffmpeg -encoders failed: {exc}")
    wanted = sorted(set(graph.CODECS.values()))
    missing = [codec for codec in wanted if codec not in listed]
    if missing:
        return _verdict_check("encoders", False, f"missing encoders: {', '.join(missing)}")
    return _verdict_check("encoders", True, ", ".join(wanted))


def _doctor_imports() -> dict[str, Any]:
    """The three measurement imports, each with its version."""
    found: list[str] = []
    broken: list[str] = []
    for module_name, distribution in DOCTOR_IMPORTS:
        try:
            module = importlib.import_module(module_name)
            found.append(f"{module_name} {getattr(module, '__version__', _version(distribution))}")
        except Exception as exc:  # catch-all: one broken import must not hide the rest
            broken.append(f"{module_name}: {exc}")
    if broken:
        return _verdict_check("imports", False, "; ".join(broken))
    return _verdict_check("imports", True, ", ".join(found))


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _doctor_roundtrip() -> dict[str, Any]:
    """Full depth: a 1 s 440 Hz sine normalised to -16 LUFS must measure within 1 LU."""
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            sine = tmp / "sine.wav"
            _ffmpeg(["-f", "lavfi", "-i", DOCTOR_SINE, "-ar", str(DOCTOR_RATE_HZ), str(sine)])
            out = tmp / "sine-normalized.wav"
            _two_pass(sine, out, DEFAULT_TARGET_LUFS, DEFAULT_TRUE_PEAK_DB, DOCTOR_RATE_HZ, tmp)
            measured = float(_measure(out, tmp, "check")["lufs"])
    except Exception as exc:  # catch-all: the check reports, the verb survives
        elapsed = time.monotonic() - started
        return _verdict_check(
            "roundtrip", False, f"the sine roundtrip failed after {elapsed:.1f} s: {exc}"
        )
    elapsed = time.monotonic() - started
    error = abs(measured - DEFAULT_TARGET_LUFS)
    target = f"{DEFAULT_TARGET_LUFS:g}"
    return _verdict_check(
        "roundtrip",
        error <= LUFS_TOL,
        f"1 s 440 Hz sine → {measured:.1f} LUFS (target {target}) in {elapsed:.1f} s",
    )


runner.main()
