# The ComfyUI server

facet treats ComfyUI as an `[engine.server]` declared in `package.toml`;
the runner never starts or configures it by hand.

## Pin and pull

`facet pull comfy` clones `https://github.com/comfyanonymous/ComfyUI.git`
at the pinned revision `3c1b7a17fdf239d35ce98cc777756f572d089795` into the
facet home, builds its venv from the checkout's `requirements.txt`, and
downloads the ten manifest models next to it (about 34.3 GB; the shared Qwen
clip downloads once). Later runs are offline.

## Launch

For the duration of a verb facet starts the server with the argv from
`[engine.server].launch`:

```
python main.py --listen 127.0.0.1 --port <free port> --disable-pinned-memory
```

`--disable-pinned-memory` is package-wide, not per-flow: the Wan flow peaked
at 18 of 19 GB of RAM without it, and it changes nothing for the still
flows.

## Reaching it

The runner reaches the server through `FACET_SERVER_URL` (default
`http://127.0.0.1:8188`, matching ComfyUI's own default port). The health
check is `GET /system_stats` — the manifest's `health_url` is
`http://127.0.0.1:{{port}}/system_stats` with the free port substituted.
Uploads go to `POST /upload/image` (multipart, `overwrite` set), the graph to
`POST /prompt`, and results are fetched from `/history` and `/view`.

## Model symlinks

At run start the runner links each facet model into the checkout where
ComfyUI looks — the unet into `models/diffusion_models/`, the clip into
`models/text_encoders/`, the vae into `models/vae/` and the FastWan LoRA
into `models/loras/` — as symlinks, refreshed on every run. The link target
is the file `facet pull` downloaded under `models/direct`; nothing is
copied.
