"""Tests for the cad package's pure helpers and its STEP verify logic (no kernel).

``occlab`` keeps every heavy import inside a function, so its parsers and
its hole dedup key import without CadQuery; ``runner`` imports with a stub
``facet_runner_sdk`` (the real one is copied into the environment at pull).
The STEP verify logic runs against a stubbed measurement: it pins the
``expect-bbox-mm`` shape the core actually delivers — one ``{x, y, z}``
item, because the manifest's schema language only describes arrays as
lists of objects — and the volume tolerance maths from the spec's own
examples (20 805 vs 20 805.514 451 passes at 0.1 %; 30 000 fails).
"""

from __future__ import annotations

import importlib.util
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


occlab = _load("occlab", "packages/cad/occlab.py")


def _stub_sdk() -> None:
    """The pull-time SDK surface the runner touches at import: nothing real."""
    sdk = types.ModuleType("facet_runner_sdk")

    class _Runner:
        def verb(self, _name: str):
            return lambda function: function

        def main(self) -> None:
            return None

    sdk.Runner = _Runner  # type: ignore[attr-defined]
    sdk.Request = object  # type: ignore[attr-defined]
    sys.modules["facet_runner_sdk"] = sdk


_stub_sdk()
runner = _load("cad_runner", "packages/cad/runner.py")

#: The spec's own measurements of the lab's escuadra.
ESCUEADRA_MEASURED = {
    "volume_mm3": 20805.514451,
    "bbox_mm": [60.0, 40.0, 50.0],
    "faces": 11,
    "solids": 1,
    "holes": [],
}
ESCUEADRA_SHAPE = types.SimpleNamespace(isValid=lambda: True)


def _verify_step(params: dict, path: Path = Path("escuadra.step")) -> dict:
    with (
        mock.patch.object(occlab, "import_step", return_value=ESCUEADRA_SHAPE),
        mock.patch.object(occlab, "measure", return_value=ESCUEADRA_MEASURED),
    ):
        return runner._verify_step(params, path)


def test_expected_bbox_reads_the_core_shape() -> None:
    """The validated piece carries one {x, y, z} item, never flat numbers."""
    assert runner._expected_bbox([{"x": 60, "y": 40, "z": 50}]) == (60.0, 40.0, 50.0)


@pytest.mark.parametrize(
    "value",
    [
        [60, 40, 50],  # the flat shape the core refuses
        [],  # no item at all
        [{"x": 60, "y": 40}],  # z missing
        [{"x": "wide", "y": 40, "z": 50}],  # not a number
        [{"x": 60, "y": 40, "z": 50}, {"x": 1, "y": 1, "z": 1}],  # two items
        "60x40x50",
    ],
)
def test_expected_bbox_rejects_anything_else(value) -> None:
    assert runner._expected_bbox(value) is None


def test_verify_step_passes_volume_and_bbox() -> None:
    """The lab's escuadra inside 0.1 % and its measured bbox: a pass."""
    verdict = _verify_step(
        {
            "expect-volume-mm3": 20805,
            "volume-rel-tol": 0.001,
            "expect-bbox-mm": [{"x": 60, "y": 40, "z": 50}],
            "bbox-abs-tol-mm": 0.01,
        }
    )
    assert verdict["passed"] is True
    assert verdict["metrics"]["volume_diff_rel"] == pytest.approx(2.5e-05)
    assert verdict["metrics"]["bbox_diff_mm"] == [0.0, 0.0, 0.0]
    assert verdict["thresholds"] == {"volume_rel_tol": 0.001, "bbox_abs_tol_mm": 0.01}


def test_verify_step_fails_the_off_volume() -> None:
    """expect-volume-mm3 = 30000 fails with the spec's relative difference."""
    verdict = _verify_step({"expect-volume-mm3": 30000, "volume-rel-tol": 0.001})
    assert verdict["passed"] is False
    assert verdict["metrics"]["volume_diff_rel"] == pytest.approx(0.306483, abs=1e-6)


def test_verify_step_fails_a_bbox_side_out_of_tolerance() -> None:
    """One side 0.5 mm long fails at bbox-abs-tol-mm = 0.01."""
    verdict = _verify_step({"expect-bbox-mm": [{"x": 60.5, "y": 40, "z": 50}]})
    assert verdict["passed"] is False
    assert verdict["metrics"]["bbox_diff_mm"] == [0.5, 0.0, 0.0]


def test_verify_step_fails_a_flat_bbox_without_crashing() -> None:
    """A flat [x, y, z] can never reach the runner through the core; if it
    ever does, verify fails with the reason instead of raising."""
    verdict = _verify_step({"expect-bbox-mm": [60, 40, 50]})
    assert verdict["passed"] is False
    assert verdict["metrics"]["error"] == "expect-bbox-mm must be one {x, y, z} item"


def test_verify_step_fails_a_non_positive_expectation() -> None:
    """expect-volume-mm3 = 0 is a failed verdict, never a division by zero."""
    verdict = _verify_step({"expect-volume-mm3": 0})
    assert verdict["passed"] is False
    assert verdict["metrics"]["error"] == "expect-volume-mm3 must be positive"


def test_solid_summary_reads_like_the_spec() -> None:
    """``escuadra · valid · 20 806 mm³ · 2 holes Ø6.5``, and invalid when it is."""
    holes = [
        {"center_mm": [45, 20, 2.5], "diameter_mm": 6.5, "axis": [0, 0, 1]},
        {"center_mm": [2.5, 20, 35], "diameter_mm": 6.5, "axis": [1, 0, 0]},
    ]
    fields = {**ESCUEADRA_MEASURED, "valid": True, "holes": holes}
    assert (
        runner._solid_summary("escuadra", fields) == "escuadra · valid · 20 806 mm³ · 2 holes Ø6.5"
    )
    assert runner._solid_summary("escuadra", {**fields, "valid": False}).startswith(
        "escuadra · invalid"
    )


def test_stl_triangles_counts_a_binary_file(tmp_path: Path) -> None:
    """A well-formed binary STL reports its header's triangle count."""
    expected = 2
    path = tmp_path / "part.stl"
    path.write_bytes(
        b"binary" + b"\0" * 74 + expected.to_bytes(4, "little") + b"\0" * (50 * expected)
    )
    assert occlab.stl_triangles(path) == expected


def test_stl_triangles_counts_an_ascii_file(tmp_path: Path) -> None:
    expected = 2
    facets = "\n".join("facet normal 0 0 1\nendfacet" for _ in range(expected))
    path = tmp_path / "part.stl"
    path.write_text(f"solid part\n{facets}\n")
    assert occlab.stl_triangles(path) == expected


def test_stl_triangles_is_zero_for_garbage(tmp_path: Path) -> None:
    path = tmp_path / "part.stl"
    path.write_bytes(b"not an stl at all")
    assert occlab.stl_triangles(path) == 0


def test_svg_ok_accepts_an_svg_root(tmp_path: Path) -> None:
    path = tmp_path / "view.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    assert occlab.svg_ok(path) is True


def test_svg_ok_rejects_another_root(tmp_path: Path) -> None:
    path = tmp_path / "view.svg"
    path.write_text("<html></html>")
    assert occlab.svg_ok(path) is False


def test_verify_svg_reports_broken_xml(tmp_path: Path) -> None:
    """A view that does not parse is a failed verdict, not a crash."""
    path = tmp_path / "view.svg"
    path.write_text("definitely not xml")
    with pytest.raises(ET.ParseError):
        occlab.svg_ok(path)
    verdict = runner._verify_svg(path)
    assert verdict["passed"] is False
    assert "error" in verdict["metrics"]


def test_hole_key_ignores_the_axis_sign() -> None:
    """The two faces of one hole share a key whichever way the axis points."""
    down = {"center_mm": [45, 20, 2.5], "diameter_mm": 6.5, "axis": [0, 0, -1]}
    up = {"center_mm": [45, 20, 2.5], "diameter_mm": 6.5, "axis": [0, 0, 1]}
    other = {"center_mm": [2.5, 20, 35], "diameter_mm": 6.5, "axis": [1, 0, 0]}
    assert occlab._key(down) == occlab._key(up)
    assert occlab._key(other) != occlab._key(up)
