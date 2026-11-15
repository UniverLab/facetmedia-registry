# Background removal test

Uses U2NetP on CPU to produce an alpha PNG and a checkerboard view:

```bash
uv run remove.py
```

`measurement.json` records time, provider and transparent pixel share. Check hair, thin edges and holes especially before picking it for the catalogue.

`cutout.toml` and `paper.toml` are the example pieces: both use `plate.png`, a copy of the same machine plate that already ships in `packages/ascii/examples/plate.png` (512 px crop), so each example runs alone.

The rembg code is MIT ([repository](https://github.com/danielgatis/rembg)); the U-2-Net weights are Apache-2.0 ([U-2-Net](https://github.com/xuebinqin/U-2-Net)). The test uses the small `u2netp` model and CPU, no VRAM.
