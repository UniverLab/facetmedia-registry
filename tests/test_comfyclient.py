"""The shared ComfyUI client, unit-tested without a server or a checkout.

The lib loads by file path so the test never imports the registry tooling.
HTTP helpers are observed through a fake ``open_url``/``urlopen`` that
captures the joined URL; the video probe is stubbed to fixed metrics.
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_lib() -> object:
    spec = importlib.util.spec_from_file_location("comfyclient", ROOT / "lib" / "comfyclient.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


comfyclient = _load_lib()

BASE = "http://127.0.0.1:8188"
PROMPT_ID = "stub-prompt"


class _JsonResponse:
    """A context manager yielding a readable JSON body, like ``urlopen``."""

    def __init__(self, payload: object):
        self._body = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self) -> io.BytesIO:
        return self._body

    def __exit__(self, *args: object) -> bool:
        return False


class _Req:
    def __init__(self, models: dict[str, Path]):
        self._models = models

    def model_path(self, model_id: str) -> Path:
        return self._models[model_id]


def _manifest_dict(rev: str = "3c1b7a17fdf239d35ce98cc777756f572d089795") -> dict[str, object]:
    return {
        "name": "comfy",
        "version": "0.1.0",
        "tool_name": "ComfyUI",
        "engine": {"server": {"rev": rev}},
        "models": [{"id": "m1", "bytes": 3}],
    }


def test_fill_replaces_placeholders_and_keeps_types() -> None:
    graph = {"a": "$prompt", "b": ["$seed", 2, {"c": "$prompt"}], "d": 7}
    assert comfyclient.fill(graph, {"prompt": "cup", "seed": 7}) == {
        "a": "cup",
        "b": [7, 2, {"c": "cup"}],
        "d": 7,
    }


def test_fill_missing_key_raises() -> None:
    with pytest.raises(ValueError, match="the flow needs seed"):
        comfyclient.fill({"a": "$seed"}, {"prompt": "cup"})


def test_placeholders_collects_every_key() -> None:
    graph = {"a": "$prompt", "b": ["$seed", {"c": "$prompt"}], "d": 1}
    assert comfyclient.placeholders(graph) == {"prompt", "seed"}


def test_values_merges_params_first_then_entry() -> None:
    flow = {"params": {"steps": 8, "seed": 1}, "graph": {"a": ["$steps", "$seed", "$prompt"]}}
    assert comfyclient.values(flow, {"seed": 7, "prompt": "cup"}) == {
        "steps": 8,
        "seed": 7,
        "prompt": "cup",
    }


def test_values_unknown_key_raises() -> None:
    flow = {"params": {"steps": 8}, "graph": {"a": "$steps"}}
    with pytest.raises(ValueError, match="unknown keys"):
        comfyclient.values(flow, {"nope": 1})


def test_error_detail_extracts_the_exception_message() -> None:
    status = {
        "status_str": "error",
        "messages": [["execution_error", {"exception_message": "OOM"}, {"x": 1}]],
    }
    assert comfyclient.error_detail(status) == "OOM"


def test_error_detail_without_an_error_returns_the_status() -> None:
    status: dict[str, object] = {"status_str": "error", "messages": []}
    assert comfyclient.error_detail(status) == status


def test_images_raises_on_a_failed_job_with_its_message() -> None:
    history = {
        "status": {
            "status_str": "error",
            "messages": [["execution_error", {"exception_message": "OOM"}]],
        },
        "outputs": {},
    }
    with pytest.raises(RuntimeError, match="OOM"):
        comfyclient.images(history)


def test_images_returns_the_outputs_of_a_finished_job() -> None:
    image = {"filename": "still.png", "subfolder": "", "type": "output"}
    history = {"status": {"status_str": "success"}, "outputs": {"save": {"images": [image]}}}
    assert comfyclient.images(history) == [image]


def test_images_raises_when_a_finished_job_has_no_image() -> None:
    with pytest.raises(RuntimeError, match="without an image"):
        comfyclient.images({"status": {"status_str": "success"}, "outputs": {}})


def test_submit_posts_the_graph_to_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_open(url: str, payload: object = None, timeout: float = 30.0) -> _JsonResponse:
        seen["url"] = url
        seen["payload"] = payload
        return _JsonResponse({"prompt_id": PROMPT_ID})

    monkeypatch.setattr(comfyclient, "open_url", fake_open)
    monkeypatch.setenv("FACET_SERVER_URL", BASE + "/")
    assert comfyclient.submit({"1": {"class_type": "Empty"}}) == PROMPT_ID
    assert seen["url"] == f"{BASE}/prompt"
    assert seen["payload"] == {"prompt": {"1": {"class_type": "Empty"}}}


def test_history_polls_history_id(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_open(url: str, payload: object = None, timeout: float = 30.0) -> _JsonResponse:
        seen.append(url)
        entry = {"status": {"completed": True, "status_str": "success"}, "outputs": {}}
        return _JsonResponse({PROMPT_ID: entry})

    monkeypatch.setattr(comfyclient, "open_url", fake_open)
    monkeypatch.setenv("FACET_SERVER_URL", BASE)
    assert comfyclient.history(PROMPT_ID)["status"]["status_str"] == "success"
    assert seen == [f"{BASE}/history/{PROMPT_ID}"]


def test_upload_posts_the_file_to_upload_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}
    source = tmp_path / "frame.png"
    source.write_bytes(b"pixels")

    def fake_urlopen(request: object, timeout: float = 60.0) -> _JsonResponse:
        assert isinstance(request, urllib.request.Request)
        seen["url"] = request.full_url
        seen["body"] = request.data
        return _JsonResponse({"name": "frame.png", "subfolder": "", "type": "input"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("FACET_SERVER_URL", BASE)
    assert comfyclient.upload(source) == "frame.png"
    assert seen["url"] == f"{BASE}/upload/image"
    assert isinstance(seen["body"], bytes) and b"pixels" in seen["body"]


def test_get_bytes_reads_from_the_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_open(url: str, payload: object = None, timeout: float = 30.0) -> _JsonResponse:
        seen.append(url)
        response = _JsonResponse({})
        response._body = io.BytesIO(b"bytes")
        return response

    monkeypatch.setattr(comfyclient, "open_url", fake_open)
    monkeypatch.setenv("FACET_SERVER_URL", BASE)
    assert comfyclient.get_bytes("/view?filename=still.png") == b"bytes"
    assert seen == [f"{BASE}/view?filename=still.png"]


def test_server_url_prefers_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FACET_SERVER_URL", BASE + "/")
    assert comfyclient.server_url() == BASE
    monkeypatch.delenv("FACET_SERVER_URL")
    assert comfyclient.server_url() == comfyclient.DEFAULT_SERVER_URL


def test_manifest_and_tool_parse_the_package_toml(tmp_path: Path) -> None:
    (tmp_path / "package.toml").write_text(
        'name = "comfy"\nversion = "0.1.0"\ntool_name = "ComfyUI"\n[engine.server]\nrev = "abc"\n',
        encoding="utf-8",
    )
    manifest = comfyclient.manifest(tmp_path)
    assert manifest["name"] == "comfy"
    assert comfyclient.tool(manifest) == {"name": "ComfyUI", "version": "0.1.0"}


def test_flow_loads_the_named_graph(tmp_path: Path) -> None:
    flows = tmp_path / "flows"
    flows.mkdir()
    (flows / "z.json").write_text('{"graph": {}, "params": {"a": 1}}', encoding="utf-8")
    assert comfyclient.flow(flows, "z") == {"graph": {}, "params": {"a": 1}}


def test_server_dir_derives_from_models_home_and_rev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FACET_MODELS", "/srv/a/very/long/facet/home/models/direct")
    directory = comfyclient.server_dir(_manifest_dict())
    assert directory == Path("/srv/a/very/long/facet/home/servers/comfy/0.1.0/3c1b7a17fdf2")


def test_checkout_missing_main_raises_with_the_fix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="facet pull comfy"):
        comfyclient.checkout(_manifest_dict(), "facet pull comfy")


def test_link_models_symlinks_and_refreshes(tmp_path: Path) -> None:
    source = tmp_path / "models" / "m1.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"m")
    checkout = tmp_path / "checkout"
    stale = checkout / "models" / "diffusion_models" / "m1.bin"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")
    comfyclient.link_models(_Req({"m1": source}), checkout, {"m1": "models/diffusion_models"})
    assert stale.is_symlink()
    assert stale.resolve() == source.resolve()


def test_verify_video_passes_on_matching_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = {"width": 1280, "height": 704, "fps": 24.0, "frames": 49}
    monkeypatch.setattr(comfyclient, "probe_video", lambda path: metrics)
    thresholds = {"width": 1280, "height": 704, "fps": 24, "frames": 49}
    verdict = comfyclient.verify_video(Path("clip.mp4"), thresholds, 0.01)
    assert verdict["passed"] is True
    assert verdict["metrics"] == metrics
    assert verdict["verifier"] == "ffmpeg"


@pytest.mark.parametrize(
    "metrics",
    [
        {"width": 640, "height": 704, "fps": 24.0, "frames": 49},
        {"width": 1280, "height": 704, "fps": 12.0, "frames": 49},
        {"width": 1280, "height": 704, "fps": 24.0, "frames": 25},
    ],
)
def test_verify_video_fails_on_width_fps_and_frames(
    monkeypatch: pytest.MonkeyPatch, metrics: dict[str, object]
) -> None:
    monkeypatch.setattr(comfyclient, "probe_video", lambda path: metrics)
    thresholds = {"width": 1280, "height": 704, "fps": 24, "frames": 49}
    verdict = comfyclient.verify_video(Path("clip.mp4"), thresholds, 0.01)
    assert verdict["passed"] is False
    assert verdict["thresholds"] == thresholds


def test_verify_video_reports_a_probe_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(path: Path) -> dict[str, object]:
        raise ValueError("no stream")

    monkeypatch.setattr(comfyclient, "probe_video", fail)
    thresholds = {"width": 1280, "height": 704, "fps": 24, "frames": 49}
    verdict = comfyclient.verify_video(Path("clip.mp4"), thresholds, 0.01)
    assert verdict["passed"] is False
    assert verdict["metrics"] == {"error": "no stream"}


def test_check_marks_failures_with_their_fix() -> None:
    assert comfyclient.check("gpu", True, "ok") == {
        "name": "gpu",
        "ok": True,
        "detail": "ok",
        "fix": "",
    }
    failed = comfyclient.check("gpu", False, "missing", "install it")
    assert failed["fix"] == "install it"


def test_healthy_reports_2xx_only(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __init__(self, status: int):
            self.status = status

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: Response(200))
    assert comfyclient.healthy(f"{BASE}/system_stats") is True
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: Response(500))
    assert comfyclient.healthy(f"{BASE}/system_stats") is False

    def fail(url: object, timeout: float = 2.0) -> object:
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    assert comfyclient.healthy(f"{BASE}/system_stats") is False


def test_doctor_models_counts_bytes_from_the_manifest(tmp_path: Path) -> None:
    full = tmp_path / "full.bin"
    full.write_bytes(b"123")
    short = tmp_path / "short.bin"
    short.write_bytes(b"1")
    manifest = {
        "models": [
            {"id": "full", "bytes": 3},
            {"id": "short", "bytes": 3},
            {"id": "gone", "bytes": 3},
        ]
    }
    verdict = comfyclient.doctor_models(_Req({"full": full, "short": short}), manifest, "pull it")
    assert verdict["ok"] is False
    assert verdict["fix"] == "pull it"
    assert "full" not in verdict["detail"]
    assert "short" in verdict["detail"] and "gone" in verdict["detail"]
    matched = comfyclient.doctor_models(
        _Req({"full": full}), {"models": [{"id": "full", "bytes": 3}]}, "x"
    )
    assert matched["ok"] is True


def test_doctor_checkout_needs_main_py(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("FACET_MODELS", str(home / "models" / "direct"))
    manifest = _manifest_dict()
    assert comfyclient.doctor_checkout(manifest, "pull it")["ok"] is False
    target = comfyclient.server_dir(manifest)
    target.mkdir(parents=True)
    (target / "main.py").write_text("x", encoding="utf-8")
    assert comfyclient.doctor_checkout(manifest, "pull it")["ok"] is True


def test_doctor_server_reports_the_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(comfyclient, "healthy", lambda url: True)
    monkeypatch.setenv("FACET_SERVER_URL", BASE)
    verdict = comfyclient.doctor_server()
    assert verdict == {
        "name": "server",
        "ok": True,
        "detail": f"{BASE}/system_stats answers",
        "fix": "",
    }
