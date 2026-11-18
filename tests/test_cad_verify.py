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

import contextlib
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
    assert verdict["thresholds"] == {
        "expect_solids": 1,
        "volume_rel_tol": 0.001,
        "bbox_abs_tol_mm": 0.01,
    }


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


def _run_solid(tmp_path: Path, writes: tuple[str, ...]) -> list[dict]:
    """Run the solid runner against a stub script that writes the named files."""
    writes_lines = "\n".join(
        f'(out.with_suffix(".{extension}")).write_bytes(b"x")' for extension in writes
    )
    script = tmp_path / "piece.py"
    script.write_text(
        "import sys\nfrom pathlib import Path\nout = Path(sys.argv[1])\n" + writes_lines + "\n"
    )
    req = types.SimpleNamespace(
        out_dir=tmp_path,
        capability="cad.solid",
        inputs={"script": str(script), "name": "escuadra"},
    )
    with (
        mock.patch.object(occlab, "import_step", return_value=ESCUEADRA_SHAPE),
        mock.patch.object(occlab, "measure", return_value=ESCUEADRA_MEASURED),
        mock.patch.object(
            occlab, "export_stl", side_effect=lambda shape, path: Path(path).write_bytes(b"x")
        ),
        mock.patch.object(
            occlab, "export_svg", side_effect=lambda shape, path: Path(path).write_bytes(b"x")
        ),
    ):
        return runner._run_solid(req, dict(req.inputs))["assets"]


def test_solid_keeps_the_glb_the_script_wrote(tmp_path: Path) -> None:
    """A script that writes step/stl/svg/glb yields four assets, the glb last."""
    assets = _run_solid(tmp_path, ("step", "stl", "svg", "glb"))
    assert [asset["file"] for asset in assets] == [
        "escuadra.step",
        "escuadra.stl",
        "escuadra.svg",
        "escuadra.glb",
    ]
    assert assets[3]["mime"] == "model/gltf-binary"


def test_solid_without_glb_keeps_three_assets(tmp_path: Path) -> None:
    """A script that writes only the STEP yields today's three assets."""
    assets = _run_solid(tmp_path, ("step",))
    assert [asset["file"] for asset in assets] == ["escuadra.step", "escuadra.stl", "escuadra.svg"]


def test_verify_glb_accepts_the_magic(tmp_path: Path) -> None:
    """A .glb starting with the glTF magic passes verification."""
    path = tmp_path / "escuadra.glb"
    path.write_bytes(b"glTF" + b"\0" * 20)
    verdict = runner._verify_glb(path)
    assert verdict["passed"] is True


def test_verify_glb_fails_without_the_magic(tmp_path: Path) -> None:
    """A .glb without the magic fails verification and names the file."""
    path = tmp_path / "part.glb"
    path.write_bytes(b"solid nope")
    verdict = runner._verify_glb(path)
    assert verdict["passed"] is False
    assert verdict["file"] == "part.glb"


def test_verify_asset_routes_the_glb(tmp_path: Path) -> None:
    """verify dispatches .glb, so the glb a run declared is checked like the rest."""
    path = tmp_path / "escuadra.glb"
    path.write_bytes(b"glTF" + b"\0" * 20)
    assert runner._verify_asset({}, path)["passed"] is True


def test_verify_glb_fails_a_missing_file(tmp_path: Path) -> None:
    """A .glb that is not there fails and names the file instead of raising."""
    verdict = runner._verify_glb(tmp_path / "missing.glb")
    assert verdict["passed"] is False
    assert verdict["file"] == "missing.glb"


def test_hole_key_ignores_the_axis_sign() -> None:
    """The two faces of one hole share a key whichever way the axis points."""
    down = {"center_mm": [45, 20, 2.5], "diameter_mm": 6.5, "axis": [0, 0, -1]}
    up = {"center_mm": [45, 20, 2.5], "diameter_mm": 6.5, "axis": [0, 0, 1]}
    other = {"center_mm": [2.5, 20, 35], "diameter_mm": 6.5, "axis": [1, 0, 0]}
    assert occlab._key(down) == occlab._key(up)
    assert occlab._key(other) != occlab._key(up)


def test_verify_step_fails_when_solids_count_differs() -> None:
    """A part with two solids fails by default and names the counts."""
    measured = {**ESCUEADRA_MEASURED, "solids": 2}
    with (
        mock.patch.object(occlab, "import_step", return_value=ESCUEADRA_SHAPE),
        mock.patch.object(occlab, "measure", return_value=measured),
    ):
        verdict = runner._verify_step({}, Path("part.step"))
    assert verdict["passed"] is False
    assert verdict["metrics"]["expected_solids"] == 1
    assert verdict["thresholds"]["expect_solids"] == 1
    assert verdict["metrics"]["error"] == "expected 1 solid(s), found 2"


def test_verify_step_passes_when_expect_solids_matches() -> None:
    """expect-solids accepts an exact multi-body result."""
    expected_solids = 2
    measured = {**ESCUEADRA_MEASURED, "solids": expected_solids}
    with (
        mock.patch.object(occlab, "import_step", return_value=ESCUEADRA_SHAPE),
        mock.patch.object(occlab, "measure", return_value=measured),
    ):
        verdict = runner._verify_step({"expect-solids": expected_solids}, Path("part.step"))
    assert verdict["passed"] is True
    assert verdict["metrics"]["expected_solids"] == expected_solids
    assert verdict["thresholds"]["expect_solids"] == expected_solids


class _Attr:
    def __init__(self, **values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)

    def drop(self, key) -> None:
        self._values.pop(key, None)

    def __getattr__(self, key):
        try:
            return self._values[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


class _Entity:
    def __init__(self, dxftype: str, **attrs):
        self._dxftype = dxftype
        self.dxf = _Attr(**attrs)

    def dxftype(self) -> str:
        return self._dxftype


class _TableEntry:
    def __init__(self, name: str):
        self.dxf = _Attr(name=name)


class _Audit:
    def __init__(self, errors=(), fixes=()):
        self.errors = list(errors)
        self.fixes = list(fixes)


class _FakeDoc:
    """The slice of an ezdxf document that verify touches, with ezdxf's defaults."""

    def __init__(
        self,
        *,
        insunits: int,
        measurement: int,
        entities=None,
        layers=None,
        linetypes=None,
        styles=None,
    ):
        self.header = {"$INSUNITS": insunits, "$MEASUREMENT": measurement}
        self._entities = list(entities or [])
        self.layers = list(layers or [_TableEntry("0")])
        self.linetypes = list(linetypes or [_TableEntry("Continuous")])
        self.styles = list(styles or [_TableEntry("Standard")])

    def modelspace(self):
        return list(self._entities)

    def audit(self):
        """Like ezdxf's audit: repair an undefined linetype by dropping it."""
        fixes = 0
        for entity in self._entities:
            linetype = entity.dxf.get("linetype")
            if linetype is not None and linetype not in {"BYLAYER", "BYBLOCK"}:
                entity.dxf.drop("linetype")
                fixes += 1
        return _Audit(fixes=[None] * fixes)


@contextlib.contextmanager
def _dxf_document(tmp_path: Path, *, build, fake_doc=None):
    """Yield a DXF fixture's path: a real ezdxf file, or the fake document."""
    path = tmp_path / "drawing.dxf"
    if fake_doc is not None:
        path.write_bytes(b"fake-dxf")
        with (
            mock.patch.object(occlab, "read_dxf", return_value=fake_doc),
            mock.patch.object(
                occlab, "dxf_data", return_value={"entities": len(fake_doc.modelspace())}
            ),
        ):
            yield path
        return
    ezdxf = importlib.import_module("ezdxf")
    document = ezdxf.new("R2018", setup=True)
    build(document)
    document.saveas(path)
    yield path


def _dxf_fixture(tmp_path: Path, *, build, fake_doc):
    """The real-ezdxf fixture when the kernel is installed, the fake otherwise."""
    if importlib.util.find_spec("ezdxf") is not None:
        return _dxf_document(tmp_path, build=build)
    return _dxf_document(tmp_path, build=build, fake_doc=fake_doc)


def test_verify_dxf_fails_units_mismatch_and_names_found_expected(tmp_path: Path) -> None:
    """units='m' fails when the header codes do not match metres."""

    def build(document):
        document.header["$INSUNITS"] = 4

    fake = _FakeDoc(insunits=4, measurement=1)
    with _dxf_fixture(tmp_path, build=build, fake_doc=fake) as path:
        verdict = runner._verify_dxf({"units": "m"}, path)
    assert verdict["passed"] is False
    assert verdict["metrics"]["units_found"] == [4, 1]
    assert verdict["metrics"]["units_expected"] == [6, 1]
    assert "units found (4,1) expected [6, 1]" in verdict["metrics"]["error"]


def test_verify_dxf_fails_when_insunits_unset(tmp_path: Path) -> None:
    """An explicitly unitless drawing fails when no units are declared."""

    def build(document):
        document.header["$INSUNITS"] = 0

    fake = _FakeDoc(insunits=0, measurement=1)
    with _dxf_fixture(tmp_path, build=build, fake_doc=fake) as path:
        verdict = runner._verify_dxf({}, path)
    assert verdict["passed"] is False
    assert verdict["metrics"]["units_found"] == [0, 1]
    assert "units found (0,1) expected set" in verdict["metrics"]["error"]


def test_verify_dxf_passes_a_metric_header_without_units(tmp_path: Path) -> None:
    """A drawing that names its units and measurement as metres still passes."""

    def build(document):
        document.modelspace().add_line((0, 0), (1, 0))

    fake = _FakeDoc(insunits=6, measurement=1, entities=[_Entity("LINE", layer="0")])
    with _dxf_fixture(tmp_path, build=build, fake_doc=fake) as path:
        verdict = runner._verify_dxf({}, path)
    assert verdict["passed"] is True
    assert verdict["metrics"]["units_expected"] == "consistent"


def test_verify_dxf_fails_on_undefined_linetype_before_audit(tmp_path: Path) -> None:
    """An undefined linetype is reported before the audit can remove it."""

    def build(document):
        document.modelspace().add_line((0, 0), (1, 0), dxfattribs={"linetype": "MISSING_LT"})

    fake = _FakeDoc(
        insunits=6,
        measurement=1,
        entities=[_Entity("LINE", layer="0", linetype="MISSING_LT")],
    )
    with _dxf_fixture(tmp_path, build=build, fake_doc=fake) as path:
        verdict = runner._verify_dxf({}, path)
    assert verdict["passed"] is False
    assert "MISSING_LT" in verdict["metrics"]["undefined_refs"]["linetypes"]
    assert "undefined linetype MISSING_LT" in verdict["metrics"]["error"]


def test_verify_dxf_accepts_text_without_an_explicit_style(tmp_path: Path) -> None:
    """A TEXT with no style names ezdxf's Standard style, not a phantom name."""

    def build(document):
        document.modelspace().add_text("STUDY")

    fake = _FakeDoc(insunits=6, measurement=1, entities=[_Entity("TEXT", layer="0")])
    with _dxf_fixture(tmp_path, build=build, fake_doc=fake) as path:
        verdict = runner._verify_dxf({}, path)
    assert verdict["passed"] is True
    assert verdict["metrics"]["undefined_refs"] == {"layers": [], "linetypes": [], "styles": []}


def test_verify_dxf_fails_on_undefined_layer_and_names_it(tmp_path: Path) -> None:
    """A layer an entity references but the drawing never defines fails."""

    def build(document):
        document.modelspace().add_line((0, 0), (1, 0), dxfattribs={"layer": "ghost"})

    fake = _FakeDoc(insunits=6, measurement=1, entities=[_Entity("LINE", layer="ghost")])
    with _dxf_fixture(tmp_path, build=build, fake_doc=fake) as path:
        verdict = runner._verify_dxf({}, path)
    assert verdict["passed"] is False
    assert verdict["metrics"]["undefined_refs"]["layers"] == ["ghost"]
    assert "undefined layer ghost" in verdict["metrics"]["error"]
