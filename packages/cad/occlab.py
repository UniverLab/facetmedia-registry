"""CAD helpers for the cad package runner: OpenCASCADE measures and renders.

The runner leans on this module for everything that touches the geometry
kernels: importing a STEP, measuring a solid (volume, bounding box, faces,
solids and the deduplicated holes), completing a missing export (STL, SVG),
parsing and auditing a DXF, rendering a missing DXF view and shading a
solid's isometric view.

Heavy imports go through ``importlib`` inside each function, so a broken
environment still lets the doctor report *which* import fails instead of
dying on a top-level import.
"""

from __future__ import annotations

import importlib
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

#: STL export tolerances the lab's escuadra.py itself uses.
STL_TOLERANCE = 0.05
STL_ANGULAR_TOLERANCE = 0.2
#: SVG line view: the lab's projection direction and canvas.
SVG_PROJECTION_DIR = (1.2, -1.0, 0.8)
SVG_WIDTH = 600
SVG_HEIGHT = 450
#: A hole is a full-revolution cylinder; a fillet or rounded edge is not.
FULL_REVOLUTION_DEG = 359.0
#: The isometric view's canvas and its light direction (Lambert shading).
VIEW_WIDTH = 1200
VIEW_HEIGHT = 900
VIEW_TOLERANCE = 0.1
LIGHT_DIRECTION = (1.2, -1.0, 0.8)
#: Rounding of the dedup key, in mm: two faces of one hole share it.
DEDUP_DECIMALS = 4
#: Axis components below this are zero, for the sign the dedup key normalises.
AXIS_ZERO = 1e-9
#: A binary STL is an 80-byte header, a 4-byte count and 50 bytes per triangle.
STL_HEADER_BYTES = 80
STL_TRIANGLE_BYTES = 50


def import_step(path: Path) -> Any:
    """The solid inside a STEP file, as a CadQuery shape."""
    cadquery = importlib.import_module("cadquery")
    return cadquery.importers.importStep(str(path)).val()


def export_step(shape: Any, path: Path) -> None:
    """Write a shape to STEP (the doctor's throwaway roundtrip)."""
    cadquery = importlib.import_module("cadquery")
    cadquery.exporters.export(shape, str(path))


def export_stl(shape: Any, path: Path) -> None:
    """Mesh a shape to STL with the lab's print tolerances."""
    cadquery = importlib.import_module("cadquery")
    cadquery.exporters.export(
        shape, str(path), tolerance=STL_TOLERANCE, angularTolerance=STL_ANGULAR_TOLERANCE
    )


def export_svg(shape: Any, path: Path) -> None:
    """Line view of a shape, hidden lines off, on the lab's canvas."""
    cadquery = importlib.import_module("cadquery")
    options = {
        "projectionDir": SVG_PROJECTION_DIR,
        "showHidden": False,
        "width": SVG_WIDTH,
        "height": SVG_HEIGHT,
    }
    cadquery.exporters.export(shape, str(path), opt=options)


def measure(shape: Any) -> dict[str, Any]:
    """A solid's measurements: volume, bounding box, faces, solids, holes."""
    box = shape.BoundingBox()
    return {
        "volume_mm3": round(float(shape.Volume()), 6),
        "bbox_mm": [round(box.xlen, 6), round(box.ylen, 6), round(box.zlen, 6)],
        "faces": len(shape.Faces()),
        "solids": len(shape.Solids()),
        "holes": holes(shape),
    }


def holes(shape: Any) -> list[dict[str, Any]]:
    """Every full-revolution cylindrical face, deduplicated by axis and centre.

    A drilled hole wraps 360 degrees around its axis; a fillet or a rounded
    edge is a partial cylinder and is not a hole, so the angular span tells
    them apart.
    """
    adaptor = importlib.import_module("OCP.BRepAdaptor")
    found: dict[tuple[Any, ...], dict[str, Any]] = {}
    for face in shape.Faces():
        if face.geomType() != "CYLINDER":
            continue
        surface = adaptor.BRepAdaptor_Surface(face.wrapped)
        if math.degrees(surface.LastUParameter() - surface.FirstUParameter()) < FULL_REVOLUTION_DEG:
            continue
        hole = _hole(face, surface)
        found.setdefault(_key(hole), hole)
    return [found[key] for key in sorted(found)]


def _hole(face: Any, surface: Any) -> dict[str, Any]:
    """One cylindrical face as data: centre, diameter and axis."""
    cylinder = surface.Cylinder()
    axis = cylinder.Axis().Direction()
    box = face.BoundingBox()
    return {
        "center_mm": [
            round((box.xmin + box.xmax) / 2, 6),
            round((box.ymin + box.ymax) / 2, 6),
            round((box.zmin + box.zmax) / 2, 6),
        ],
        "diameter_mm": round(2.0 * cylinder.Radius(), 6),
        "axis": [round(axis.X(), 6), round(axis.Y(), 6), round(axis.Z(), 6)],
    }


def _key(hole: dict[str, Any]) -> tuple[Any, ...]:
    """The dedup key: the axis sign normalised, centre and diameter rounded."""
    axis = [float(value) for value in hole["axis"]]
    if next((value for value in axis if abs(value) > AXIS_ZERO), 1.0) < 0:
        axis = [-value for value in axis]
    centre = tuple(round(float(value), DEDUP_DECIMALS) for value in hole["center_mm"])
    return (*centre, round(float(hole["diameter_mm"]), DEDUP_DECIMALS), *axis)


def stl_triangles(path: Path) -> int:
    """Triangle count of an STL file (binary or ASCII); 0 when unparseable."""
    data = path.read_bytes()
    header = STL_HEADER_BYTES + 4
    if len(data) >= header:
        count = int.from_bytes(data[STL_HEADER_BYTES:header], "little")
        if len(data) == header + STL_TRIANGLE_BYTES * count and count > 0:
            return count
    return sum(1 for line in data.splitlines() if line.strip().startswith(b"facet normal"))


def svg_ok(path: Path) -> bool:
    """True when the file parses as XML with an <svg> root."""
    root = ET.parse(path).getroot()
    return root.tag.rsplit("}", 1)[-1] == "svg"


def read_dxf(path: Path) -> Any:
    """A parsed DXF document; callers audit and render from it."""
    ezdxf = importlib.import_module("ezdxf")
    return ezdxf.readfile(path)


def audit_dxf(document: Any) -> dict[str, int]:
    """The audit result: errors and fixes a strict reader would reject."""
    auditor = document.audit()
    return {"errors": len(auditor.errors), "fixes": len(auditor.fixes)}


def layer_names(document: Any) -> list[str]:
    """Every layer the drawing defines, for verify's expect-layers."""
    return [layer.dxf.name for layer in document.layers]


def dxf_data(document: Any, audit: dict[str, int]) -> dict[str, Any]:
    """A DXF's entities, layers, units and audit, as the preview's drawing.

    ``audit`` is the result of one :func:`audit_dxf` call on ``document``:
    auditing twice would let the first pass's repairs hide the fixes.
    """
    units = importlib.import_module("ezdxf.units")
    modelspace = document.modelspace()
    counts: dict[str, int] = {}
    for entity in modelspace:
        layer = entity.dxf.layer
        counts[layer] = counts.get(layer, 0) + 1
    return {
        "units": units.unit_name(document.units),
        "entities": len(modelspace),
        "layers": [{"name": name, "entities": counts[name]} for name in sorted(counts)],
        "audit": dict(audit),
    }


def render_dxf_svg(document: Any, path: Path) -> None:
    """The drawing's SVG view on white, colours as drawn."""
    drawing = importlib.import_module("ezdxf.addons.drawing")
    svg = importlib.import_module("ezdxf.addons.drawing.svg")
    config = _drawing_config(drawing)
    backend = svg.SVGBackend()
    frontend = drawing.Frontend(drawing.RenderContext(document), backend, config=config)
    frontend.draw_layout(document.modelspace())
    page = drawing.layout.Page(
        0, 0, drawing.layout.Units.mm, margins=drawing.layout.Margins.all(10)
    )
    path.write_text(backend.get_string(page), encoding="utf-8")


def render_dxf_png(document: Any, path: Path, dpi: int = 200) -> None:
    """The drawing's PNG view on white, colours as drawn."""
    drawing = importlib.import_module("ezdxf.addons.drawing")
    draw_mpl = importlib.import_module("ezdxf.addons.drawing.matplotlib")
    draw_mpl.qsave(
        document.modelspace(), str(path), bg="#FFFFFF", dpi=dpi, config=_drawing_config(drawing)
    )


def _drawing_config(drawing: Any) -> Any:
    """White background, layer colours kept."""
    config = importlib.import_module("ezdxf.addons.drawing.config")
    return config.Configuration(
        background_policy=config.BackgroundPolicy.WHITE, color_policy=config.ColorPolicy.COLOR
    )


def png_ok(path: Path) -> bool:
    """True when matplotlib's image reader opens the PNG."""
    image = importlib.import_module("matplotlib.image")
    return image.imread(path).size > 0


def view_png(shape: Any, path: Path) -> None:
    """Shaded isometric PNG of a solid: tessellate, Lambert, Poly3DCollection."""
    matplotlib = importlib.import_module("matplotlib")
    matplotlib.use("Agg", force=True)
    pyplot = importlib.import_module("matplotlib.pyplot")
    collections = importlib.import_module("mpl_toolkits.mplot3d.art3d")
    vertices, triangles = shape.tessellate(VIEW_TOLERANCE)
    points = [(vertex.x, vertex.y, vertex.z) for vertex in vertices]
    faces = [[points[index] for index in triangle] for triangle in triangles]
    figure = pyplot.figure(figsize=(VIEW_WIDTH / 100, VIEW_HEIGHT / 100), dpi=100)
    axis = figure.add_subplot(111, projection="3d")
    collection = collections.Poly3DCollection(faces, facecolors=_shades(faces), edgecolors="none")
    axis.add_collection3d(collection)
    _set_limits(axis, points)
    axis.set_axis_off()
    figure.savefig(path, dpi=100, facecolor="white")
    pyplot.close(figure)


def _shades(faces: list[list[tuple[float, float, float]]]) -> list[tuple[float, float, float]]:
    """One Lambert shade per face: a fixed light on a steel-grey surface."""
    light = _normalise(LIGHT_DIRECTION)
    shades: list[tuple[float, float, float]] = []
    for points in faces:
        normal = _normalise(_cross(_sub(points[1], points[0]), _sub(points[2], points[0])))
        luminance = 0.25 + 0.65 * max(0.0, sum(a * b for a, b in zip(normal, light, strict=True)))
        shades.append((luminance, luminance, luminance))
    return shades


def _set_limits(axis: Any, points: list[tuple[float, float, float]]) -> None:
    """Equal aspect and a small margin around the tessellated points."""
    spans = [max(p[i] for p in points) - min(p[i] for p in points) for i in range(3)]
    centres = [(max(p[i] for p in points) + min(p[i] for p in points)) / 2 for i in range(3)]
    half = max(spans) / 2 * 1.05 if max(spans) > 0 else 1.0
    axis.set_box_aspect((1, 1, 1))
    axis.set_xlim(centres[0] - half, centres[0] + half)
    axis.set_ylim(centres[1] - half, centres[1] + half)
    axis.set_zlim(centres[2] - half, centres[2] + half)


def _normalise(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(value * value for value in vector)) or 1.0
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _sub(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (first[0] - second[0], first[1] - second[1], first[2] - second[2])


def _cross(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )
