"""The comfy package runner: still images from prompts with ComfyUI.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull). ``run`` links facet's models into the pinned ComfyUI
checkout, fills the selected flow's graph and downloads the PNGs it
produced; ``verify`` opens every PNG with Pillow and checks its pixel size;
``preview`` writes the image preview file; ``doctor`` checks the GPU, the
models and the checkout at ``quick`` and probes the server at ``full``.

ComfyUI itself is a ``[engine.server]``: facet clones the pinned revision,
builds its venv and starts ``main.py`` for the duration of the verb, passing
the free port and the base URL through ``{{port}}`` and ``FACET_SERVER_URL``.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import PIL.Image
from facet_runner_sdk import Request, Runner

runner = Runner()

#: The lab's flows, copied from the Grafics lab's ``tools/comfy/``.
FLOW_NAMES = ("z-image-turbo", "flux2-klein-4b")
DEFAULT_WORKFLOW = "z-image-turbo"
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 768
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


def _save(images: list[dict[str, Any]], name: str, out_dir: Path) -> list[Path]:
    """Download every output beside the piece; one image keeps the plain name."""
    saved: list[Path] = []
    for index, image in enumerate(images):
        query = urllib.parse.urlencode(
            {key: image[key] for key in ("filename", "subfolder", "type")}
        )
        suffix = Path(str(image["filename"])).suffix or ".png"
        stem = f"{name}{suffix}" if len(images) == 1 else f"{name}-{index + 1}{suffix}"
        target = out_dir / stem
        target.write_bytes(_bytes(f"/view?{query}"))
        saved.append(target)
    return saved


def _asset(entry: dict[str, Any], path: Path) -> dict[str, Any]:
    """One record: kind image, the entry as its params, the seed beside them."""
    seed = int(entry["seed"])
    return {
        "file": path.name,
        "name": str(entry["name"]),
        "kind": "image",
        "mime": "image/png",
        "properties": {
            "width": int(entry.get("width", DEFAULT_WIDTH)),
            "height": int(entry.get("height", DEFAULT_HEIGHT)),
            "seed": seed,
        },
        "params": dict(entry),
        "seed": seed,
        "inputs": [],
    }


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    if req.capability != "comfy.still":
        raise ValueError(f"unknown capability: {req.capability}")
    raw = dict(req.inputs).get("image")
    entries = raw if isinstance(raw, list) else []
    if not entries:
        raise ValueError("the piece has no image entries")
    workflow = str(dict(req.inputs).get("workflow", DEFAULT_WORKFLOW))
    if workflow not in FLOW_NAMES:
        raise ValueError(f"unknown workflow: {workflow}")
    _link_models(req)
    flow = _flow(workflow)
    assets: list[dict[str, Any]] = []
    for entry in entries:
        graph = _fill(flow["graph"], _values(flow, entry))
        images = _images(_history(_submit(graph)))
        for path in _save(images, str(entry["name"]), req.out_dir):
            print(f"{path.name} ok", flush=True)
            assets.append(_asset(entry, path))
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


def _verify_asset(entries: dict[str, dict[str, Any]], path: Path) -> dict[str, Any]:
    """The PNG opens and its pixel size equals the entry's width and height."""
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
    return {"assets": [_verify_asset(entries, path) for path in req.assets]}


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


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    entries = _entries(req)
    results: list[dict[str, Any]] = []
    for path in req.assets:
        data = _preview_data(_entry_for(entries, path), path)
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
