# Prueba de eliminación de fondo

Usa U2NetP en CPU para generar una imagen PNG con alfa y una vista sobre checkerboard:

```bash
uv run remover.py
```

`medicion.json` registra tiempo, proveedor y porcentaje de píxeles transparentes. Revisar especialmente pelo, bordes finos y huecos antes de elegirlo para el catálogo.

`cutout.toml` y `paper.toml` son las piezas de ejemplo: ambas usan `lamina.png`, una copia de la misma lámina de máquina que ya viaja en `packages/ascii/examples/lamina.png` (recorte de 512 px), para que cada ejemplo corra solo.

El código de rembg es MIT ([repositorio](https://github.com/danielgatis/rembg)); los pesos U-2-Net son Apache-2.0 ([U-2-Net](https://github.com/xuebinqin/U-2-Net)). La prueba usa el modelo pequeño `u2netp` y CPU, no consume VRAM.
