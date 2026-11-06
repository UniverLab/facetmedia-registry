"""The comfy package runner: stills, edits and clips with ComfyUI.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull). ``run`` links facet's models into the pinned ComfyUI
checkout, fills the selected flow's graph and downloads the PNGs (or the MP4
of a clip) it produced; an edit flow uploads the piece's reference image
first and a clip uploads each entry's first frame, filling ``$image`` with
the name the server answered; ``verify`` opens every PNG with Pillow (and
every clip with FFmpeg) and checks its pixel size (and its resolution, frame
rate and frame count); ``preview`` writes the preview file of the asset's
kind; ``doctor`` checks the GPU, the models and the checkout at ``quick`` and
probes the server at ``full``.

ComfyUI itself is a ``[engine.server]``: facet clones the pinned revision,
builds its venv and starts ``main.py`` for the duration of the verb, passing
the free port and the base URL through ``{{port}}`` and ``FACET_SERVER_URL``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import PIL.Image
from facet_runner_sdk import Request, Runner

runner = Runner()

#: The lab's flows, copied from the Grafics lab's ``tools/comfy/``.
FLOW_NAMES = ("z-image-turbo", "flux2-klein-4b")
DEFAULT_WORKFLOW = "z-image-turbo"
#: The one flow an edit uses: reference-guided, no denoise strength.
EDIT_FLOW = "flux2-klein-img2img"
#: The flows a clip uses: Wan 2.2 TI2V 5B animating what is inside a still.
CLIP_FLOW_NAMES = ("wan22-i2v", "wan22-i2v-rapido")
#: The half-time flow whose output is a draft, never a final render.
DRAFT_FLOW = "wan22-i2v-rapido"
#: What a draft asset's name carries before its suffix: ``<name>-borrador.mp4``.
DRAFT_SUFFIX = "borrador"
STILL_CAPABILITY = "comfy.still"
EDIT_CAPABILITY = "comfy.edit"
CLIP_CAPABILITY = "comfy.clip"
#: The lab's multipart boundary and timeout for posting an image.
UPLOAD_BOUNDARY = "----facet-upload"
UPLOAD_TIMEOUT_S = 60.0
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 768
DEFAULT_CLIP_WIDTH = 1280
DEFAULT_CLIP_HEIGHT = 704
DEFAULT_CLIP_LENGTH = 49
#: Wan 2.2 TI2V renders 24 fps; verify holds the clip to it.
VIDEO_FPS = 24
VIDEO_FPS_TOLERANCE = 0.01
FFMPEG_TIMEOUT_S = 300.0
#: Every FFmpeg call: no stdin, so a terminal keypress never cuts a probe.
FFMPEG_FLAGS = ("-nostdin", "-hide_banner")
#: FFmpeg's ``-i`` header: the stream's ``1280x704`` and its ``24 fps``.
VIDEO_STREAM = re.compile(r"Video: .*?, (\d+)x(\d+)")
VIDEO_RATE = re.compile(r"(\d+(?:\.\d+)?) fps")
#: The final ``frame=  49`` of a decode-to-null pass.
FRAME_COUNT = re.compile(r"frame=\s*(\d+)")
#: The server facet starts for the verb; the fallback is the lab's own port.
DEFAULT_SERVER_URL = "http://127.0.0.1:8188"
HEALTH_TIMEOUT_S = 2.0
HEALTHY_STATUS = (200, 300)
HISTORY_TIMEOUT_S = 900.0
HISTORY_POLL_S = 0.5
NVIDIA_SMI_TIMEOUT_S = 4.0
ERROR_TAIL_CHARS = 2000
PULL_FIX = "facet pull comfy"
#: Model id -> the directory of the checkout ComfyUI loads that kind from.
MODEL_DIRS = {
    "z-image-turbo-unet": "models/diffusion_models",
    "z-image-qwen-clip": "models/text_encoders",
    "z-image-vae": "models/vae",
    "flux2-klein-unet": "models/diffusion_models",
    "flux2-qwen-clip": "models/text_encoders",
    "flux2-klein-vae": "models/vae",
    "wan2v2-unet": "models/diffusion_models",
    "wan2v2-clip": "models/text_encoders",
    "wan2v2-vae": "models/vae",
    "wan2v2-fastwan-lora": "models/loras",
}


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity and the server pin."""
    return tomllib.loads((Path(__file__).parent / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    """The manifest's tool identity, so records name the real tool."""
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _server_dir() -> Path:
    """The checkout ``facet pull`` made, under ``<home>/servers/<name>/<version>``.

    ``FACET_MODELS`` is ``<home>/models/direct``, so two parents reach the
    facet home; the checkout's own directory is named after the short rev.
    """
    home = Path(os.environ.get("FACET_MODELS", "")).parent.parent
    manifest = _manifest()
    rev = str(manifest["engine"]["server"]["rev"])
    return home / "servers" / str(manifest["name"]) / str(manifest["version"]) / rev[:12]


def _checkout() -> Path:
    """The ComfyUI checkout; missing means facet has not pulled it yet."""
    checkout = _server_dir()
    if not (checkout / "main.py").is_file():
        raise ValueError(f"{checkout}: no ComfyUI checkout; run {PULL_FIX}")
    return checkout


def _link_models(req: Request) -> None:
    """Link every model into the clone where ComfyUI looks, refreshed each run."""
    checkout = _checkout()
    for model_id, relative in MODEL_DIRS.items():
        source = req.model_path(model_id)
        target = checkout / relative / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        target.symlink_to(source)


def _flow(name: str) -> dict[str, Any]:
    """The API graph of ``name``, shipped beside the runner as ``flows/<name>.json``."""
    path = Path(__file__).parent / "flows" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _values(flow: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """The flow's params first, then the entry: the lab's fill order."""
    params = flow.get("params")
    values = params if isinstance(params, dict) else {}
    unknown = set(entry) - set(values) - _placeholders(flow["graph"])
    if unknown:
        raise ValueError(f"unknown keys {sorted(unknown)} for this flow")
    return {**values, **entry}


def _placeholders(value: Any) -> set[str]:
    """Every ``"$key"`` the graph fills, as the lab's ``placeholders`` does."""
    if isinstance(value, dict):
        return set().union(*(_placeholders(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_placeholders(item) for item in value))
    if isinstance(value, str) and value.startswith("$"):
        return {value[1:]}
    return set()


def _fill(value: Any, values: dict[str, Any]) -> Any:
    """Replace every ``"$key"`` with ``values[key]``, keeping the value's type."""
    if isinstance(value, dict):
        return {key: _fill(item, values) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, values) for item in value]
    if isinstance(value, str) and value.startswith("$"):
        name = value[1:]
        if name not in values:
            raise ValueError(f"the flow needs {name}, which the piece does not give")
        return values[name]
    return value


def _server_url() -> str:
    return os.environ.get("FACET_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")


def _open(url: str, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
    """One HTTP call: a JSON body on POST, none on GET."""
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(request, timeout=timeout)


def _json(path: str, payload: dict[str, Any] | None = None) -> Any:
    with _open(_server_url() + path, payload) as response:
        return json.load(response)


def _bytes(path: str, timeout: float = 60.0) -> bytes:
    with _open(_server_url() + path, timeout=timeout) as response:
        return response.read()


def _upload_body(path: Path) -> bytes:
    """The lab's multipart body: ``overwrite`` first, then the file as ``image``."""
    head = (
        f"--{UPLOAD_BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
        "true\r\n"
        f"--{UPLOAD_BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    return head + path.read_bytes() + f"\r\n--{UPLOAD_BOUNDARY}--\r\n".encode()


def _upload(path: Path) -> str:
    """Upload ``path`` to the server's input folder; the name a LoadImage expects."""
    request = urllib.request.Request(
        _server_url() + "/upload/image",
        data=_upload_body(path),
        headers={"Content-Type": f"multipart/form-data; boundary={UPLOAD_BOUNDARY}"},
    )
    with urllib.request.urlopen(request, timeout=UPLOAD_TIMEOUT_S) as response:
        answer = json.load(response)
    name = answer.get("name") if isinstance(answer, dict) else None
    if not isinstance(name, str) or not name:
        raise RuntimeError(f"{path}: the server uploaded no name")
    subfolder = answer.get("subfolder")
    return f"{subfolder}/{name}" if subfolder else name


def _submit(graph: dict[str, Any]) -> str:
    """POST the graph; ComfyUI answers the prompt id that owns the job."""
    try:
        answer = _json("/prompt", {"prompt": graph})
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:ERROR_TAIL_CHARS]
        raise RuntimeError(f"ComfyUI rejected the flow: {detail}") from None
    prompt_id = answer.get("prompt_id") if isinstance(answer, dict) else None
    if not isinstance(prompt_id, str) or not prompt_id:
        raise RuntimeError("ComfyUI answered no prompt id")
    return prompt_id


def _history(prompt_id: str) -> dict[str, Any]:
    """Poll /history until the job is complete, as the lab's script does."""
    path = f"/history/{urllib.parse.quote(prompt_id)}"
    deadline = time.monotonic() + HISTORY_TIMEOUT_S
    while time.monotonic() < deadline:
        answer = _json(path)
        history = answer.get(prompt_id) if isinstance(answer, dict) else None
        if isinstance(history, dict) and history.get("status", {}).get("completed") is not None:
            return history
        time.sleep(HISTORY_POLL_S)
    raise RuntimeError(f"{prompt_id}: ComfyUI did not finish within {HISTORY_TIMEOUT_S:.0f} s")


def _error_detail(status: dict[str, Any]) -> Any:
    """The execution error's message, or the status itself when there is none."""
    messages = status.get("messages")
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, list) or not message or message[0] != "execution_error":
            continue
        payload = message[1:]
        if not payload:
            continue
        if isinstance(payload[0], dict):
            return payload[0].get("exception_message", "") or payload[0]
    return status


def _images(history: dict[str, Any]) -> list[dict[str, Any]]:
    """The output images of a completed job; a failed job raises."""
    status = history.get("status")
    status = status if isinstance(status, dict) else {}
    if status.get("status_str") != "success":
        raise RuntimeError(f"generation failed: {_error_detail(status)}")
    outputs = history.get("outputs")
    images = [
        image
        for output in (outputs if isinstance(outputs, dict) else {}).values()
        for image in output.get("images", [])
        if isinstance(image, dict)
    ]
    if not images:
        raise RuntimeError("generation finished without an image")
    return images


def _save(
    images: list[dict[str, Any]], name: str, out_dir: Path, draft: bool = False
) -> list[Path]:
    """Download every output beside the piece; one image keeps the plain name.

    A draft names its file ``<name>-borrador`` so a draft never passes for a
    final render.
    """
    saved: list[Path] = []
    marker = f"-{DRAFT_SUFFIX}" if draft else ""
    for index, image in enumerate(images):
        query = urllib.parse.urlencode(
            {key: image[key] for key in ("filename", "subfolder", "type")}
        )
        suffix = Path(str(image["filename"])).suffix or ".png"
        if len(images) == 1:
            stem = f"{name}{marker}{suffix}"
        else:
            stem = f"{name}{marker}-{index + 1}{suffix}"
        target = out_dir / stem
        target.write_bytes(_bytes(f"/view?{query}"))
        saved.append(target)
    return saved


def _asset(
    entry: dict[str, Any], path: Path, video: bool = False, draft: bool = False
) -> dict[str, Any]:
    """One record: the entry as its params, its seed beside them.

    A still is the ``image`` kind, a clip the ``video`` kind with the same
    measured width and height. A draft clip marks its properties so no
    assembly mistakes it for a final.
    """
    seed = int(entry["seed"])
    kind, mime = ("video", "video/mp4") if video else ("image", "image/png")
    properties: dict[str, Any] = {
        "width": int(entry.get("width", DEFAULT_CLIP_WIDTH if video else DEFAULT_WIDTH)),
        "height": int(entry.get("height", DEFAULT_CLIP_HEIGHT if video else DEFAULT_HEIGHT)),
        "seed": seed,
    }
    if draft:
        properties["draft"] = True
    return {
        "file": path.name,
        "name": str(entry["name"]),
        "kind": kind,
        "mime": mime,
        "properties": properties,
        "params": dict(entry),
        "seed": seed,
        "inputs": [],
    }


def _flow_name(capability: str, inputs: dict[str, Any]) -> str:
    """The flow the request asks for: an edit is always the img2img one."""
    if capability == EDIT_CAPABILITY:
        return EDIT_FLOW
    if capability == CLIP_CAPABILITY:
        names, fallback = CLIP_FLOW_NAMES, CLIP_FLOW_NAMES[0]
    else:
        names, fallback = FLOW_NAMES, DEFAULT_WORKFLOW
    workflow = str(inputs.get("workflow", fallback))
    if workflow not in names:
        raise ValueError(f"unknown workflow: {workflow}")
    return workflow


def _source_path(flow: dict[str, Any], inputs: dict[str, Any]) -> Path | None:
    """The piece's reference image, when the flow uploads one."""
    uploads = flow.get("uploads")
    if not isinstance(uploads, list) or "image" not in uploads:
        return None
    source = inputs.get("source")
    if not source:
        raise ValueError("the piece has no source image")
    return Path(str(source))


def _entry_list(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """The piece's ``image`` array, one dict per entry."""
    raw = inputs.get("image")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _entry_image(req: Request, entry: dict[str, Any]) -> Path:
    """A clip entry's first frame; the core resolves it, this keeps one relative."""
    path = Path(str(entry["image"]))
    return path if path.is_absolute() else req.piece_dir / path


def _upload_entry(req: Request, entry: dict[str, Any]) -> str:
    """Upload one clip's first frame; the server's name is what LoadImage wants."""
    source = _entry_image(req, entry)
    uploaded = _upload(source)
    print(f"{source.name} uploaded as {uploaded}", flush=True)
    return uploaded


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    if req.capability not in (STILL_CAPABILITY, EDIT_CAPABILITY, CLIP_CAPABILITY):
        raise ValueError(f"unknown capability: {req.capability}")
    inputs = dict(req.inputs)
    entries = _entry_list(inputs)
    if not entries:
        raise ValueError("the piece has no image entries")
    video = req.capability == CLIP_CAPABILITY
    flow_name = _flow_name(req.capability, inputs)
    flow = _flow(flow_name)
    draft = flow_name == DRAFT_FLOW
    source = None if video else _source_path(flow, inputs)
    _link_models(req)
    uploaded = _upload(source) if source is not None else ""
    if source is not None:
        print(f"{source.name} uploaded as {uploaded}", flush=True)
    assets: list[dict[str, Any]] = []
    for entry in entries:
        values = _values(flow, entry)
        if video:
            uploaded = _upload_entry(req, entry)
        if source is not None or video:
            values["image"] = uploaded
        graph = _fill(flow["graph"], values)
        images = _images(_history(_submit(graph)))
        for path in _save(images, str(entry["name"]), req.out_dir, draft):
            print(f"{path.name} ok", flush=True)
            assets.append(_asset(entry, path, video, draft))
    return {"tool": _tool(), "assets": assets}


def _entries(req: Request) -> dict[str, dict[str, Any]]:
    """The image entries by name: the piece's list, or one record's params.

    ``run`` and its verify get the piece's ``image`` array; ``facet check``
    and ``facet preview`` pass the record's params for one asset, which are
    the entry itself.
    """
    raw = dict(req.inputs).get("image")
    items = raw if isinstance(raw, list) else [req.inputs]
    return {str(item.get("name")): item for item in items if isinstance(item, dict)}


def _entry_for(entries: dict[str, dict[str, Any]], path: Path) -> dict[str, Any]:
    """The entry that produced ``path``: its own name, else the first entry."""
    for name, entry in entries.items():
        if path.stem == name or path.stem.startswith(f"{name}-"):
            return entry
    return next(iter(entries.values()), {})


def _size(path: Path) -> tuple[int, int]:
    with PIL.Image.open(path) as image:
        width, height = image.size
    return int(width), int(height)


def _ffmpeg_exe() -> str:
    """The FFmpeg binary ``imageio-ffmpeg`` ships; the package depends on it."""
    return str(imageio_ffmpeg.get_ffmpeg_exe())


def _ffmpeg_output(*args: str) -> str:
    """One FFmpeg pass, its stdout and stderr together: the info it prints."""
    done = subprocess.run(
        [_ffmpeg_exe(), *FFMPEG_FLAGS, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=FFMPEG_TIMEOUT_S,
    )
    return done.stdout + done.stderr


def _probe_video(path: Path) -> dict[str, Any]:
    """The MP4's width, height, frame rate and frame count, as FFmpeg reads them."""
    header = _ffmpeg_output("-i", str(path))
    stream = VIDEO_STREAM.search(header)
    rate = VIDEO_RATE.search(header)
    if stream is None or rate is None:
        raise ValueError(f"{path}: FFmpeg read no video stream")
    counted = _ffmpeg_output("-i", str(path), "-map", "0:v:0", "-f", "null", "-")
    frames = FRAME_COUNT.findall(counted)
    if not frames:
        raise ValueError(f"{path}: FFmpeg counted no frames")
    return {
        "width": int(stream.group(1)),
        "height": int(stream.group(2)),
        "fps": float(rate.group(1)),
        "frames": int(frames[-1]),
    }


def _verify_video(entries: dict[str, dict[str, Any]], path: Path) -> dict[str, Any]:
    """The MP4 opens, at the entry's size, 24 fps and the entry's frame count."""
    entry = _entry_for(entries, path)
    thresholds: dict[str, Any] = {
        "width": int(entry.get("width", DEFAULT_CLIP_WIDTH)),
        "height": int(entry.get("height", DEFAULT_CLIP_HEIGHT)),
        "fps": VIDEO_FPS,
        "frames": int(entry.get("length", DEFAULT_CLIP_LENGTH)),
    }
    try:
        metrics = _probe_video(path)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"error": str(exc)},
            "thresholds": thresholds,
            "verifier": "ffmpeg",
        }
    passed = (
        metrics["width"] == thresholds["width"]
        and metrics["height"] == thresholds["height"]
        and abs(metrics["fps"] - VIDEO_FPS) <= VIDEO_FPS_TOLERANCE
        and metrics["frames"] == thresholds["frames"]
    )
    return {
        "file": path.name,
        "passed": passed,
        "metrics": metrics,
        "thresholds": thresholds,
        "verifier": "ffmpeg",
    }


def _verify_asset(
    entries: dict[str, dict[str, Any]], path: Path, video: bool = False
) -> dict[str, Any]:
    """A clip's MP4 is probed with FFmpeg; a still's PNG with Pillow."""
    if video:
        return _verify_video(entries, path)
    entry = _entry_for(entries, path)
    expected_width = int(entry.get("width", DEFAULT_WIDTH))
    expected_height = int(entry.get("height", DEFAULT_HEIGHT))
    thresholds = {"width": expected_width, "height": expected_height}
    try:
        width, height = _size(path)
    except OSError as exc:
        return {
            "file": path.name,
            "passed": False,
            "metrics": {"error": str(exc)},
            "thresholds": thresholds,
            "verifier": "pillow",
        }
    passed = width == expected_width and height == expected_height
    return {
        "file": path.name,
        "passed": passed,
        "metrics": {"width": width, "height": height},
        "thresholds": thresholds,
        "verifier": "pillow",
    }


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    entries = _entries(req)
    video = req.capability == CLIP_CAPABILITY
    return {"assets": [_verify_asset(entries, path, video) for path in req.assets]}


def _preview_data(entry: dict[str, Any], path: Path) -> dict[str, Any]:
    """The image schema's fields, with the size measured from the PNG."""
    width, height = _size(path)
    name = str(entry.get("name", path.stem))
    seed = int(entry.get("seed", 0))
    return {
        "preview": 1,
        "kind": "image",
        "summary": f"{name} · {width}×{height} · seed {seed}",
        "name": name,
        "prompt": str(entry.get("prompt", "")),
        "seed": seed,
        "width": width,
        "height": height,
    }


def _preview_video(entry: dict[str, Any], path: Path) -> dict[str, Any]:
    """The video schema's fields, with the probe's measurements of the MP4."""
    probe = _probe_video(path)
    name = str(entry.get("name", path.stem))
    seed = int(entry.get("seed", 0))
    fps = int(round(float(probe["fps"])))
    summary = (
        f"{name} · {probe['width']}×{probe['height']} · "
        f"{probe['frames']} frames · {fps} fps · seed {seed}"
    )
    return {
        "preview": 1,
        "kind": "video",
        "summary": summary,
        "name": name,
        "prompt": str(entry.get("prompt", "")),
        "seed": seed,
        "width": probe["width"],
        "height": probe["height"],
        "length": probe["frames"],
        "fps": fps,
    }


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    entries = _entries(req)
    video = req.capability == CLIP_CAPABILITY
    results: list[dict[str, Any]] = []
    for path in req.assets:
        entry = _entry_for(entries, path)
        data = _preview_video(entry, path) if video else _preview_data(entry, path)
        preview_name = f"{path.name}.preview.json"
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        results.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": results}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names what fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _nvidia_smi(*args: str) -> subprocess.CompletedProcess[str] | None:
    """One nvidia-smi query, or ``None`` when the command cannot run."""
    try:
        return subprocess.run(
            ["nvidia-smi", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=NVIDIA_SMI_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _healthy(url: str) -> bool:
    """True when ``url`` answers 2xx within the short health timeout."""
    try:
        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_S) as response:
            status: int = response.status
            return HEALTHY_STATUS[0] <= status < HEALTHY_STATUS[1]
    except (OSError, ValueError):
        return False


def _doctor_gpu() -> dict[str, Any]:
    """nvidia-smi sees an NVIDIA GPU."""
    done = _nvidia_smi("-L")
    if done is None:
        return _check("gpu", False, "nvidia-smi cannot run", "install the NVIDIA driver")
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    ok = done.returncode == 0 and bool(lines)
    detail = lines[0] if ok else f"nvidia-smi exited {done.returncode} with no GPU"
    return _check("gpu", ok, detail, "install the NVIDIA driver")


def _doctor_gpu_free() -> dict[str, Any]:
    """No other process holds GPU memory: one model at a time."""
    if _healthy(_server_url() + "/system_stats"):
        return _check("gpu_free", True, "the server facet started owns the GPU")
    done = _nvidia_smi("--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader")
    if done is None:
        return _check("gpu_free", False, "nvidia-smi cannot list compute apps", "check nvidia-smi")
    users = [line for line in done.stdout.splitlines() if line.strip()]
    ok = done.returncode == 0 and not users
    detail = "no other process holds GPU memory" if ok else "; ".join(users[:3])
    return _check("gpu_free", ok, detail, "stop the other GPU job: one model at a time")


def _doctor_models(req: Request) -> dict[str, Any]:
    """Every manifest model is downloaded with its declared byte count."""
    present: list[str] = []
    problems: list[str] = []
    models = _manifest().get("models")
    for model in models if isinstance(models, list) else []:
        model_id = str(model["id"])
        expected = int(model["bytes"])
        try:
            path = req.model_path(model_id)
            size = path.stat().st_size
        except KeyError:
            problems.append(f"{model_id}: not in the request")
            continue
        except OSError:
            problems.append(f"{model_id}: missing")
            continue
        if size == expected:
            present.append(model_id)
        else:
            problems.append(f"{model_id}: {size} of {expected} bytes")
    ok = not problems
    detail = f"{len(present)} model(s) present" if ok else "; ".join(problems)
    return _check("models", ok, detail, PULL_FIX)


def _doctor_checkout() -> dict[str, Any]:
    """The pinned ComfyUI checkout exists with its main.py."""
    checkout = _server_dir()
    ok = (checkout / "main.py").is_file()
    detail = f"ComfyUI checkout at {checkout}" if ok else f"{checkout}: no main.py"
    return _check("checkout", ok, detail, PULL_FIX)


def _doctor_server() -> dict[str, Any]:
    """Full depth: the server facet started for the doctor answers /system_stats."""
    url = _server_url() + "/system_stats"
    ok = _healthy(url)
    detail = f"{url} answers" if ok else f"{url} does not answer"
    return _check("server", ok, detail, "run a piece so facet starts ComfyUI; check its log")


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    checks = [_doctor_gpu(), _doctor_gpu_free(), _doctor_models(req), _doctor_checkout()]
    if req.depth == "full":
        checks.append(_doctor_server())
    return {"checks": checks}


runner.main()
