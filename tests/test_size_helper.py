"""The shared size helper: an edit or a clip keeps the source's shape.

The cases are the ones the spec names: a portrait, a landscape, a 10:1
extreme that clamps at the manifest's ceiling, one side given, and a pair
whose aspect disagrees with the source's by more than the rounding tolerance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "comfy"))

import size_helper  # noqa: E402

#: The edit flow's own frame: about one megapixel, landscape.
FRAME = (1344, 768)
#: The clip flow's own frame.
CLIP_FRAME = (1280, 704)


def test_a_portrait_source_keeps_its_aspect_at_the_pixel_count() -> None:
    assert size_helper.compute_size((768, 1344), FRAME, (None, None)) == (768, 1344)


def test_a_landscape_source_keeps_its_aspect() -> None:
    assert size_helper.compute_size((1920, 1080), CLIP_FRAME, (None, None)) == (1280, 704)


def test_a_ten_to_one_source_clamps_to_the_ceiling() -> None:
    assert size_helper.compute_size((2000, 200), CLIP_FRAME, (None, None)) == (2048, 192)


def test_one_given_width_derives_the_height() -> None:
    assert size_helper.compute_size((1920, 1080), CLIP_FRAME, (1280, None)) == (1280, 704)


def test_one_given_height_derives_the_width() -> None:
    assert size_helper.compute_size((1920, 1080), CLIP_FRAME, (None, 704)) == (1280, 704)


def test_a_pair_matching_the_source_is_used_as_given() -> None:
    assert size_helper.compute_size((1344, 768), FRAME, (1344, 768)) == (1344, 768)


def test_a_pair_within_the_rounding_tolerance_is_used_as_given() -> None:
    # 1280x736 is 0.6 % off the source's 1.75: rounding to 64 allows that much.
    assert size_helper.compute_size((1344, 768), FRAME, (1280, 736)) == (1280, 736)


def test_a_pair_off_the_source_aspect_is_refused_with_the_computed_size() -> None:
    with pytest.raises(ValueError, match=r"aspect mismatch; computed 768x1344; crop source first"):
        size_helper.compute_size((768, 1344), FRAME, (1344, 768))


def test_the_shipped_clip_shape_passes_its_still_source() -> None:
    """The registry's own clip examples give 1280x704 over a 1344x768 still."""
    assert size_helper.compute_size((1344, 768), CLIP_FRAME, (1280, 704)) == (1280, 704)


def test_a_tall_extreme_clamps_the_height_and_recomputes_the_width() -> None:
    assert size_helper.compute_size((200, 2000), FRAME, (None, None)) == (192, 2048)


def test_one_given_side_is_kept_when_the_other_clamps() -> None:
    assert size_helper.compute_size((200, 2000), FRAME, (None, 768)) == (64, 768)
