# /// script
# requires-python = ">=3.11"
# dependencies = ["ezdxf==1.4.4", "matplotlib==3.11.2"]
# ///
"""Plano 2D de un estudio de 6 × 4,5 m con ezdxf: muros, puerta con barrido, ventanas, mobiliario y cotas.
Exporta DXF (unidades: metros), SVG y PNG de vista previa, y audita el DXF.
Uso: uv run projects/prueba-cad/plano-estudio.py [salida-sin-extensión]
Es la misma prueba de campo que se le hizo a cadspec el 2026-10-09."""
import math
import sys
from pathlib import Path

import ezdxf
from ezdxf import colors
from ezdxf.addons.drawing import Frontend, RenderContext, layout, svg
from ezdxf.addons.drawing import matplotlib as draw_mpl
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration

DATA = {
    "ancho": 6.0,          # m, interior
    "fondo": 4.5,          # m, interior
    "muro": 0.15,          # m, espesor
    "puerta_x": 1.0,       # m, bisagra en el muro sur
    "puerta_ancho": 0.9,   # m
    "ventanas": {"ancho": 1.2, "n": 2},   # repartidas en el muro norte
    "mesa": {"centro": (4.2, 2.6), "radio": 0.5, "sillas": 4},
    "cama": {"origen": (0.3, 2.3), "ancho": 1.4, "largo": 2.0},
}
CAPAS = {  # nombre: (color verdadero, grosor de línea en centésimas de mm)
    "muros": ("#2b2b2b", 50),
    "aberturas": ("#2a78d6", 25),
    "mobiliario": ("#eb6834", 18),
    "cotas": ("#6b6b6b", 13),
    "textos": ("#2b2b2b", 13),
}

d = DATA
doc = ezdxf.new("R2018", setup=True, units=6)  # 6 = metros
for nombre, (hex_color, grosor) in CAPAS.items():
    capa = doc.layers.add(nombre, lineweight=grosor)
    capa.rgb = colors.RGB.from_hex(hex_color)  # color verdadero (código 420), no solo índice ACI
msp = doc.modelspace()
W, H, t = d["ancho"], d["fondo"], d["muro"]

# Muros: contorno exterior e interior; el hueco de la puerta corta el muro sur.
p0, p1 = d["puerta_x"], d["puerta_x"] + d["puerta_ancho"]
for off in (0.0, t):
    x0, y0, x1, y1 = -off, -off, W + off, H + off
    msp.add_lwpolyline([(p1, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0), (p0, y0)], dxfattribs={"layer": "muros"})
for x in (p0, p1):  # jambas
    msp.add_line((x, 0), (x, -t), dxfattribs={"layer": "muros"})

# Puerta: hoja abierta 90° y su barrido.
msp.add_line((p0, 0), (p0, d["puerta_ancho"]), dxfattribs={"layer": "aberturas"})
msp.add_arc((p0, 0), d["puerta_ancho"], 0, 90, dxfattribs={"layer": "aberturas"})

# Ventanas repartidas a partes iguales en el muro norte (matriz lineal).
v = d["ventanas"]
paso = W / v["n"]
for i in range(v["n"]):
    cx = paso * (i + 0.5)
    a, b = cx - v["ancho"] / 2, cx + v["ancho"] / 2
    msp.add_lwpolyline([(a, H), (b, H), (b, H + t), (a, H + t)], close=True, dxfattribs={"layer": "aberturas"})
    msp.add_line((a, H + t / 2), (b, H + t / 2), dxfattribs={"layer": "aberturas"})

# Mesa redonda con sillas en matriz polar.
m = d["mesa"]
msp.add_circle(m["centro"], m["radio"], dxfattribs={"layer": "mobiliario"})
for i in range(m["sillas"]):
    ang = 2 * math.pi * i / m["sillas"] + math.pi / 4
    cx = m["centro"][0] + (m["radio"] + 0.3) * math.cos(ang)
    cy = m["centro"][1] + (m["radio"] + 0.3) * math.sin(ang)
    s = 0.2
    pts = [(cx + s * math.cos(ang + k * math.pi / 2 + math.pi / 4) * math.sqrt(2),
            cy + s * math.sin(ang + k * math.pi / 2 + math.pi / 4) * math.sqrt(2)) for k in range(4)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "mobiliario"})

# Cama con almohada.
c = d["cama"]
(cx0, cy0), cw, cl = c["origen"], c["ancho"], c["largo"]
msp.add_lwpolyline([(cx0, cy0), (cx0 + cw, cy0), (cx0 + cw, cy0 + cl), (cx0, cy0 + cl)], close=True,
                   dxfattribs={"layer": "mobiliario"})
msp.add_lwpolyline([(cx0 + 0.1, cy0 + cl - 0.45), (cx0 + cw - 0.1, cy0 + cl - 0.45),
                    (cx0 + cw - 0.1, cy0 + cl - 0.1), (cx0 + 0.1, cy0 + cl - 0.1)], close=True,
                   dxfattribs={"layer": "mobiliario"})

# Cotas interiores y de la puerta.
estilo = doc.dimstyles.get("EZDXF")
estilo.dxf.dimtxt = 0.15   # alto del texto en m
estilo.dxf.dimasz = 0.1    # flechas
estilo.dxf.dimdec = 2
estilo.dxf.dimzin = 0    # sin suprimir ceros: 0,90 y 6,00, no ,9 y 6
estilo.dxf.dimlfac = 1   # el estilo EZDXF trae 100 (m → cm); aquí las cotas van en metros
estilo.dxf.dimdsep = ord(",")  # separador decimal español
cota = {"dimstyle": "EZDXF", "dxfattribs": {"layer": "cotas"}}
msp.add_linear_dim(base=(0, -0.8), p1=(0, 0), p2=(W, 0), **cota).render()
msp.add_linear_dim(base=(W + 0.8, 0), p1=(W, 0), p2=(W, H), angle=90, **cota).render()
msp.add_linear_dim(base=(0, -0.45), p1=(p0, 0), p2=(p1, 0), **cota).render()

msp.add_text("ESTUDIO", height=0.25, dxfattribs={"layer": "textos"}).set_placement(
    (W / 2, H / 2 - 0.6), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
msp.add_text(f"{W * H:.2f} m²".replace(".", ","), height=0.15, dxfattribs={"layer": "textos"}).set_placement(
    (W / 2, H / 2 - 0.95), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

salida = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_suffix(""))
doc.saveas(salida.with_suffix(".dxf"))

# Auditoría: lo que un lector estricto (AutoCAD, ODA) rechazaría.
releido = ezdxf.readfile(salida.with_suffix(".dxf"))
auditoria = releido.audit()
print(f"DXF  {salida.with_suffix('.dxf')}  ({len(releido.modelspace())} entidades, "
      f"{len(auditoria.errors)} errores, {len(auditoria.fixes)} reparaciones en la auditoría)")

# Vista previa: fondo blanco y los colores de cada capa tal cual.
config = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR)
backend = svg.SVGBackend()
Frontend(RenderContext(releido), backend, config=config).draw_layout(releido.modelspace())
pagina = layout.Page(0, 0, layout.Units.mm, margins=layout.Margins.all(10))
salida.with_suffix(".svg").write_text(backend.get_string(pagina))
print(f"SVG  {salida.with_suffix('.svg')}")
draw_mpl.qsave(releido.modelspace(), str(salida.with_suffix(".png")), bg="#FFFFFF", dpi=200, config=config)
print(f"PNG  {salida.with_suffix('.png')}")
