# Img2img con FLUX.2 klein

```bash
facet run comfy.edit packages/comfy/examples/img2img.toml
```

El flujo `tools/comfy/flux2-klein-img2img.json` sube una image de referencia y usa `ReferenceLatent` para guiar una edición por instrucciones. La prueba produjo `iteracion-grabado.png` desde `flux2-klein-4b/ilustracion-editorial.png` en 22,7 s a 1344 × 768. Conserva personaje y encuadre y cambia la image a un grabado azul/crema. El grano y las líneas son ásperos, acordes al estilo pedido.

Este flujo sirve para iterar mediante instrucciones; no ofrece el control clásico de fuerza de denoise. Si se necesita controlar cuánto se conserva en una transformación gradual, hay que sumar un flujo latent img2img con denoise ajustable y compararlo por separado.
