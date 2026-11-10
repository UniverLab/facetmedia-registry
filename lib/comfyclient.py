"""The registry's shared ComfyUI client: server, flows, video probe and doctor.

The package-agnostic half of a ComfyUI package runner, pulled into the
environment as ``facet_lib.comfyclient`` and declared with the top-level
``uses`` key. Every function receives what used to come from a package's
module state as explicit parameters; none of them reads a package's own
files. The calling package keeps only its flow and capability names, its
size defaults, its model map and its thin entry-point wiring.

Requires: imageio-ffmpeg
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

#: The server facet starts for the verb; the fallback is the lab's own port.
DEFAULT_SERVER_URL = "http://127.0.0.1:8188"
HEALTH_TIMEOUT_S = 2.0
HEALTHY_STATUS = (200, 300)
HISTORY_TIMEOUT_S = 900.0
HISTORY_POLL_S = 0.5
NVIDIA_SMI_TIMEOUT_S = 4.0
ERROR_TAIL_CHARS = 2000
#: The lab's multipart boundary and timeout for posting an image.
UPLOAD_BOUNDARY = "----facet-upload"
UPLOAD_TIMEOUT_S = 60.0
FFMPEG_TIMEOUT_S = 300.0
#: Every FFmpeg call: no stdin, so a terminal keypress never cuts a probe.
FFMPEG_FLAGS = ("-nostdin", "-hide_banner")
#: FFmpeg's ``-i`` header: the stream's ``1280x704`` and its ``24 fps``.
VIDEO_STREAM = re.compile(r"Video: .*?, (\d+)x(\d+)")
VIDEO_RATE = re.compile(r"(\d+(?:\.\d+)?) fps")
#: The final ``frame=  49`` of a decode-to-null pass.
FRAME_COUNT = re.compile(r"frame=\s*(\d+)")


def manifest(package_dir: Path) -> dict[str, Any]:
    """The parsed package.toml, for the tool identity and the server pin."""
    return tomllib.loads((package_dir / "package.toml").read_text(encoding="utf-8"))


def tool(manifest: dict[str, Any]) -> dict[str, str]:
    """The manifest's tool identity, so records name the real tool."""
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def server_dir(manifest: dict[str, Any]) -> Path:
    """The checkout ``facet pull`` made, under ``<home>/servers/<name>/<version>``.

    ``FACET_MODELS`` is ``<home>/models/direct``, so two parents reach the
    facet home; the checkout's own directory is named after the short rev.
    """
    home = Path(os.environ.get("FACET_MODELS", "")).parent.parent
    rev = str(manifest["engine"]["server"]["rev"])
    return home / "servers" / str(manifest["name"]) / str(manifest["version"]) / rev[:12]


def checkout(manifest: dict[str, Any], pull_fix: str) -> Path:
    """The ComfyUI checkout; missing means facet has not pulled it yet."""
    directory = server_dir(manifest)
    if not (directory / "main.py").is_file():
        raise ValueError(f"{directory}: no ComfyUI checkout; run {pull_fix}")
    return directory


def link_models(req: Any, checkout: Path, model_dirs: dict[str, str]) -> None:
    """Link every model into the clone where ComfyUI looks, refreshed each run."""
    for model_id, relative in model_dirs.items():
        source = req.model_path(model_id)
        target = checkout / relative / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        target.symlink_to(source)


def flow(flows_dir: Path, name: str) -> dict[str, Any]:
    """The API graph of ``name``, shipped beside the runner as ``flows/<name>.json``."""
    return json.loads((flows_dir / f"{name}.json").read_text(encoding="utf-8"))


def values(flow: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """The flow's params first, then the entry: the lab's fill order."""
    params = flow.get("params")
    filled = params if isinstance(params, dict) else {}
    unknown = set(entry) - set(filled) - placeholders(flow["graph"])
    if unknown:
        raise ValueError(f"unknown keys {sorted(unknown)} for this flow")
    return {**filled, **entry}


def placeholders(value: Any) -> set[str]:
    """Every ``"$key"`` the graph fills, as the lab's ``placeholders`` does."""
    if isinstance(value, dict):
        return set().union(*(placeholders(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(placeholders(item) for item in value))
    if isinstance(value, str) and value.startswith("$"):
        return {value[1:]}
    return set()


def fill(value: Any, values: dict[str, Any]) -> Any:
    """Replace every ``"$key"`` with ``values[key]``, keeping the value's type."""
    if isinstance(value, dict):
        return {key: fill(item, values) for key, item in value.items()}
    if isinstance(value, list):
        return [fill(item, values) for item in value]
    if isinstance(value, str) and value.startswith("$"):
        name = value[1:]
        if name not in values:
            raise ValueError(f"the flow needs {name}, which the piece does not give")
        return values[name]
    return value


def server_url() -> str:
    return os.environ.get("FACET_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")


def open_url(url: str, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
    """One HTTP call: a JSON body on POST, none on GET."""
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(request, timeout=timeout)


def get_json(path: str, timeout: float = 30.0) -> Any:
    with open_url(server_url() + path, None, timeout) as response:
        return json.load(response)


def post_json(path: str, payload: dict[str, Any], timeout: float = 30.0) -> Any:
    with open_url(server_url() + path, payload, timeout) as response:
        return json.load(response)


def get_bytes(path: str, timeout: float = 60.0) -> bytes:
    with open_url(server_url() + path, timeout=timeout) as response:
        return response.read()


def upload_body(path: Path) -> bytes:
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


def upload(path: Path) -> str:
    """Upload ``path`` to the server's input folder; the name a LoadImage expects."""
    request = urllib.request.Request(
        server_url() + "/upload/image",
        data=upload_body(path),
        headers={"Content-Type": f"multipart/form-data; boundary={UPLOAD_BOUNDARY}"},
    )
    with urllib.request.urlopen(request, timeout=UPLOAD_TIMEOUT_S) as response:
        answer = json.load(response)
    name = answer.get("name") if isinstance(answer, dict) else None
    if not isinstance(name, str) or not name:
        raise RuntimeError(f"{path}: the server uploaded no name")
    subfolder = answer.get("subfolder")
    return f"{subfolder}/{name}" if subfolder else name


def submit(graph: dict[str, Any]) -> str:
    """POST the graph; ComfyUI answers the prompt id that owns the job."""
    try:
        answer = post_json("/prompt", {"prompt": graph})
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:ERROR_TAIL_CHARS]
        raise RuntimeError(f"ComfyUI rejected the flow: {detail}") from None
    prompt_id = answer.get("prompt_id") if isinstance(answer, dict) else None
    if not isinstance(prompt_id, str) or not prompt_id:
        raise RuntimeError("ComfyUI answered no prompt id")
    return prompt_id


def history(prompt_id: str) -> dict[str, Any]:
    """Poll /history until the job is complete, as the lab's script does."""
    path = f"/history/{urllib.parse.quote(prompt_id)}"
    deadline = time.monotonic() + HISTORY_TIMEOUT_S
    while time.monotonic() < deadline:
        answer = get_json(path)
        entry = answer.get(prompt_id) if isinstance(answer, dict) else None
        if isinstance(entry, dict) and entry.get("status", {}).get("completed") is not None:
            return entry
        time.sleep(HISTORY_POLL_S)
    raise RuntimeError(f"{prompt_id}: ComfyUI did not finish within {HISTORY_TIMEOUT_S:.0f} s")


def error_detail(status: dict[str, Any]) -> Any:
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


def images(history: dict[str, Any]) -> list[dict[str, Any]]:
    """The output images of a completed job; a failed job raises."""
    status = history.get("status")
    status = status if isinstance(status, dict) else {}
    if status.get("status_str") != "success":
        raise RuntimeError(f"generation failed: {error_detail(status)}")
    outputs = history.get("outputs")
    found = [
        image
        for output in (outputs if isinstance(outputs, dict) else {}).values()
        for image in output.get("images", [])
        if isinstance(image, dict)
    ]
    if not found:
        raise RuntimeError("generation finished without an image")
    return found


def ffmpeg_exe() -> str:
    """The FFmpeg binary ``imageio-ffmpeg`` ships; the package depends on it."""
    return str(imageio_ffmpeg.get_ffmpeg_exe())


def ffmpeg_output(*args: str) -> str:
    """One FFmpeg pass, its stdout and stderr together: the info it prints."""
    done = subprocess.run(
        [ffmpeg_exe(), *FFMPEG_FLAGS, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=FFMPEG_TIMEOUT_S,
    )
    return done.stdout + done.stderr


def probe_video(path: Path) -> dict[str, Any]:
    """The MP4's width, height, frame rate and frame count, as FFmpeg reads them."""
    header = ffmpeg_output("-i", str(path))
    stream = VIDEO_STREAM.search(header)
    rate = VIDEO_RATE.search(header)
    if stream is None or rate is None:
        raise ValueError(f"{path}: FFmpeg read no video stream")
    counted = ffmpeg_output("-i", str(path), "-map", "0:v:0", "-f", "null", "-")
    frames = FRAME_COUNT.findall(counted)
    if not frames:
        raise ValueError(f"{path}: FFmpeg counted no frames")
    return {
        "width": int(stream.group(1)),
        "height": int(stream.group(2)),
        "fps": float(rate.group(1)),
        "frames": int(frames[-1]),
    }


def verify_video(path: Path, thresholds: dict[str, Any], fps_tolerance: float) -> dict[str, Any]:
    """The MP4 opens, at the thresholds' size, frame rate and frame count."""
    try:
        metrics = probe_video(path)
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
        and abs(metrics["fps"] - thresholds["fps"]) <= fps_tolerance
        and metrics["frames"] == thresholds["frames"]
    )
    return {
        "file": path.name,
        "passed": passed,
        "metrics": metrics,
        "thresholds": thresholds,
        "verifier": "ffmpeg",
    }


def check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names what fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def nvidia_smi(*args: str) -> subprocess.CompletedProcess[str] | None:
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


def healthy(url: str) -> bool:
    """True when ``url`` answers 2xx within the short health timeout."""
    try:
        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_S) as response:
            status: int = response.status
            return HEALTHY_STATUS[0] <= status < HEALTHY_STATUS[1]
    except (OSError, ValueError):
        return False


def doctor_gpu() -> dict[str, Any]:
    """nvidia-smi sees an NVIDIA GPU."""
    done = nvidia_smi("-L")
    if done is None:
        return check("gpu", False, "nvidia-smi cannot run", "install the NVIDIA driver")
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    ok = done.returncode == 0 and bool(lines)
    detail = lines[0] if ok else f"nvidia-smi exited {done.returncode} with no GPU"
    return check("gpu", ok, detail, "install the NVIDIA driver")


def doctor_gpu_free() -> dict[str, Any]:
    """No other process holds GPU memory: one model at a time."""
    if healthy(server_url() + "/system_stats"):
        return check("gpu_free", True, "the server facet started owns the GPU")
    done = nvidia_smi("--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader")
    if done is None:
        return check("gpu_free", False, "nvidia-smi cannot list compute apps", "check nvidia-smi")
    users = [line for line in done.stdout.splitlines() if line.strip()]
    ok = done.returncode == 0 and not users
    detail = "no other process holds GPU memory" if ok else "; ".join(users[:3])
    return check("gpu_free", ok, detail, "stop the other GPU job: one model at a time")


def doctor_models(req: Any, manifest: dict[str, Any], pull_fix: str) -> dict[str, Any]:
    """Every manifest model is downloaded with its declared byte count."""
    present: list[str] = []
    problems: list[str] = []
    models = manifest.get("models")
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
    return check("models", ok, detail, pull_fix)


def doctor_checkout(manifest: dict[str, Any], pull_fix: str) -> dict[str, Any]:
    """The pinned ComfyUI checkout exists with its main.py."""
    directory = server_dir(manifest)
    ok = (directory / "main.py").is_file()
    detail = f"ComfyUI checkout at {directory}" if ok else f"{directory}: no main.py"
    return check("checkout", ok, detail, pull_fix)


def doctor_server() -> dict[str, Any]:
    """Full depth: the server facet started for the doctor answers /system_stats."""
    url = server_url() + "/system_stats"
    ok = healthy(url)
    detail = f"{url} answers" if ok else f"{url} does not answer"
    return check("server", ok, detail, "run a piece so facet starts ComfyUI; check its log")
