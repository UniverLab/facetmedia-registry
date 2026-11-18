"""Output size from a source image and a flow's default frame."""

from __future__ import annotations

import math

ASPECT_TOLERANCE = 0.05


def _r64(x: float) -> int:
    return max(64, round(x / 64) * 64)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def compute_size(
    source: tuple[int, int],
    flow: tuple[int, int],
    given: tuple[int | None, int | None],
    lo: int = 64,
    hi: int = 2048,
) -> tuple[int, int]:
    """Return (width, height) rounded to 64, derived from the source aspect."""
    sw, sh = source
    fw, fh = flow
    gw, gh = given
    aspect = sw / sh
    if gw is None and gh is None:
        pixels = fw * fh
        width = _r64(math.sqrt(pixels * aspect))
        height = _r64(pixels / width)
        if width < lo or width > hi:
            width = _clamp(width, lo, hi)
            height = _r64(width / aspect)
        if height < lo or height > hi:
            height = _clamp(height, lo, hi)
            width = _clamp(_r64(height * aspect), lo, hi)
        return width, height
    if gw is None:
        assert gh is not None
        height = _clamp(gh, lo, hi)
        return _clamp(_r64(height * aspect), lo, hi), height
    if gh is None:
        width = _clamp(gw, lo, hi)
        return width, _clamp(_r64(width / aspect), lo, hi)
    if abs(gw / gh - aspect) / aspect > ASPECT_TOLERANCE:
        cw, ch = compute_size(source, flow, (None, None), lo, hi)
        raise ValueError(
            f"aspect mismatch; computed {cw}x{ch}; crop source first (e.g. with pillow)"
        )
    return gw, gh
