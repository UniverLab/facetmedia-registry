"""Cars for scale through a stub host: load order, the floor and the failures.

No real Blender and no network. A stub ``bpy`` records what the runner did: the
materials dressed before any library load, each car's root location, scale and
yaw after the collection was linked, and where the camera came in the order.
The prebuilt ``cars.blend`` is a JSON catalog of collection names and root
counts, so a name the file does not hold and a collection that holds two roots
are both reproducible without the Quaternius pack.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from test_blender_personas import (
    _call,
    _env,
    _events,
    _model,
    _request,
    _trail,
)

#: The lab's car pair from projects/prueba-render-arq/escena.py:45 plus a
#: turned compacto; positions are metres in the scene's own axes.
CARS = [
    {"name": "sedan", "x": -2.7, "y": 0.8},
    {"name": "camioneta", "x": -5.1, "y": 0.8},
    {"name": "compacto", "x": 1.0, "y": -2.0, "rotation": 90},
]
#: The collections the stub cars.blend holds, one root each.
CAR_CATALOG = {"sedan": 1, "camioneta": 1, "compacto": 1}


def _autos_blend(tmp_path: Path) -> Path:
    path = tmp_path / "cars.blend"
    path.write_bytes(b"BLENDER-stub")
    return path


def _car_env(tmp_path: Path, catalog: dict[str, int] | None = None) -> dict[str, str]:
    return _env(tmp_path, CAR_CATALOG if catalog is None else catalog)


def test_cars_load_after_dress_and_park_on_the_floor(tmp_path: Path) -> None:
    """The prebuilt collections load after dressing and park at (x, y, floor)."""
    model = _model(tmp_path)
    blend = _autos_blend(tmp_path)
    request = _request(
        tmp_path,
        "run",
        model=str(model),
        **{"cars-blend": str(blend)},
        cars=CARS,
    )

    done, result_path = _call("run", request, tmp_path, _car_env(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    assert result_path.exists()
    trail = _trail(tmp_path)
    events = _events(trail)
    first_load = min(index for index, name in enumerate(events) if name.startswith("load:"))
    last_dress = max(index for index, name in enumerate(events) if name.startswith("material:"))
    assert last_dress < first_load
    floor_z = trail["floor"][2]
    for placement in CARS:
        root = trail["people"][f"{placement['name']}-root"]
        assert root["location"][:2] == [placement["x"], placement["y"]]
        assert root["location"][2] == pytest.approx(floor_z)
        assert root["scale"] == [1.0, 1.0, 1.0]
        assert root["yaw"] == pytest.approx(math.radians(placement.get("rotation", 0)))
        assert root["mode"] == "XYZ"
    # No car was dressed: they were not part of the scene at dress time.
    assert all(not blocks for blocks in trail["person_materials"].values())


def test_the_unknown_car_names_the_collections_the_blend_holds(tmp_path: Path) -> None:
    """A name the blend does not hold fails loudly, naming what it has."""
    model = _model(tmp_path)
    blend = _autos_blend(tmp_path)
    request = _request(
        tmp_path,
        "run",
        model=str(model),
        **{"cars-blend": str(blend)},
        cars=[{"name": "nadie", "x": 1, "y": 2}],
    )

    done, result_path = _call("run", request, tmp_path, _car_env(tmp_path))

    assert done.returncode != 0
    assert f"nadie is not a collection in {blend}" in done.stderr
    assert "(has: ['camioneta', 'compacto', 'sedan'])" in done.stderr
    assert not result_path.exists()
    assert not (tmp_path / "out" / "estudio-photo.png").exists()


def test_a_car_collection_with_two_roots_fails_loudly(tmp_path: Path) -> None:
    """Moving one root is the only safe placement, so two roots is a failure."""
    model = _model(tmp_path)
    request = _request(
        tmp_path,
        "run",
        model=str(model),
        **{"cars-blend": str(_autos_blend(tmp_path))},
        cars=[{"name": "dos", "x": 0, "y": 0}],
    )

    done, result_path = _call("run", request, tmp_path, _car_env(tmp_path, {"dos": 2}))

    assert done.returncode != 0
    assert "dos: expected one root object, found 2" in done.stderr
    assert not result_path.exists()
    assert not (tmp_path / "out" / "estudio-photo.png").exists()


def test_the_tour_parks_cars_before_it_builds_the_camera(tmp_path: Path) -> None:
    """The tour parks the same cars, between the dressing and the camera."""
    model = _model(tmp_path)
    request = _request(
        tmp_path,
        "run",
        capability="blender.tour",
        model=str(model),
        seconds=2,
        fps=12,
        **{"cars-blend": str(_autos_blend(tmp_path))},
        cars=CARS,
    )

    done, result_path = _call("run", request, tmp_path, _car_env(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    assert result_path.exists()
    trail = _trail(tmp_path)
    events = _events(trail)
    first_load = min(index for index, name in enumerate(events) if name.startswith("load:"))
    last_dress = max(index for index, name in enumerate(events) if name.startswith("material:"))
    assert last_dress < first_load < events.index("camera")
    assert trail["animation"] is True
    for placement in CARS:
        root = trail["people"][f"{placement['name']}-root"]
        assert root["location"][:2] == [placement["x"], placement["y"]]
        assert root["location"][2] == pytest.approx(trail["floor"][2])
        assert root["scale"] == [1.0, 1.0, 1.0]


def test_an_empty_list_never_touches_the_missing_blend(tmp_path: Path) -> None:
    """No car is placed, so a blend that does not exist is never opened."""
    model = _model(tmp_path)
    request = _request(
        tmp_path,
        "run",
        model=str(model),
        **{"cars-blend": str(tmp_path / "nada.blend")},
        cars=[],
    )

    done, result_path = _call("run", request, tmp_path, _car_env(tmp_path))

    assert done.returncode == 0, done.stdout + done.stderr
    assert result_path.exists()
    assert not [name for name in _events(_trail(tmp_path)) if name.startswith("load:")]
