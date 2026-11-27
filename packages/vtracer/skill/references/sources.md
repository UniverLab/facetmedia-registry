# Sources

The trace rules in `SKILL.md` rest on these public sources. Where a licence
allows it, at most one short line is quoted; everything else is a paraphrased
fact or practice.

| Source | URL | Maintainer | Licence | Taken |
|---|---|---|---|---|
| VisionCortex/VTracer README | https://github.com/visioncortex/VTracer | VisionCortex | MIT | Raster-to-vector on CPU: `colormode` (color/binary), path fitting (`spline`/`polygon`/`none`), speckle filter and colour precision convert pixels to SVG paths. Paraphrased. |
| vtracer-py docs | https://github.com/visioncortex/VTracer | VisionCortex | MIT | `convert_image_to_svg_py(image_path, out_path, colormode, mode, filter_speckle, color_precision, ...)` with `None` keeping each default. Paraphrased. |
| SVG 1.1 paths | https://www.w3.org/TR/SVG11/paths.html | W3C | W3C Document License | Path data scales without loss, so flat shapes stay sharp at any zoom while traced noise scales with them. Facts only. |
