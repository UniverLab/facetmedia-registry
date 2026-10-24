# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["cadquery==2.8.0"]
# ///
"""Escuadra de montaje en L, paramétrica, con CadQuery: patrón de referencia para piezas 3D.
Exporta STEP (CAD), STL (impresión 3D) y una vista SVG de líneas. Corre nativo en Linux.
Verificada: volumen 20.806 mm³ (cálculo a mano 20.805) y centros de agujero en (45, 20, 2,5) y (2,5, 20, 35);
la misma pieza en FreeCAD está en escuadra-freecad.py.
Uso: uv run projects/prueba-cad/escuadra.py [salida-sin-extensión]"""
import sys
from pathlib import Path

import cadquery as cq

DATA = {
    "ancho": 40.0,          # mm, a lo largo del pliegue
    "ala_base": 60.0,       # mm, ala horizontal
    "ala_pared": 50.0,      # mm, ala vertical
    "espesor": 5.0,         # mm
    "radio_interior": 4.0,  # mm, redondeo del pliegue por dentro
    "diametro_agujero": 6.5,  # mm, para tornillo M6
    "margen_agujero": 15.0,   # mm, desde el extremo de cada ala
}
d = DATA

# Perfil en L en el plano XZ, extruido a lo ancho (Y).
perfil = (cq.Workplane("XZ")
          .polyline([(0, 0), (d["ala_base"], 0), (d["ala_base"], d["espesor"]), (d["espesor"], d["espesor"]),
                     (d["espesor"], d["ala_pared"]), (0, d["ala_pared"])]).close()
          .extrude(-d["ancho"]))
# Redondeo interior: la única arista paralela a Y en x = z = espesor.
escuadra = perfil.edges("|Y").edges(cq.selectors.NearestToPointSelector((d["espesor"], d["ancho"] / 2, d["espesor"]))) \
    .fillet(d["radio_interior"])
# Agujeros en coordenadas absolutas (un agujero ubicado relativo a una cara no cambia el volumen si queda
# mal puesto, así que nada lo delataría): uno por ala, centrados a lo ancho.
r, t, V = d["diametro_agujero"] / 2, d["espesor"], cq.Vector
agujero_base = cq.Solid.makeCylinder(r, 3 * t, V(d["ala_base"] - d["margen_agujero"], d["ancho"] / 2, -t), V(0, 0, 1))
agujero_pared = cq.Solid.makeCylinder(r, 3 * t, V(-t, d["ancho"] / 2, d["ala_pared"] - d["margen_agujero"]), V(1, 0, 0))
escuadra = escuadra.cut(agujero_base).cut(agujero_pared)

solido = escuadra.val()
if not solido.isValid():
    raise RuntimeError("La geometría resultante no es válida")

salida = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_suffix(""))
cq.exporters.export(escuadra, str(salida.with_suffix(".step")))
cq.exporters.export(escuadra, str(salida.with_suffix(".stl")), tolerance=0.05, angularTolerance=0.2)
cq.exporters.export(escuadra, str(salida.with_suffix(".svg")),
                    opt={"projectionDir": (1.2, -1, 0.8), "showHidden": False, "width": 600, "height": 450})
print(f"volumen {solido.Volume():.0f} mm³ · caras {len(solido.Faces())}")
for ext in ("step", "stl", "svg"):
    print(f"{ext.upper():4} {salida.with_suffix('.' + ext)}")
