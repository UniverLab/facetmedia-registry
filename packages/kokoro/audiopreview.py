"""Audio measurement and loudness for the audio preview.

The runner keeps every pure-text function in ``textnorm``; this module is
the signal side: loudness normalisation (ITU-R BS.1770 through pyloudnorm),
the preview's waveform, momentary curve, silences and clipped samples.
numpy, pyloudnorm and soundfile come from the package environment.

Packages run in separate environments, so kokoro and ffmpeg each carry a
byte-identical copy of this module; ``tests/test_audiopreview_copies.py``
keeps the copies from drifting.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy
import pyloudnorm as pyln
import soundfile

#: Normalisation never pushes the sample peak past this.
PEAK_CAP_DBFS = -1.0
#: Waveform bins the audio preview schema fixes.
WAVEFORM_BINS = 1200
#: Momentary loudness window and step, both fixed by the schema.
MOMENTARY_WINDOW_S = 0.4
MOMENTARY_STEP_S = 0.1
#: Windows at or below this loudness are reported as ``null``.
MOMENTARY_FLOOR_LUFS = -70.0
#: Silence is a stretch of frames at or below this level…
SILENCE_FLOOR_DBFS = -50.0
#: …of at least this long to be worth reporting.
SILENCE_MIN_S = 1.0
#: Frame grid for the silence scan.
SILENCE_FRAME_S = 0.01
#: Samples at or above this level count as clipped.
CLIP_FLOOR_DBFS = -0.1
LINEAR_CLIP_FLOOR = 10 ** (CLIP_FLOOR_DBFS / 20)
#: Floor for log-amplitude on digital silence, so JSON stays finite.
_SILENCE_DBFS = -160.0


def read_wav(path: Path) -> tuple[numpy.ndarray, int]:
    """The clip as float64 in [-1, 1] (mono, or (samples, channels)) and its rate."""
    data, rate = soundfile.read(str(path), dtype="float64")
    return data, int(rate)


def write_wav(path: Path, samples: numpy.ndarray, rate: int) -> None:
    """Write PCM 16-bit at ``rate``; Kokoro's own rate is 24 kHz."""
    soundfile.write(str(path), samples, rate, subtype="PCM_16")


def integrated_lufs(samples: numpy.ndarray, rate: int) -> float:
    """Integrated loudness (BS.1770) on the raw signal; pads short audio to one 400 ms block."""
    window = int(MOMENTARY_WINDOW_S * rate)
    data = samples if len(samples) >= window else _pad(samples, window)
    try:
        value = pyln.Meter(rate).integrated_loudness(data)
    except (ValueError, ZeroDivisionError):
        return MOMENTARY_FLOOR_LUFS - 10.0
    return float(value) if math.isfinite(value) else MOMENTARY_FLOOR_LUFS - 10.0


def peak_dbfs(samples: numpy.ndarray) -> float:
    """Sample peak in dBFS; digital silence reports the JSON-safe floor."""
    peak = float(numpy.max(numpy.abs(samples))) if len(samples) else 0.0
    if peak <= 0.0:
        return _SILENCE_DBFS
    return max(20.0 * math.log10(peak), _SILENCE_DBFS)


def normalize(samples: numpy.ndarray, rate: int, target_lufs: float) -> numpy.ndarray:
    """Gain to ``target_lufs``, capped so the peak stays at or below -1.0 dBFS."""
    measured = integrated_lufs(samples, rate)
    gain_db = target_lufs - measured
    headroom_db = PEAK_CAP_DBFS - peak_dbfs(samples)
    applied = min(gain_db, headroom_db)
    return samples * (10.0 ** (applied / 20.0))


def duration_s(samples: numpy.ndarray, rate: int) -> float:
    return len(samples) / rate if rate else 0.0


def channels(samples: numpy.ndarray) -> int:
    """1 for mono, else the second axis' width."""
    return 1 if samples.ndim == 1 else int(samples.shape[1])


def waveform(samples: numpy.ndarray) -> dict[str, Any]:
    """Per-bin min and max peaks over exactly ``WAVEFORM_BINS`` bins, from the channel mean."""
    samples = _mono(samples)
    count = len(samples)
    if count == 0:
        return {"bins": WAVEFORM_BINS, "min": [0.0] * WAVEFORM_BINS, "max": [0.0] * WAVEFORM_BINS}
    mins: list[float] = []
    maxs: list[float] = []
    for index in range(WAVEFORM_BINS):
        start = index * count // WAVEFORM_BINS
        end = max((index + 1) * count // WAVEFORM_BINS, start + 1)
        # More bins than samples: repeat the last one.
        chunk = samples[count - 1 : count] if start >= count else samples[start:end]
        mins.append(round(float(numpy.min(chunk)), 6))
        maxs.append(round(float(numpy.max(chunk)), 6))
    return {"bins": WAVEFORM_BINS, "min": mins, "max": maxs}


def momentary(samples: numpy.ndarray, rate: int) -> list[float | None]:
    """Momentary loudness: 400 ms windows every 100 ms, null below -70 LUFS."""
    samples = _mono(samples)
    window = int(MOMENTARY_WINDOW_S * rate)
    step = int(MOMENTARY_STEP_S * rate)
    meter = pyln.Meter(rate)
    curve: list[float | None] = []
    for start in range(0, len(samples), step):
        chunk = _pad(samples[start : start + window], window)
        try:
            value = meter.integrated_loudness(chunk)
        except (ValueError, ZeroDivisionError):
            value = MOMENTARY_FLOOR_LUFS - 10.0
        if not math.isfinite(value) or value <= MOMENTARY_FLOOR_LUFS:
            curve.append(None)
        else:
            curve.append(round(float(value), 2))
    return curve


def silences(samples: numpy.ndarray, rate: int) -> list[dict[str, float]]:
    """Stretches longer than 1 s whose 10 ms peak stays below -50 dBFS."""
    samples = _mono(samples)
    frame = max(int(SILENCE_FRAME_S * rate), 1)
    threshold = 10 ** (SILENCE_FLOOR_DBFS / 20)
    quiet = _quiet_frames(samples, frame, threshold)
    stretches: list[dict[str, float]] = []
    start: int | None = None
    for index, is_quiet in enumerate(quiet + [False]):
        if is_quiet and start is None:
            start = index
        elif not is_quiet and start is not None:
            stretches.extend(_silence_stretch(samples, rate, frame, start, index))
            start = None
    return stretches


def _mono(samples: numpy.ndarray) -> numpy.ndarray:
    """One waveform: the channel mean, identity for mono."""
    if samples.ndim == 1:
        return samples
    return samples.mean(axis=1)


def _quiet_frames(samples: numpy.ndarray, frame: int, threshold: float) -> list[bool]:
    """One flag per frame: whether its peak sits at or below ``threshold``."""
    flags: list[bool] = []
    for start in range(0, len(samples) - frame + 1, frame):
        peak = float(numpy.max(numpy.abs(samples[start : start + frame])))
        flags.append(peak <= threshold)
    return flags


def _silence_stretch(
    samples: numpy.ndarray, rate: int, frame: int, start: int, end: int
) -> list[dict[str, float]]:
    """One quiet run as data when it lasts longer than the reporting floor."""
    start_s = round(start * frame / rate, 3)
    end_s = round(min(end * frame, len(samples)) / rate, 3)
    if end_s - start_s <= SILENCE_MIN_S:
        return []
    return [{"start_s": start_s, "end_s": end_s}]


def clipped_samples(samples: numpy.ndarray) -> int:
    """How many samples sit at or above -0.1 dBFS."""
    return int(numpy.count_nonzero(numpy.abs(samples) >= LINEAR_CLIP_FLOOR))


def _pad(chunk: numpy.ndarray, size: int) -> numpy.ndarray:
    """Zero-pad ``chunk`` (or cut it) to exactly ``size`` samples, along the sample axis only."""
    if len(chunk) >= size:
        return chunk[:size]
    pad = ((0, size - len(chunk)),) + ((0, 0),) * (chunk.ndim - 1)
    return numpy.pad(chunk, pad)
