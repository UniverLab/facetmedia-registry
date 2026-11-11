# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["cadquery==2.8.0"]
# ///
"""The lab's study as a CadQuery Assembly, exported as glTF for blender.photo.

Each piece is one Assembly element, and its name is the material prefix
``render.py`` matches: muros, piso, vidrio-*, cama, almohada, mesa, sillas.
It models in mm, so the glTF carries millimeters and the blender runner
scales it to metres (x0.001).

Usage: ``uv run packages/blender/examples/estudio.py`` writes ``estudio.glb``
beside this file.
"""

import json
import math
import struct
from pathlib import Path

import cadquery as cq

DATA = {
    "ancho": 6.0,
    "fondo": 4.5,
    "muro": 0.15,
    "alto": 2.6,
    "losa": 0.12,
    "puerta": {"x": 1.0, "ancho": 0.9, "alto": 2.1},
    "ventanas": {"n": 2, "ancho": 1.2, "antepecho": 0.9, "alto": 1.2},
    "cama": {"x": 0.3, "y": 2.3, "ancho": 1.4, "largo": 2.0, "alto": 0.45},
    "mesa": {"x": 4.2, "y": 2.6, "radio": 0.5, "alto": 0.75},
    "sillas": 4,
}
MM = 1000.0
d = DATA


def caja(x, y, z, dx, dy, dz):
    """Box from its minimum corner, in metres."""
    return (
        cq.Workplane("XY")
        .box(dx * MM, dy * MM, dz * MM, centered=False)
        .translate((x * MM, y * MM, z * MM))
    )


W, H, t, h = d["ancho"], d["fondo"], d["muro"], d["alto"]
muros = caja(-t, -t, 0, W + 2 * t, H + 2 * t, h).cut(caja(0, 0, 0, W, H, h))
p = d["puerta"]
muros = muros.cut(caja(p["x"], -t - 0.01, 0, p["ancho"], t + 0.02, p["alto"]))
v = d["ventanas"]
vidrios = []
for i in range(v["n"]):
    cx = W / v["n"] * (i + 0.5)
    muros = muros.cut(
        caja(cx - v["ancho"] / 2, H - 0.01, v["antepecho"], v["ancho"], t + 0.02, v["alto"])
    )
    vidrios.append(
        caja(cx - v["ancho"] / 2, H + t / 2 - 0.01, v["antepecho"], v["ancho"], 0.02, v["alto"])
    )

piso = caja(-t, -t, -d["losa"], W + 2 * t, H + 2 * t, d["losa"])
c = d["cama"]
cama = caja(c["x"], c["y"], 0, c["ancho"], c["largo"], c["alto"])
almohada = caja(c["x"] + 0.1, c["y"] + c["largo"] - 0.5, c["alto"], c["ancho"] - 0.2, 0.4, 0.12)
m = d["mesa"]
mesa = (
    cq.Workplane("XY")
    .circle(m["radio"] * MM)
    .extrude(0.04 * MM)
    .translate((m["x"] * MM, m["y"] * MM, (m["alto"] - 0.04) * MM))
    .union(
        cq.Workplane("XY")
        .circle(0.05 * MM)
        .extrude((m["alto"] - 0.04) * MM)
        .translate((m["x"] * MM, m["y"] * MM, 0))
    )
)
sillas = None
for i in range(d["sillas"]):
    ang = 2 * math.pi * i / d["sillas"] + math.pi / 4
    sx, sy = m["x"] + 0.8 * math.cos(ang), m["y"] + 0.8 * math.sin(ang)
    silla = (
        caja(-0.2, -0.2, 0, 0.4, 0.4, 0.45)
        .union(caja(-0.2, 0.17, 0.45, 0.4, 0.03, 0.45))
        .rotate((0, 0, 0), (0, 0, 1), math.degrees(ang) + 90)
        .translate((sx * MM, sy * MM, 0))
    )
    sillas = silla if sillas is None else sillas.union(silla)

estudio = cq.Assembly(name="estudio")
estudio.add(piso, name="piso", color=cq.Color(0.55, 0.38, 0.24))
estudio.add(muros, name="muros", color=cq.Color(0.93, 0.92, 0.89))
for i, vidrio in enumerate(vidrios):
    estudio.add(vidrio, name=f"vidrio-{i + 1}", color=cq.Color(0.7, 0.85, 0.95, 0.3))
estudio.add(cama, name="cama", color=cq.Color(0.25, 0.35, 0.55))
estudio.add(almohada, name="almohada", color=cq.Color(0.95, 0.95, 0.95))
estudio.add(mesa, name="mesa", color=cq.Color(0.45, 0.3, 0.18))
estudio.add(sillas, name="sillas", color=cq.Color(0.92, 0.42, 0.2))



def matte(glb: Path) -> None:
    """Make every material dielectric and rough.

    CadQuery's glTF writer omits metallicFactor, and glTF reads a missing one
    as 1.0: a viewer without an environment map (the HyperFrames turntable)
    then draws the whole study black.
    """
    data = glb.read_bytes()
    magic, version, _ = struct.unpack("<III", data[:12])
    length, kind = struct.unpack("<II", data[12:20])
    doc = json.loads(data[20 : 20 + length])
    rest = data[20 + length :]
    for material in doc.get("materials", []):
        pbr = material.setdefault("pbrMetallicRoughness", {})
        pbr.setdefault("metallicFactor", 0.0)
        pbr.setdefault("roughnessFactor", 0.8)
    chunk = json.dumps(doc, separators=(",", ":")).encode()
    chunk += b" " * (-len(chunk) % 4)
    header = struct.pack("<III", magic, version, 20 + len(chunk) + len(rest))
    glb.write_bytes(header + struct.pack("<II", len(chunk), kind) + chunk + rest)


salida = Path(__file__).with_name("estudio.glb")
estudio.export(str(salida))
matte(salida)
print(f"GLB  {salida}  ({len(estudio.children)} piezas)")
