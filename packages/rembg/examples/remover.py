#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["rembg[cpu]==2.0.67", "pillow==11.3.0"]
# ///
"""Quita el fondo de una imagen con rembg/U2Net en CPU."""
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw
from rembg import new_session, remove

HERE = Path(__file__).resolve().parent
source = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE / "entrada.png"
output = HERE / "sin-fondo.png"
started = time.monotonic()
session = new_session("u2netp", providers=["CPUExecutionProvider"])
cutout = remove(Image.open(source).convert("RGBA"), session=session)
cutout.save(output)

# Vista sobre damero para inspeccionar bordes sin alterar el PNG con alfa.
checker = Image.new("RGB", cutout.size, "white")
draw = ImageDraw.Draw(checker)
tile = 32
for y in range(0, checker.height, tile):
    for x in range(0, checker.width, tile):
        if (x // tile + y // tile) % 2:
            draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill="#d8dde2")
checker.paste(cutout, mask=cutout.getchannel("A"))
checker.save(HERE / "vista-damero.png")

alpha = cutout.getchannel("A")
report = {
    "engine": "rembg 2.0.67 / U2NetP",
    "provider": "CPUExecutionProvider",
    "model_license": "Apache-2.0 (U-2-Net); rembg code MIT",
    "input": str(source),
    "size": list(cutout.size),
    "transparent_pixels_percent": round(100 * sum(1 for p in alpha.getdata() if p < 250) / (cutout.width * cutout.height), 2),
    "elapsed_seconds": round(time.monotonic() - started, 2),
    "output": output.name,
    "preview": "vista-damero.png",
}
(HERE / "medicion.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
