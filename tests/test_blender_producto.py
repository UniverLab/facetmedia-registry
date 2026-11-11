"""The product shot through the same stub host: bounding box, lights, PNG.

No real Blender runs here. The stub scene already used by the daylight cycle
answers ``wm.stl_import`` with the piece list from ``STUB_SCENE`` and records
the world bound box, every light's type, energy, size and place, the camera and
the render settings. That makes the light rule — derived from the part's
measured span, never a fixed studio value — assertable without a GPU.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import PIL.Image
import pytest
from test_blender_cycle import (
    SCHEMA,
    _call,
    _env,
    _request,
    _scene,
    _trail,
    runner,
)

PRODUCTO = runner.producto
#: The approved reference: a 6 cm bracket, 60 x 40 x 10 mm in the STL.
PIECES = [("escuadra", (60.0, 40.0, 10.0))]
#: The same bracket in metres, for the bounding radius the camera is fitted to.
REFERENCE_EXTENTS = (0.06, 0.04, 0.01)
#: Twice the reference span, so the light plan must move with the box.
LARGE_PIECES = [("escuadra", (120.0, 80.0, 20.0))]
#: Each studio input, at both ends of the range it refuses.
OUT_OF_RANGE = [
    ("exposure", -3.5),
    ("exposure", 3.5),
    ("fill", 0.1),
    ("fill", 1.0),
    ("light", 0.05),
    ("light", 11.0),
]
SUMMARY_MAX = 160
#: The floor the old span rule imposed; the fill distance no longer has one.
FORMER_FLOOR = 0.25


def _radius(extents: tuple[float, ...] = REFERENCE_EXTENTS) -> float:
    """Half the diagonal of the box: the sphere the part is framed inside."""
    return 0.5 * math.sqrt(sum(side * side for side in extents))


def _part(tmp_path: Path) -> Path:
    path = tmp_path / "escuadra.stl"
    path.write_bytes(b"solid escuadra\nendsolid escuadra\n")
    return path


def _render(
    tmp_path: Path, pieces: list[tuple[str, tuple[float, float, float]]] | None = None, **inputs
) -> dict:
    request = _request(
        tmp_path, "run", capability="blender.product", part=str(_part(tmp_path)), **inputs
    )
    env = _env(
        tmp_path,
        STUB_SCENE=str(_scene(tmp_path, pieces or PIECES)),
        STUB_TRAIL=str(tmp_path / "trail.json"),
    )
    done, result_path = _call("run", request, tmp_path, env)
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(result_path.read_text(encoding="utf-8"))


def test_the_light_plan_pins_four_watts_at_fifty_centimetres_for_six_centimetres() -> None:
    """The reference regime and the clamps on both ends, in watts and metres."""
    plan = PRODUCTO.light_plan
    assert plan(0.06) == pytest.approx((4.0, 0.5))
    assert plan(0.12) == pytest.approx((6.0, 1.0))
    # Below 2 W a small piece goes dark; above 6 W it burns out.
    assert plan(0.001) == pytest.approx((2.0, 0.15))
    assert plan(1.0) == pytest.approx((6.0, 2.0))


def test_the_cycle_scales_the_studio_lights_from_the_measured_box(tmp_path: Path) -> None:
    """The 6 cm bracket measures 0.06 m and gets 4 W lights 0.50 m away."""
    result = _render(tmp_path)
    part = _part(tmp_path)
    trail = _trail(tmp_path)

    assert trail["stl_import"] == str(part)
    assert trail["span"] == pytest.approx(0.06)
    lights = trail["lights"]
    assert set(lights) == {"luz-1", "luz-2"}
    for light in lights.values():
        assert (light["type"], light["shape"]) == ("AREA", "SQUARE")
        assert light["energy"] == pytest.approx(4.0)
        assert light["size"] == pytest.approx(0.5)
        assert math.dist(light["location"], (0.0, 0.0, 0.0)) == pytest.approx(0.5)

    asset = result["assets"][0]
    assert asset["file"] == "escuadra-product.png"
    assert (asset["kind"], asset["mime"], asset["seed"]) == ("image", "image/png", 0)
    assert asset["inputs"] == [str(part)]
    assert asset["properties"] == {
        "width": PRODUCTO.PRODUCT_WIDTH,
        "height": PRODUCTO.PRODUCT_HEIGHT,
        "samples": PRODUCTO.SAMPLES,
        "exposure": PRODUCTO.EXPOSURE,
        "fill": PRODUCTO.DEFAULT_FILL,
        "light": PRODUCTO.DEFAULT_LIGHT,
        "material": "brushed-aluminum",
        "backdrop": "graphite",
    }
    assert result["tool"]["name"] == "blender"
    with PIL.Image.open(tmp_path / "out" / "escuadra-product.png") as image:
        assert image.size == (PRODUCTO.PRODUCT_WIDTH, PRODUCTO.PRODUCT_HEIGHT)


def test_a_larger_part_gets_more_light_from_its_own_box(tmp_path: Path) -> None:
    """12 cm is 6 W at 1 m: the plan follows the box, it is not a constant."""
    _render(tmp_path, LARGE_PIECES)
    trail = _trail(tmp_path)

    assert trail["span"] == pytest.approx(0.12)
    for light in trail["lights"].values():
        assert light["energy"] == pytest.approx(6.0)
        assert light["size"] == pytest.approx(1.0)
        assert math.dist(light["location"], (0.0, 0.0, 0.0)) == pytest.approx(1.0)


def test_the_recipe_is_a_1200_square_cycles_studio(tmp_path: Path) -> None:
    """The dark backdrop, the metal, the 50 mm camera and the AgX exposure."""
    _render(tmp_path)
    trail = _trail(tmp_path)
    render = trail["render"]

    assert render["resolution"] == [PRODUCTO.PRODUCT_WIDTH, PRODUCTO.PRODUCT_HEIGHT]
    assert render["engine"] == "CYCLES"
    assert render["device"] == "GPU"
    assert render["samples"] == PRODUCTO.SAMPLES
    assert render["denoise"] is True
    assert render["exposure"] == PRODUCTO.EXPOSURE
    assert render["look"] == "AgX - Medium High Contrast"
    assert render["filepath"] == str(tmp_path / "out" / "escuadra-product.png")
    assert trail["materials"] == {"escuadra": "brushed-aluminum"}
    assert trail["backdrop"] == [0.02, 0.02, 0.025, 1.0]
    assert trail["camera"]["type"] == "PERSP"
    assert trail["camera"]["lens"] == PRODUCTO.LENS
    distance = PRODUCTO.camera_distance(_radius(), PRODUCTO.DEFAULT_FILL)
    assert math.dist(trail["camera"]["location"], (0.0, 0.0, 0.0)) == pytest.approx(distance)
    # 6 cm of bracket is framed closer than the old 25 cm floor ever allowed.
    assert distance < FORMER_FLOOR
    assert trail["camera"]["clip_start"] < distance - _radius()


def test_the_material_and_backdrop_inputs_reach_the_scene(tmp_path: Path) -> None:
    """Steel on cement is a different studio, not the same one renamed."""
    result = _render(tmp_path, material="steel", backdrop="concrete")
    trail = _trail(tmp_path)

    assert trail["materials"] == {"escuadra": "steel"}
    assert trail["backdrop"] == [0.09, 0.09, 0.095, 1.0]
    properties = result["assets"][0]["properties"]
    assert (properties["material"], properties["backdrop"]) == ("steel", "concrete")


def test_the_studio_options_default_to_the_approved_recipe() -> None:
    """No input means today's studio: -0.2 stops, 0.6 fill, one times the light."""
    assert PRODUCTO.options({}) == pytest.approx((PRODUCTO.EXPOSURE, 0.6, 1.0))
    assert PRODUCTO.options({"exposure": 0, "fill": 0.2, "light": 0.1}) == pytest.approx(
        (0.0, 0.2, 0.1)
    )


def test_the_exposure_input_reaches_the_scene_and_the_record(tmp_path: Path) -> None:
    """A burnt shot is corrected from the piece, and the record says what ran."""
    result = _render(tmp_path, exposure=1.5)
    trail = _trail(tmp_path)

    assert trail["render"]["exposure"] == pytest.approx(1.5)
    properties = result["assets"][0]["properties"]
    assert properties["exposure"] == pytest.approx(1.5)
    assert properties["fill"] == PRODUCTO.DEFAULT_FILL
    assert properties["light"] == PRODUCTO.DEFAULT_LIGHT


def test_the_fill_input_sets_the_camera_distance(tmp_path: Path) -> None:
    """A 0.4 fill pushes the camera back from the default framing of 0.6."""
    result = _render(tmp_path, fill=0.4)
    trail = _trail(tmp_path)
    distance = PRODUCTO.camera_distance(_radius(), 0.4)

    assert math.dist(trail["camera"]["location"], (0.0, 0.0, 0.0)) == pytest.approx(distance)
    assert trail["camera"]["clip_start"] < distance - _radius()
    assert distance > PRODUCTO.camera_distance(_radius(), PRODUCTO.DEFAULT_FILL)
    assert result["assets"][0]["properties"]["fill"] == pytest.approx(0.4)


def test_the_light_input_scales_the_energy_but_not_the_distance(tmp_path: Path) -> None:
    """Twice the light on the same 6 cm part is 8 W at 50 cm, not a new studio."""
    result = _render(tmp_path, light=2.0)
    trail = _trail(tmp_path)

    for lamp in trail["lights"].values():
        assert lamp["energy"] == pytest.approx(8.0)
        assert lamp["size"] == pytest.approx(0.5)
        assert math.dist(lamp["location"], (0.0, 0.0, 0.0)) == pytest.approx(0.5)
    assert result["assets"][0]["properties"]["light"] == pytest.approx(2.0)


@pytest.mark.parametrize(("name", "value"), OUT_OF_RANGE)
def test_an_input_outside_its_range_fails_the_run_loudly(
    tmp_path: Path, name: str, value: float
) -> None:
    """The shot is never rendered with a value the package does not promise."""
    request = _request(
        tmp_path, "run", capability="blender.product", part=str(_part(tmp_path)), **{name: value}
    )
    env = _env(
        tmp_path,
        STUB_SCENE=str(_scene(tmp_path, PIECES)),
        STUB_TRAIL=str(tmp_path / "trail.json"),
    )

    done, _ = _call("run", request, tmp_path, env)

    assert done.returncode != 0
    assert name in done.stderr
    assert "out of range" in done.stderr


def test_verify_measures_the_product_png_at_1200_square(tmp_path: Path) -> None:
    """verify answers without Blender and rejects the daylight 1600 frame."""
    good = tmp_path / "out" / "escuadra-product.png"
    good.parent.mkdir()
    PIL.Image.new("RGB", (PRODUCTO.PRODUCT_WIDTH, PRODUCTO.PRODUCT_HEIGHT)).save(good)
    large = tmp_path / "out" / "estudio-photo.png"
    PIL.Image.new("RGB", (1600, 1600)).save(large)
    request = _request(tmp_path, "verify", capability="blender.product")
    request["assets"] = [str(good), str(large)]

    done, result_path = _call("verify", request, tmp_path, {**os.environ, "PATH": str(tmp_path)})

    assert done.returncode == 0, done.stdout + done.stderr
    verdicts = json.loads(result_path.read_text(encoding="utf-8"))["assets"]
    thresholds = {"width": PRODUCTO.PRODUCT_WIDTH, "height": PRODUCTO.PRODUCT_HEIGHT}
    assert verdicts[0]["passed"] is True
    assert verdicts[0]["metrics"] == thresholds
    assert verdicts[0]["thresholds"] == thresholds
    assert verdicts[1]["passed"] is False
    assert verdicts[1]["metrics"] == {"width": 1600, "height": 1600}


def test_preview_writes_the_image_schema_for_a_product_shot(tmp_path: Path) -> None:
    """The preview names the studio the shot came from, not the daylight one."""
    photo = tmp_path / "out" / "escuadra-product.png"
    photo.parent.mkdir()
    PIL.Image.new("RGB", (PRODUCTO.PRODUCT_WIDTH, PRODUCTO.PRODUCT_HEIGHT)).save(photo)
    request = _request(
        tmp_path,
        "preview",
        capability="blender.product",
        part=str(_part(tmp_path)),
        assets=[str(photo)],
    )

    done, result_path = _call("preview", request, tmp_path, {**os.environ})

    assert done.returncode == 0, done.stdout + done.stderr
    entry = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert entry["file"] == "escuadra-product.png"
    assert entry["preview"] == "escuadra-product.png.preview.json"
    data = json.loads((photo.parent / entry["preview"]).read_text(encoding="utf-8"))
    assert set(data) == set(SCHEMA["required"])
    assert data["preview"] == 1 and data["kind"] == "image"
    assert data["name"] == "escuadra-product"
    assert (data["width"], data["height"]) == (
        PRODUCTO.PRODUCT_WIDTH,
        PRODUCTO.PRODUCT_HEIGHT,
    )
    assert data["seed"] == 0
    assert data["prompt"] == "escuadra · product photo · brushed-aluminum on graphite · studio"
    assert len(data["summary"]) <= SUMMARY_MAX
