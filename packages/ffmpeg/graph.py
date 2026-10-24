"""Pure FFmpeg command building for the ffmpeg package: arguments, filtergraphs, parsing.

stdlib only, no imports from the package environment: the runner wires
these functions to the bundled static binary and to ``audiopreview``, and
``tests/test_ffmpeg_graph.py`` asserts the exact strings on fixed inputs.
Every number that reaches an argument goes through ``:g`` so a command
reads the same everywhere.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

#: The encoder behind each ``format`` value of ``convert``; the enum is exactly
#: those whose encoder appears in the bundled build's ``-encoders``.
CODECS: Final[dict[str, str]] = {
    "wav": "pcm_s16le",
    "flac": "flac",
    "mp3": "libmp3lame",
    "ogg": "libopus",
}
#: Formats whose encoder spends bits; they take ``-b:a``.
LOSSY: Final[frozenset[str]] = frozenset({"mp3", "ogg"})
#: alimiter's ceiling: -1 dBFS in linear, so a mix peak stays at or below it.
LIMIT: Final[float] = 0.891251
#: loudnorm's second pass always fixes the loudness range at this.
LOUDNORM_LRA: Final[float] = 11.0
#: One ``"key" : "value",`` line inside loudnorm's JSON report.
_JSON_LINE: Final[re.Pattern[str]] = re.compile(r'^\s*"([^"]+)"\s*:\s*"([^"]*)",?\s*$')
#: One ``ffmpeg -encoders`` listing line: six flag characters, then the name.
_ENCODER_LINE: Final[re.Pattern[str]] = re.compile(r"^\s*[A-Z.]{6}\s+(\S+)")


def num(value: float) -> str:
    """A number for an ffmpeg argument, in the shortest exact form."""
    return f"{value:g}"


def loudnorm_json(stderr: str) -> dict[str, float]:
    """The last ``{...}`` block of loudnorm's ``print_format=json`` report, floats only."""
    end = stderr.rfind("}")
    start = stderr.rfind("{", 0, end) if end != -1 else -1
    if end == -1 or start == -1:
        raise ValueError("loudnorm printed no JSON block in its stderr")
    measured: dict[str, float] = {}
    for line in stderr[start + 1 : end].splitlines():
        match = _JSON_LINE.match(line)
        if match is None:
            continue
        key, raw = match.groups()
        try:
            measured[key] = float(raw)
        except ValueError:
            continue  # normalization_type and friends stay out
    return measured


def measure_args(input: Path, output: Path) -> list[str]:
    """Decode any input to a 32-bit float WAV the measurements can read (no ffprobe)."""
    return ["-i", str(input), "-acodec", "pcm_f32le", "-f", "wav", str(output)]


def normalize_args(
    input: Path,
    output: Path,
    target_lufs: float,
    true_peak_db: float,
    measured: Mapping[str, float],
    sample_rate_hz: int,
) -> list[str]:
    """Pass 2: loudnorm with pass 1's measured values (linear), resampled, to a WAV.

    The trailing alimiter is the true-peak ceiling the verify rule measures:
    loudnorm's own estimate lets about a quarter of a dB through when its
    192 kHz stream is decimated to the output rate, and the spec keeps the
    decoded peak at or below ``true_peak_db`` + 0.1.
    """
    chain = (
        f"loudnorm=I={num(target_lufs)}:TP={num(true_peak_db)}:LRA={num(LOUDNORM_LRA)}"
        f":measured_I={num(measured['input_i'])}"
        f":measured_TP={num(measured['input_tp'])}"
        f":measured_LRA={num(measured['input_lra'])}"
        f":measured_thresh={num(measured['input_thresh'])}"
        f":offset={num(measured['target_offset'])}"
        ":linear=true:print_format=summary"
        f",aresample={int(sample_rate_hz)}"
        f",alimiter=limit={num(10 ** (true_peak_db / 20))}:level=false"
    )
    return ["-i", str(input), "-af", chain, str(output)]


def measure_chain(target_lufs: float, true_peak_db: float) -> str:
    """Pass 1's loudnorm: measure this input and print its JSON report on stderr."""
    return (
        f"loudnorm=I={num(target_lufs)}:TP={num(true_peak_db)}:LRA={num(LOUDNORM_LRA)}"
        ":print_format=json"
    )


def mix_filtergraph(layers: Sequence[Mapping[str, object]], ducking: bool, duck_db: float) -> str:
    """One filtergraph: layers delayed and scaled, voices summed, beds ducked, alimited.

    A piece without a voice is legal (a bed alone, or several beds), so
    the beds form the mix directly: an ``amix`` with no voice sum to key
    on would be ``amix=inputs=0``, which ffmpeg rejects.
    """
    steps = [_layer_step(index, layer) for index, layer in enumerate(layers)]
    voices = [index for index, layer in enumerate(layers) if str(layer["role"]) == "voice"]
    beds = [index for index, layer in enumerate(layers) if str(layer["role"]) != "voice"]
    if not voices:
        steps.append(_sum_step(beds, "mix"))
        steps.append(f"[mix]alimiter=limit={num(LIMIT)}[out]")
        return ";".join(steps)
    steps.append(_sum_step(voices, "vsum"))
    if not beds:
        steps.append(f"[vsum]alimiter=limit={num(LIMIT)}[out]")
        return ";".join(steps)
    steps.append(_sum_step(beds, "bsum"))
    if ducking:
        steps.extend(_duck_steps(duck_db))
    else:
        steps.append("[vsum][bsum]amix=inputs=2:normalize=0[mix]")
    steps.append(f"[mix]alimiter=limit={num(LIMIT)}[out]")
    return ";".join(steps)


def _layer_step(index: int, layer: Mapping[str, object]) -> str:
    """One layer: aformat to 48 kHz stereo, delayed by start_s, scaled by gain_db."""
    delay_ms = int(round(float(layer.get("start_s", 0.0)) * 1000))
    delay = f"{num(delay_ms)}|{num(delay_ms)}"
    gain = num(float(layer.get("gain_db", 0.0)))
    head = f"[{index}:a]aformat=sample_rates=48000:channel_layouts=stereo"
    return f"{head},adelay={delay},volume={gain}dB[l{index}]"


def _sum_step(indices: Sequence[int], label: str) -> str:
    """Sum the given layer outputs; a single layer passes through with anull."""
    if len(indices) == 1:
        return f"[l{indices[0]}]anull[{label}]"
    inputs = "".join(f"[l{index}]" for index in indices)
    return f"{inputs}amix=inputs={len(indices)}:normalize=0[{label}]"


def _duck_steps(duck_db: float) -> list[str]:
    """The bed ducked under the voice: sidechaincompress keyed on the padded voice sum.

    The ``apad`` is mandatory: sidechaincompress stops when its key stops, so
    a padded key is what lets a short voice hold a long bed down to the end.
    """
    ratio = num(duck_ratio(duck_db))
    compressor = (
        "[bsum][vkeyp]sidechaincompress=threshold=0.001"
        f":ratio={ratio}:attack=20:release=300:makeup=1[bduck]"
    )
    return [
        "[vsum]asplit=2[vout][vkey]",
        "[vkey]apad[vkeyp]",
        compressor,
        "[vout][bduck]amix=inputs=2:normalize=0[mix]",
    ]


def duck_ratio(duck_db: float) -> float:
    """The sidechain ratio whose compression drop is about ``duck_db`` when keyed."""
    return 1.0 / (1.0 - abs(duck_db) / 44.0)


def mix_args(filtergraph: str, inputs: Sequence[Path], output: Path) -> list[str]:
    """The mix call: one ``-i`` per layer in piece order, the graph, ``[out]`` mapped."""
    args: list[str] = []
    for path in inputs:
        args.extend(["-i", str(path)])
    args.extend(["-filter_complex", filtergraph, "-map", "[out]", str(output)])
    return args


def convert_args(
    input: Path,
    output: Path,
    fmt: str,
    cut: tuple[float | None, float | None] = (None, None),
    sample_rate_hz: int | None = None,
    channels: int | None = None,
    bitrate_kbps: int = 128,
) -> list[str]:
    """The convert call: cut, resample, channel count, the format's encoder and bitrate."""
    try:
        codec = CODECS[fmt]
    except KeyError:
        known = ", ".join(sorted(CODECS))
        raise ValueError(f"unknown format {fmt!r} (known: {known})") from None
    args = ["-i", str(input)]
    start_s, end_s = cut
    if start_s is not None:
        args.extend(["-ss", num(start_s)])
    if end_s is not None:
        args.extend(["-to", num(end_s)])
    if sample_rate_hz is not None:
        args.extend(["-ar", num(sample_rate_hz)])
    if channels is not None:
        args.extend(["-ac", num(channels)])
    args.extend(["-c:a", codec])
    if fmt in LOSSY:
        args.extend(["-b:a", f"{int(bitrate_kbps)}k"])
    args.append(str(output))
    return args


def version_line(text: str) -> str:
    """The first line of ``ffmpeg -version``: the version line every record carries."""
    lines = text.splitlines()
    return lines[0].strip() if lines else ""


def version_id(text: str) -> str:
    """The build token after ``ffmpeg version``, e.g. ``7.0.2-static``."""
    rest = version_line(text).partition("ffmpeg version")[2]
    return rest.split()[0] if rest.strip() else ""


def encoder_names(text: str) -> set[str]:
    """The encoder names ``ffmpeg -encoders`` lists (its six-flag column first)."""
    names: set[str] = set()
    for line in text.splitlines():
        match = _ENCODER_LINE.match(line)
        if match is not None and match.group(1) != "=":
            names.add(match.group(1))
    return names
