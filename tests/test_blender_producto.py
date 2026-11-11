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
#: Twice the reference span, so the light plan must move with the box.
LARGE_PIECES = [("escuadra", (120.0, 80.0, 20.0))]
SUMMARY_MAX = 160


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
    # 3 x 0.06 m is under the 25 cm floor, so the camera never enters the part.
    assert math.dist(trail["camera"]["location"], (0.0, 0.0, 0.0)) == pytest.approx(0.25)


def test_the_material_and_backdrop_inputs_reach_the_scene(tmp_path: Path) -> None:
    """Steel on cement is a different studio, not the same one renamed."""
    result = _render(tmp_path, material="steel", backdrop="concrete")
    trail = _trail(tmp_path)

    assert trail["materials"] == {"escuadra": "steel"}
    assert trail["backdrop"] == [0.09, 0.09, 0.095, 1.0]
    properties = result["assets"][0]["properties"]
    assert (properties["material"], properties["backdrop"]) == ("steel", "concrete")


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
