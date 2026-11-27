"""The audiogram package runner: audio-reactive videos on CPU.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` decodes the piece's ``audio`` to mono WAV
with the bundled FFmpeg binary, computes per-frame FFT bar heights or
RMS waveform envelopes deterministically in NumPy, renders RGB frames
with Pillow over an editorial card or cover image, and pipes rawvideo
frames plus the original audio into the bundled ``imageio-ffmpeg``
binary (``libx264`` + ``yuv420p`` + ``aac`` + ``+faststart``);
``verify`` checks size, dimensions, duration, audio-stream presence and
frame motion; ``preview`` writes ``video`` preview JSON; ``doctor``
checks the binary and imports, rendering a 1 s 440 Hz synthetic sine
audiogram at full depth.
"""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from facet_runner_sdk import Request, Runner

runner = Runner()

#: The preview records carry seed 0 (the render is deterministic).
SEED = 0
#: Canvas pixels per aspect ratio.
SIZES = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080)}
STYLES = ("bars", "waveform")
DEFAULT_STYLE = "bars"
DEFAULT_ASPECT = "1:1"
DEFAULT_BACKGROUND = "#111315"
DEFAULT_ACCENT = "#E8C547"
DEFAULT_FPS = 24
DEFAULT_CRF = 23
#: Mono decode rate for analysis.
SAMPLE_RATE = 44100
#: FFT window per bars frame and bar count across the canvas.
FFT_WINDOW = 2048
BAR_COUNT = 64
#: Verify tolerates this much drift between source audio and MP4 duration.
DURATION_TOL_S = 0.2
#: Mean per-pixel frame difference (0-255) that counts as motion.
MOTION_EPS = 0.5
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_BAD_NAME = re.compile(r"[^a-z0-9-]+")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_SIZE_RE = re.compile(r"(?:^|[\s,])(\d{2,5})x(\d{2,5})(?=[\s,]|$)")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps\b")
_TBR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*tbr\b")
_VIDEO_RE = re.compile(r"Stream\s+#\d+:\d+[^:]*:\s*Video:\s*([^\s,(]+)(.*)$", re.MULTILINE)
_AUDIO_RE = re.compile(r"Stream\s+#\d+:\d+[^:]*:\s*Audio:\s*([^\s,(]+)", re.MULTILINE)


def _exe() -> str:
    """Return the bundled static FFmpeg binary path from imageio-ffmpeg."""
    imageio_ffmpeg = importlib.import_module("imageio_ffmpeg")
    return str(imageio_ffmpeg.get_ffmpeg_exe())


def _numpy() -> Any:
    """Lazily import NumPy so doctor can report broken environments."""
    return importlib.import_module("numpy")


def _soundfile() -> Any:
    """Lazily import soundfile so doctor can report broken environments."""
    return importlib.import_module("soundfile")


def _pil_image() -> Any:
    """Lazily import PIL.Image so doctor can report broken environments."""
    return importlib.import_module("PIL.Image")


def _ffmpeg(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run one ffmpeg call; raise RuntimeError on non-zero exit."""
    done = subprocess.run(
        [_exe(), "-nostdin", "-hide_banner", "-y", *args],
        capture_output=True,
        text=True,
        start_new_session=True,
        check=False,
    )
    if done.returncode != 0:
        tail = (done.stderr or "")[-2000:].strip()
        raise RuntimeError(f"ffmpeg exited {done.returncode}: {tail}")
    return done


def _probe(path: Path) -> dict[str, Any]:
    """Parse ``ffmpeg -i`` stderr into duration, size, fps and codecs."""
    done = subprocess.run(
        [_exe(), "-nostdin", "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        start_new_session=True,
        check=False,
    )
    stderr = done.stderr or ""
    props: dict[str, Any] = {}
    match = _DURATION_RE.search(stderr)
    if match:
        hours, minutes, seconds = match.groups()
        props["duration_s"] = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    video = _VIDEO_RE.search(stderr)
    if video:
        props["video_codec"] = video.group(1)
        rest = video.group(2)
        size = _SIZE_RE.search(rest)
        if size:
            props["width"] = int(size.group(1))
            props["height"] = int(size.group(2))
        fps = _FPS_RE.search(rest) or _TBR_RE.search(rest)
        if fps:
            props["fps"] = float(fps.group(1))
    audio = _AUDIO_RE.search(stderr)
    if audio:
        props["audio_codec"] = audio.group(1)
    return props


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _hex_to_rgb(raw: str) -> tuple[int, int, int]:
    """A ``#rrggbb`` string to an RGB triple; raises ValueError when bad."""
    if not _HEX.match(raw):
        raise ValueError(f"{raw!r}: want a #rrggbb hex color")
    return int(raw[1:3], 16), int(raw[3:5], 16), int(raw[5:7], 16)


def _resolve_path(piece_dir: Path, raw: object) -> Path:
    """Resolve a piece path input relative to ``piece_dir`` when relative."""
    path = Path(str(raw))
    return path if path.is_absolute() else (piece_dir / path).resolve()


@dataclass(frozen=True)
class Spec:
    """The piece's resolved inputs; the filename follows the asset name."""

    audio: Path
    name: str
    style: str
    aspect: str
    cover: Path | None
    title: str
    background: str
    accent: str
    fps: int
    crf: int

    @property
    def filename(self) -> str:
        """The asset filename: ``<name>.mp4``."""
        return f"{self.name}.mp4"

    @property
    def size(self) -> tuple[int, int]:
        """The canvas pixels for the requested aspect ratio."""
        return SIZES[self.aspect]


def _resolve(params: dict[str, Any], piece_dir: Path) -> Spec:
    """Fold defaults over the piece inputs and check colors and paths."""
    audio = _resolve_path(piece_dir, params["audio"])
    if not audio.is_file():
        raise ValueError(f"{params['audio']}: audio file not found")
    cover_raw = params.get("cover")
    cover = _resolve_path(piece_dir, cover_raw) if cover_raw else None
    if cover is not None and not cover.is_file():
        raise ValueError(f"{cover_raw}: cover image not found")
    background = str(params.get("background", DEFAULT_BACKGROUND))
    accent = str(params.get("accent", DEFAULT_ACCENT))
    _hex_to_rgb(background)
    _hex_to_rgb(accent)
    style = str(params.get("style", DEFAULT_STYLE))
    aspect = str(params.get("aspect", DEFAULT_ASPECT))
    if style not in STYLES:
        raise ValueError(f"{style}: want one of {', '.join(STYLES)}")
    if aspect not in SIZES:
        raise ValueError(f"{aspect}: want one of {', '.join(SIZES)}")
    return Spec(
        audio=audio,
        name=str(params["name"]),
        style=style,
        aspect=aspect,
        cover=cover,
        title=str(params.get("title", "")),
        background=background,
        accent=accent,
        fps=int(params.get("fps", DEFAULT_FPS)),
        crf=int(params.get("crf", DEFAULT_CRF)),
    )


def _decode_mono(src: Path, dest: Path) -> None:
    """Decode any FFmpeg-readable clip to mono 44.1 kHz WAV."""
    _ffmpeg(
        [
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "wav",
            str(dest),
        ]
    )


def _load_samples(wav: Path) -> Any:
    """The decoded mono samples as a flat float array."""
    np = _numpy()
    soundfile = _soundfile()
    data, _rate = soundfile.read(str(wav), dtype="float32")
    return np.asarray(data, dtype=float).ravel()


def _bar_matrix(samples: Any, n_frames: int) -> Any:
    """Per-frame log FFT magnitudes over the first bar bins, peak-normalized."""
    np = _numpy()
    hop = len(samples) / n_frames
    half = FFT_WINDOW // 2
    padded = np.pad(samples, (half, half))
    mags = np.empty((n_frames, BAR_COUNT))
    for index in range(n_frames):
        center = int((index + 0.5) * hop) + half
        window = padded[center - half : center + half]
        mags[index] = np.log1p(np.abs(np.fft.rfft(window))[:BAR_COUNT])
    peak = mags.max()
    if peak > 0:
        mags /= peak
    return mags


def _wave_matrix(samples: Any, n_frames: int, width: int) -> Any:
    """Per-frame per-column peak amplitudes, peak-normalized."""
    np = _numpy()
    hop = len(samples) / n_frames
    span = max(int(hop * 2), width)
    padded = np.pad(samples, (span, span))
    peaks = np.empty((n_frames, width))
    for index in range(n_frames):
        center = int((index + 0.5) * hop) + span
        window = np.abs(padded[center - span : center + span])
        usable = (len(window) // width) * width
        peaks[index] = window[:usable].reshape(width, -1).max(axis=1)
    peak = peaks.max()
    if peak > 0:
        peaks /= peak
    return peaks


def _background(size: tuple[int, int], spec: Spec) -> Any:
    """The card canvas: dimmed cover fill, or the flat background color."""
    pil = _pil_image()
    width, height = size
    if spec.cover is None:
        return pil.new("RGB", size, _hex_to_rgb(spec.background))
    with pil.open(spec.cover) as img:
        cover = img.convert("RGB")
    scale = max(width / cover.width, height / cover.height)
    cover = cover.resize((max(1, round(cover.width * scale)), max(1, round(cover.height * scale))))
    left = (cover.width - width) // 2
    top = (cover.height - height) // 2
    canvas = cover.crop((left, top, left + width, top + height))
    return pil.blend(canvas, pil.new("RGB", size, (0, 0, 0)), 0.45)


def _draw_title(draw: Any, size: tuple[int, int], title: str) -> int:
    """Draw the centered card title; return the visualizer's top edge."""
    if not title:
        return int(size[1] * 0.10)
    image_font = importlib.import_module("PIL.ImageFont")
    font = image_font.load_default(size=max(24, size[1] // 18))
    box = draw.textbbox((0, 0), title, font=font)
    draw.text(((size[0] - (box[2] - box[0])) / 2, size[1] * 0.05), title, font=font, fill="white")
    return int(box[3] - box[1] + size[1] * 0.09)


def _draw_bars(draw: Any, heights: Any, size: tuple[int, int], top: int, accent: str) -> None:
    """Draw FFT bars from the baseline up, with a small gutter between bars."""
    width, height = size
    margin = int(width * 0.06)
    baseline = int(height * 0.84)
    avail = width - 2 * margin
    slot = avail / BAR_COUNT
    bar_h = baseline - top
    for index, level in enumerate(heights):
        pixels = int(float(level) * bar_h)
        x0 = margin + index * slot
        draw.rectangle([x0, baseline - pixels, x0 + slot * 0.72, baseline], fill=accent)


def _draw_waveform(draw: Any, peaks: Any, size: tuple[int, int], top: int, accent: str) -> None:
    """Draw the centered amplitude waveform as one vertical span per column."""
    width, height = size
    margin = int(width * 0.06)
    mid = (top + int(height * 0.86)) // 2
    amp = (int(height * 0.86) - top) // 2
    step = (width - 2 * margin) / len(peaks)
    for index, level in enumerate(peaks):
        pixels = max(1, int(float(level) * amp))
        x = margin + index * step
        draw.line([x, mid - pixels, x, mid + pixels], fill=accent, width=max(1, int(step)))


def _render_frame(canvas: Any, spec: Spec, row: Any, top: int) -> Any:
    """One RGB frame: the card canvas plus the style's visualizer row."""
    draw_module = importlib.import_module("PIL.ImageDraw")
    frame = canvas.copy()
    draw = draw_module.Draw(frame)
    if spec.style == "waveform":
        _draw_waveform(draw, row, frame.size, top, spec.accent)
    else:
        _draw_bars(draw, row, frame.size, top, spec.accent)
    return frame


def _encode(frames: Any, spec: Spec, out: Path) -> None:
    """Pipe RGB frames on stdin and the source audio into libx264 + aac."""
    width, height = spec.size
    cmd = [
        _exe(),
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(spec.fps),
        "-i",
        "-",
        "-i",
        str(spec.audio),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        str(spec.crf),
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        "-shortest",
        str(out),
    ]
    with tempfile.TemporaryFile(prefix="audiogram-encode-") as errors:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=errors,
            start_new_session=True,
        )
        assert proc.stdin is not None
        for frame in frames:
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        code = proc.wait()
        errors.seek(0)
        detail = errors.read().decode(errors="replace")[-2000:]
    if code != 0:
        raise RuntimeError(f"ffmpeg encode exited {code}: {detail}")


def _render(params: dict[str, Any], out_dir: Path, piece_dir: Path) -> list[dict[str, Any]]:
    """Decode, analyze, draw and encode one audiogram MP4."""
    np = _numpy()
    spec = _resolve(params, piece_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="audiogram-") as tmp:
        wav = Path(tmp) / "mono.wav"
        _decode_mono(spec.audio, wav)
        samples = _load_samples(wav)
    if len(samples) < SAMPLE_RATE // spec.fps:
        raise ValueError(f"{spec.audio}: audio is shorter than one frame")
    duration_s = len(samples) / SAMPLE_RATE
    n_frames = max(2, round(duration_s * spec.fps))
    if spec.style == "waveform":
        rows = _wave_matrix(samples, n_frames, spec.size[0])
    else:
        rows = _bar_matrix(samples, n_frames)
    canvas = _background(spec.size, spec)
    draw_module = importlib.import_module("PIL.ImageDraw")
    probe_draw = draw_module.Draw(canvas.copy())
    top = _draw_title(probe_draw, spec.size, spec.title)
    out = out_dir / spec.filename
    frames = (np.asarray(_render_frame(canvas, spec, rows[i], top)) for i in range(n_frames))
    _encode(frames, spec, out)
    props = _probe(out)
    asset = {
        "file": out.name,
        "name": spec.name,
        "kind": "video",
        "mime": "video/mp4",
        "properties": {
            "width": spec.size[0],
            "height": spec.size[1],
            "duration_s": props.get("duration_s"),
            "fps": spec.fps,
        },
        "params": {
            "style": spec.style,
            "aspect": spec.aspect,
            "title": spec.title,
            "fps": spec.fps,
            "crf": spec.crf,
        },
        "seed": SEED,
        "inputs": [spec.audio.name],
    }
    return [asset]


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    """Render the requested audiogram MP4."""
    return {"tool": _tool(), "assets": _render(dict(req.inputs), req.out_dir, req.piece_dir)}


def _frame_at(path: Path, at_s: float) -> Any:
    """One decoded RGB frame as a float array."""
    np = _numpy()
    props = _probe(path)
    width, height = int(props.get("width") or 0), int(props.get("height") or 0)
    done = subprocess.run(
        [
            _exe(),
            "-nostdin",
            "-hide_banner",
            "-ss",
            str(at_s),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        start_new_session=True,
        check=False,
    )
    if done.returncode != 0 or len(done.stdout) != width * height * 3:
        raise RuntimeError(f"ffmpeg could not grab a frame at {at_s}s of {path.name}")
    return np.frombuffer(done.stdout, dtype=np.uint8).astype(float)


def _verify_asset(path: Path, params: Mapping[str, Any], piece_dir: Path) -> dict[str, Any]:
    """Verify one MP4: size, canvas, duration, audio stream and motion."""
    size = path.stat().st_size if path.is_file() else 0
    if size <= 0:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size},
            "thresholds": {},
            "verifier": "audiogram",
        }
    try:
        props = _probe(path)
        aspect = str(params.get("aspect", DEFAULT_ASPECT))
        want = SIZES.get(aspect)
        if want is None:
            raise ValueError(f"{aspect}: want one of {', '.join(SIZES)}")
        audio = _resolve_path(piece_dir, params["audio"])
        src = _probe(audio)
        src_dur = src.get("duration_s")
        if src_dur is None:
            raise ValueError(f"{audio}: no audio duration")
        out_dur = float(props.get("duration_s") or 0.0)
        duration_ok = abs(out_dur - float(src_dur)) <= DURATION_TOL_S
        dims_ok = (
            int(props.get("width") or 0) == want[0] and int(props.get("height") or 0) == want[1]
        )
        audio_ok = bool(props.get("audio_codec"))
        motion = 0.0
        motion_ok = False
        if out_dur > 0:
            first = _frame_at(path, out_dur * 0.25)
            second = _frame_at(path, out_dur * 0.60)
            motion = float(abs(first - second).mean())
            motion_ok = motion > MOTION_EPS
        passed = bool(size > 0 and duration_ok and dims_ok and audio_ok and motion_ok)
        metrics: dict[str, Any] = {
            "bytes": size,
            "width": props.get("width"),
            "height": props.get("height"),
            "duration_s": props.get("duration_s"),
            "source_duration_s": src_dur,
            "audio_codec": props.get("audio_codec"),
            "motion": round(motion, 3),
        }
    except Exception as exc:  # verify reports failure instead of crashing
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"bytes": size, "error": str(exc)},
            "thresholds": {},
            "verifier": "audiogram",
        }
    return {
        "file": path.name,
        "passed": passed,
        "metrics": metrics,
        "thresholds": {"duration_tolerance_s": DURATION_TOL_S, "motion_eps": MOTION_EPS},
        "verifier": "audiogram",
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    """Verify every generated asset for the render capability."""
    params = dict(req.inputs)
    return {"assets": [_verify_asset(Path(path), params, req.piece_dir) for path in req.assets]}


def _asset_name(stem: str) -> str:
    """A stem folded into the record's ``[a-z0-9][a-z0-9-]*`` name shape."""
    name = _BAD_NAME.sub("-", stem.lower()).strip("-")
    return name or "audiogram"


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    """Write ``<asset>.preview.json`` for every asset."""
    req.out_dir.mkdir(parents=True, exist_ok=True)
    params = dict(req.inputs)
    entries = []
    for path in req.assets:
        asset = Path(path)
        props = _probe(asset)
        width = int(props.get("width") or 1)
        height = int(props.get("height") or 1)
        dur = float(props.get("duration_s") or 0.0)
        fps = max(1, round(float(props.get("fps") or params.get("fps", DEFAULT_FPS))))
        length = max(1, round(dur * fps))
        name = _asset_name(str(params.get("name") or asset.stem))
        data = {
            "preview": 1,
            "kind": "video",
            "summary": f"render · {width}x{height} · {dur:.1f}s @ {fps} fps"[:160],
            "name": name,
            "prompt": f"render video {name}",
            "seed": SEED,
            "width": width,
            "height": height,
            "length": length,
            "fps": fps,
        }
        preview_name = f"{asset.name}.preview.json"
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append({"file": asset.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names what fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_imports() -> dict[str, Any]:
    """NumPy, soundfile, Pillow and imageio-ffmpeg import (the runner needs them)."""
    try:
        numpy = _numpy()
        soundfile = _soundfile()
        pil = _pil_image()
        _exe()
    except Exception as exc:
        return _check("imports", False, str(exc), "facet pull audiogram")
    return _check(
        "imports",
        True,
        f"numpy {numpy.__version__}, soundfile {soundfile.__version__}, pillow {pil.__version__}",
    )


def _sine_wav(dest: Path, seconds: float = 1.0) -> None:
    """A 1 s 440 Hz sine with a slow tremolo, so frames visibly react."""
    np = _numpy()
    soundfile = _soundfile()
    rate = SAMPLE_RATE
    times = np.arange(int(seconds * rate)) / rate
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 2 * times)
    tone = (0.5 * envelope * np.sin(2 * np.pi * 440 * times)).astype(np.float32)
    soundfile.write(str(dest), tone, rate)


def _doctor_render() -> dict[str, Any]:
    """A 1 s 440 Hz synthetic sine audiogram renders and verifies (full only)."""
    try:
        with tempfile.TemporaryDirectory(prefix="audiogram-doctor-") as folder:
            tmp = Path(folder)
            wav = tmp / "sine.wav"
            _sine_wav(wav)
            piece = tmp / "piece"
            piece.mkdir()
            (piece / "sine.wav").write_bytes(wav.read_bytes())
            out = tmp / "out"
            out.mkdir()
            params = {"audio": "sine.wav", "name": "doctor", "style": "bars"}
            assets = _render(params, out, piece)
            entry = _verify_asset(out / assets[0]["file"], params, piece)
    except Exception as exc:
        return _check("render", False, str(exc), "facet pull audiogram")
    if not entry["passed"]:
        return _check(
            "render",
            False,
            f"1 s sine audiogram failed verify: {entry['metrics']}",
            "facet pull audiogram",
        )
    return _check("render", True, "1 s 440 Hz sine audiogram verified")


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    """Run quick or full environment checks."""
    checks = [_doctor_imports()]
    if req.depth == "full":
        checks.append(_doctor_render())
    return {"checks": checks}


runner.main()
