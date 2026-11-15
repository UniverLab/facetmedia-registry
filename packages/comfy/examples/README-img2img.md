# Img2img with FLUX.2 klein

```bash
facet run comfy.edit packages/comfy/examples/img2img.toml
```

The `tools/comfy/flux2-klein-img2img.json` flow uploads one reference image and uses `ReferenceLatent` to guide an instruction edit. The test produced `print-iteration.png` from `flux2-klein-4b/editorial-illustration.png` in 22.7 s at 1344 × 768. It keeps the character and framing and turns the image into an indigo-and-cream engraving. The grain and lines are rough, as the style asks.

This flow serves to iterate by instruction; it offers no classic denoise strength. To control how much is kept in a gradual transformation, add a latent img2img flow with adjustable denoise and compare it separately.
