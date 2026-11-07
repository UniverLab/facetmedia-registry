"""The profile side of the voicestudio runner: a local clone from a reference WAV.

A profile is made from the person's own recording, with their permission:
7-30 s of neutral speech, taken from the lab's ``guion-grabacion.md``. A
questioning or exclamatory start contaminates the clone with a sharp attack
and skips the first sentences, so the runner refuses a take outside that
window instead of posting it.

Two measurement traps the runners settles here:

- a stereo WAV captured by a laptop may carry the voice on one channel and
  silence on the other (Audacity's default device, silent in mono): the one
  live channel is kept and the repair is reported;
- the reference is taken to -20 LUFS, as the approved jheison reference was
  (a 14.8 s exposition block), with the sample peak capped at -1 dBFS.

Nothing is written here. The bytes are posted to the backend, which persists
the audio under its own app-data ``VOICES_DIR``; the runner keeps only a
receipt beside the piece.
"""

from __future__ import annotations

import importlib
import io
import json
import math
import urllib.error
import urllib.request
import uuid
import wave
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

#: The lab recipe's accepted reference window, in seconds.
MIN_DURATION_S: Final[float] = 7.0
MAX_DURATION_S: Final[float] = 30.0
#: The loudness the approved reference was taken to.
TARGET_LUFS: Final[float] = -20.0
#: Normalisation never pushes the sample peak past this.
PEAK_CAP_DBFS: Final[float] = -1.0
#: A channel quieter than this counts as empty (digital silence).
EMPTY_CHANNEL_PEAK: Final[float] = 1e-6
#: JSON-safe floor for a peak measured on digital silence.
SILENCE_DBFS: Final[float] = -160.0
#: Endpoint and multipart field the backend expects (ref_audio, not ref-audio).
PROFILES_PATH: Final[str] = "/profiles"
REF_FIELD: Final[str] = "ref_audio"
#: A clone save transcribes the reference server-side; generous, but bounded.
PROFILE_TIMEOUT_S: Final[float] = 300.0


def validate_ref(path: Path) -> tuple[bytes, list[str]]:
    """The reference as 16-bit mono WAV bytes at -20 LUFS, plus repairs made."""
    samples, rate = _read_reference(path)
    _check_duration(len(samples) / rate, path.name)
    mono, repairs = _channel_choice(samples, path.name)
    normalised = _normalise(mono, rate, path.name)
    return _pcm16(normalised, rate), repairs


def post_profile(
    base_url: str,
    name: str,
    audio: bytes,
    *,
    instruct: str = "",
    language: str = "es",
) -> dict[str, Any]:
    """POST one clone profile; the backend's record (with its id) comes back."""
    clean = name.strip()
    if not clean:
        raise RuntimeError("A voice profile needs a name.")
    fields = {
        "name": clean,
        "kind": "clone",
        "language": language,
        "instruct": instruct,
        "ref_text": "",
    }
    body, content_type = _multipart(fields, "reference.wav", audio)
    request = urllib.request.Request(
        f"{base_url}{PROFILES_PATH}",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=PROFILE_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"POST {PROFILES_PATH} answered {exc.code}: {detail}") from None
    except OSError as exc:
        raise RuntimeError(f"no VoiceStudio backend at {base_url}: {exc}") from None
    except ValueError as exc:
        raise RuntimeError(f"POST {PROFILES_PATH} answered no JSON: {exc}") from None
    if not isinstance(payload, dict) or not payload.get("id"):
        raise RuntimeError(f"POST {PROFILES_PATH} answered no profile record")
    return payload


def _read_reference(path: Path) -> tuple[Any, int]:
    """The WAV decoded to float64 in [-1, 1], flat for mono, else (frames, channels)."""
    try:
        with wave.open(str(path), "rb") as reader:
            channels = reader.getnchannels()
            width = reader.getsampwidth()
            rate = reader.getframerate()
            count = reader.getnframes()
            frames = reader.readframes(count)
    except wave.Error as exc:
        raise ValueError(f"{path.name}: not a readable WAV ({exc})") from None
    if rate <= 0 or count <= 0 or not frames:
        raise ValueError(f"{path.name}: the reference has no audio")
    values = _decode(frames, width, path.name)
    if channels > 1:
        return values.reshape(-1, channels), rate
    return values, rate


def _decode(frames: bytes, width: int, name: str) -> Any:
    """PCM integer frames as floats in [-1, 1], whatever the sample width."""
    decoder = _DECODERS.get(width)
    if decoder is None:
        raise ValueError(f"{name}: unsupported sample width: {width * 8} bits")
    return decoder(frames)


def _decode_u8(frames: bytes) -> Any:
    numpy = importlib.import_module("numpy")
    values = numpy.frombuffer(frames, dtype=numpy.uint8).astype(numpy.float64) - 128.0
    return values / 128.0


def _decode_i16(frames: bytes) -> Any:
    numpy = importlib.import_module("numpy")
    return numpy.frombuffer(frames, dtype="<i2").astype(numpy.float64) / 32768.0


def _decode_i24(frames: bytes) -> Any:
    numpy = importlib.import_module("numpy")
    raw = numpy.frombuffer(frames, dtype=numpy.uint8).reshape(-1, 3)
    values = (
        raw[:, 0].astype(numpy.int32)
        | (raw[:, 1].astype(numpy.int32) << 8)
        | (raw[:, 2].astype(numpy.int32) << 16)
    )
    signed = numpy.where(values >= 1 << 23, values - (1 << 24), values)
    return signed.astype(numpy.float64) / float(1 << 23)


def _decode_i32(frames: bytes) -> Any:
    numpy = importlib.import_module("numpy")
    return numpy.frombuffer(frames, dtype="<i4").astype(numpy.float64) / float(1 << 31)


#: One decoder per WAV sample width in bytes (8, 16, 24 and 32-bit PCM).
_DECODERS: dict[int, Any] = {1: _decode_u8, 2: _decode_i16, 3: _decode_i24, 4: _decode_i32}


def _check_duration(seconds: float, name: str) -> None:
    """7-30 s of neutral speech: anything else is refused before the POST."""
    if MIN_DURATION_S <= seconds <= MAX_DURATION_S:
        return
    raise ValueError(
        f"{name}: the reference is {seconds:.1f} s; a clone needs "
        f"{MIN_DURATION_S:.0f}-{MAX_DURATION_S:.0f} s of neutral speech"
    )


def _channel_choice(samples: Any, name: str) -> tuple[Any, list[str]]:
    """One channel, repairing a stereo take whose other channel is silent."""
    numpy = importlib.import_module("numpy")
    if samples.ndim == 1:
        return samples, []
    peaks = numpy.max(numpy.abs(samples), axis=0)
    live = numpy.flatnonzero(peaks > EMPTY_CHANNEL_PEAK)
    if live.size == 0:
        raise ValueError(f"{name}: every channel is silent")
    if live.size == 1 and samples.shape[1] > 1:
        channel = int(live[0])
        label = f"channel {channel + 1}" if channel > 1 else ("left", "right")[channel]
        repair = f"kept the {label} channel; the other channel is silent"
        return samples[:, channel], [repair]
    return samples.mean(axis=1), []


def _normalise(samples: Any, rate: int, name: str) -> Any:
    """Gain the reference to -20 LUFS, capped so the peak stays at -1 dBFS."""
    measured = _integrated_lufs(samples, rate, name)
    gain_db = TARGET_LUFS - measured
    headroom_db = PEAK_CAP_DBFS - _peak_dbfs(samples)
    return samples * (10.0 ** (min(gain_db, headroom_db) / 20.0))


def _integrated_lufs(samples: Any, rate: int, name: str) -> float:
    """ITU-R BS.1770 integrated loudness through pyloudnorm."""
    pyloudnorm = importlib.import_module("pyloudnorm")
    try:
        value = float(pyloudnorm.Meter(rate).integrated_loudness(samples))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{name}: cannot measure the reference loudness ({exc})") from None
    if not math.isfinite(value):
        raise ValueError(f"{name}: cannot measure the reference loudness (silence)")
    return value


def _peak_dbfs(samples: Any) -> float:
    """The sample peak in dBFS; digital silence reports the JSON-safe floor."""
    numpy = importlib.import_module("numpy")
    peak = float(numpy.max(numpy.abs(samples))) if len(samples) else 0.0
    if peak <= 0.0:
        return SILENCE_DBFS
    return max(20.0 * math.log10(peak), SILENCE_DBFS)


def _pcm16(samples: Any, rate: int) -> bytes:
    """The normalised mono signal as a 16-bit PCM WAV in memory."""
    numpy = importlib.import_module("numpy")
    pcm = numpy.clip(numpy.round(samples * 32767.0), -32768.0, 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _multipart(fields: Mapping[str, str], filename: str, audio: bytes) -> tuple[bytes, str]:
    """One ``multipart/form-data`` body: the scalar fields then the WAV part."""
    boundary = f"----facet{uuid.uuid4().hex}"
    parts = [
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
        ).encode()
        for key, value in fields.items()
    ]
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{REF_FIELD}"; '
            f'filename="{filename}"\r\nContent-Type: audio/wav\r\n\r\n'
        ).encode()
    )
    parts.append(audio)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
