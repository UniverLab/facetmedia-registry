"""The three blender examples: pieces that validate, files that resolve, scripts.

An example is the contract an agent copies, so these tests pin what makes it
work: each piece TOML stays inside its capability's declared inputs and values,
every file it references is on disk beside it, each script compiles, keeps every
creative choice in one literal ``DATA`` dict, imports nothing but ``bpy`` and
``math``, and leaves ``scene.camera`` set. The study scripts must also render
glass see-through and the product must light its metal, the two failures the
functional test of 2026-11-12 found.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "blender"
EXAMPLES = PACKAGE / "examples"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))

#: Folder -> (piece TOML, script, capability) for the three examples.
CASES = {
    "study-photo": ("study-photo.toml", "study_photo.py", "scene"),
    "product": ("product.toml", "product.py", "scene"),
    "tour": ("tour.toml", "tour.py", "animation"),
}
#: The models each example must ship beside its piece.
MODELS = {
    "study-photo": "estudio.glb",
    "product": "part.stl",
    "tour": "../study-photo/estudio.glb",
}
#: The approved study photo, ported from the removed photo preset.
APPROVED_SUN = {"azimuth": 210.0, "elevation": 32.0, "strength": 3.0}
APPROVED_CAMERA = {"azimuth": -40.0, "elevation": 48.0}
#: The approved still's frame: the orthographic fit needs its aspect.
APPROVED_ASPECT = 1000 / 1600
#: The two scripts that dress the study and therefore carry glass.
STUDY_FOLDERS = ("study-photo", "tour")
#: The imports a script may carry: Blender's module and the standard library.
ALLOWED_IMPORTS = {"bpy", "math"}
#: The glass the study scripts must draw see-through.
GLASS_ROUGHNESS = 0.02
#: The approved still's exposure and sky wash.
STUDY_EXPOSURE = -0.6
SKY_STRENGTH = 0.2
#: glTF arrives in millimetres; the scripts work in metres.
MILLIMETRES = 0.001
#: The product example frames the part with a 50 mm lens.
PRODUCT_LENS = 50
#: The tour's Eevee recipe and its lens.
TOUR_SAMPLES = 32
TOUR_EXPOSURE = -0.4
TOUR_FOCAL = 30


def _piece(folder: str) -> dict[str, Any]:
    """One example's ``[inputs]`` table."""
    toml_name = CASES[folder][0]
    data = tomllib.loads((EXAMPLES / folder / toml_name).read_text(encoding="utf-8"))
    return data["inputs"]


def _source(folder: str) -> str:
    return (EXAMPLES / folder / CASES[folder][1]).read_text(encoding="utf-8")


def _tree(folder: str) -> ast.Module:
    return ast.parse(_source(folder), filename=f"{folder}/{CASES[folder][1]}")


def _data(folder: str) -> dict[str, Any]:
    """The script's ``DATA`` dict, read without running Blender."""
    for node in _tree(folder).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DATA" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, dict)
            return value
    raise AssertionError(f"{folder}: the script defines no DATA dict")


def test_each_piece_validates_against_its_capability_inputs() -> None:
    """Keys, required keys, ranges and enums are the manifest's, not the doc's."""
    for folder, (_toml_name, script, capability) in CASES.items():
        inputs = _piece(folder)
        declared = MANIFEST["capabilities"][capability]["inputs"]
        assert set(inputs) <= set(declared), folder
        required = {key for key, field in declared.items() if field.get("required")}
        assert required <= set(inputs), folder
        assert inputs["script"] == script, folder
        for key, value in inputs.items():
            field = declared[key]
            if field["type"] in ("integer", "number"):
                assert field["min"] <= value <= field["max"], (folder, key)
            if field["type"] == "enum":
                assert value in field["values"], (folder, key)


def test_every_file_a_piece_references_exists() -> None:
    """A script, a model and a part that are not on disk send the agent nowhere."""
    for folder, (_toml_name, script, _capability) in CASES.items():
        piece_dir = EXAMPLES / folder
        assert (piece_dir / script).is_file(), (folder, script)
        assert (piece_dir / _piece(folder)["script"]).is_file(), folder
        model = MODELS[folder]
        assert (piece_dir / model).is_file(), (folder, model)
        assert (piece_dir / _data(folder)["model"]).is_file(), folder


def test_each_script_compiles_and_defines_data() -> None:
    """The script is valid Python and carries its creative choices as data."""
    for folder in CASES:
        source = _source(folder)
        compile(source, f"{folder}/{CASES[folder][1]}", "exec")
        data = _data(folder)
        assert data, folder
        assert "camera" in data, folder
        assert "materials" in data or "metal" in data, folder
        assert "scene.camera =" in source, folder


def test_each_script_is_plain_bpy_with_no_runner_helpers() -> None:
    """No helper import from the runner: the script must stand on its own."""
    for folder in CASES:
        imported: set[str] = set()
        for node in ast.walk(_tree(folder)):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= ALLOWED_IMPORTS, (folder, imported)
        assert 'globals()["FACET_PIECE_DIR"]' in _source(folder), folder


def test_the_study_scripts_render_glass_see_through() -> None:
    """Glass is see-through by alpha and BLENDED: Eevee draws refraction black."""
    for folder in STUDY_FOLDERS:
        glass = _data(folder)["materials"]["vidrio"]
        assert 0.0 < glass["alpha"] < 1.0, folder
        assert glass["roughness"] == GLASS_ROUGHNESS, folder
        assert glass["blended"] is True, folder
        assert 'inputs["Alpha"]' in _source(folder), folder
        assert 'surface_render_method = "BLENDED"' in _source(folder), folder


def test_the_study_photo_keeps_the_approved_look() -> None:
    """The approved still's sun, sky, camera and output, ported from the preset."""
    inputs = _piece("study-photo")
    assert inputs["engine"] == "cycles"
    assert (inputs["width"], inputs["height"]) == (1600, 1000)
    assert inputs["exposure"] == STUDY_EXPOSURE
    data = _data("study-photo")
    assert {key: data["sun"][key] for key in APPROVED_SUN} == APPROVED_SUN
    assert data["sky"]["strength"] == SKY_STRENGTH
    assert data["camera"]["azimuth"] == APPROVED_CAMERA["azimuth"]
    assert data["camera"]["elevation"] == APPROVED_CAMERA["elevation"]
    assert data["camera"]["aspect"] == APPROVED_ASPECT
    assert set(data["materials"]) == {
        "muros",
        "piso",
        "vidrio",
        "cama",
        "almohada",
        "mesa",
        "sillas",
    }


def test_the_product_scales_millimetres_and_lights_the_part() -> None:
    """The part comes in mm; how it is lit is the script's choice, kept in DATA."""
    data = _data("product")
    assert data["scale"] == MILLIMETRES
    assert data["metal"]["metallic"] == 1.0
    assert set(data["world"]) == {"color", "strength"}
    lights = data["lights"]
    assert lights, "at least one light"
    for light in lights:
        assert light["size"] > 0
        assert light["energy"] > 0
        assert {"azimuth", "elevation", "distance"} <= set(light)
    assert data["camera"]["lens"] == PRODUCT_LENS


def test_the_tour_is_the_lab_orbit_at_the_piece_frame_count() -> None:
    """1280x720, 240 frames at 24 fps in Eevee, focal 30 over the study glb."""
    inputs = _piece("tour")
    assert inputs["engine"] == "eevee"
    assert (inputs["width"], inputs["height"]) == (1280, 720)
    assert (inputs["frames"], inputs["fps"]) == (240, 24)
    assert inputs["samples"] == TOUR_SAMPLES
    assert inputs["exposure"] == TOUR_EXPOSURE
    data = _data("tour")
    assert data["model"] == MODELS["tour"]
    assert data["camera"]["focal"] == TOUR_FOCAL
    assert data["move"] == {
        "azimuth": (-75.0, -15.0),
        "elevation": (55.0, 40.0),
        "distance": (14.0, 10.5),
        "frames": inputs["frames"],
    }
    assert data["eevee"] == {"raytracing": "SCREEN", "fast_gi": True, "shadows": True}
