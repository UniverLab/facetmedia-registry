"""The sidecar engine provisioning unit tests: install, poll, retry and resume.

The provisioning helpers as their own module, stubbed per test: no backend,
no GPU, no run. The run-level engine behaviour stays in
test_voicestudio_cycle.py.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "voicestudio"


def _import_engines() -> Any:
    """The provisioning helpers as their own module, stubbed per test."""
    spec = importlib.util.spec_from_file_location(
        "voicestudio_engines_unit", PACKAGE / "engines.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_already_installed_engine_returns_without_posting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status first: ``installed`` true means no POST and no wait."""
    engines = _import_engines()

    def fail_post(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("no POST when the engine is installed")

    monkeypatch.setattr(
        engines,
        "_fetch_json",
        lambda *_args, **_kwargs: {"installed": True, "install_dir": "/d/voxcpm2"},
    )
    monkeypatch.setattr(engines, "_post_json", fail_post)
    assert engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2") is None


def test_a_missing_engine_installs_then_polls_to_installed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not installed: one POST, progress on each state change, return on installed."""
    engines = _import_engines()
    starting = [
        {"id": "preflight", "state": "running", "detail": None},
        {"id": "fetch_source", "state": "pending", "detail": None},
    ]
    fetching = [
        {"id": "preflight", "state": "done", "detail": "uv found, disk space OK"},
        {"id": "fetch_source", "state": "running", "detail": None},
    ]
    statuses = [
        {"installed": False, "job": {"state": "running", "steps": starting}},
        {"installed": False, "job": {"state": "running", "steps": starting}},
        {"installed": False, "job": {"state": "running", "steps": fetching}},
        {"installed": True, "install_dir": "/d/voxcpm2", "job": {"state": "succeeded"}},
    ]
    posts: list[tuple[object, ...]] = []

    def scripted_fetch(*_args: object, **_kwargs: object) -> dict[str, object]:
        return dict(statuses.pop(0))

    def record_post(*args: object, **_kwargs: object) -> dict[str, object]:
        posts.append(args)
        return {}

    monkeypatch.setattr(engines, "_fetch_json", scripted_fetch)
    monkeypatch.setattr(engines, "_post_json", record_post)
    monkeypatch.setattr(engines, "ENGINE_POLL_S", 0.0)
    assert engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2") is None
    assert len(posts) == 1
    progress = capsys.readouterr().err
    assert "voicestudio: installing voxcpm2: running preflight" in progress
    assert "voicestudio: installing voxcpm2: running fetch_source" in progress


def test_a_409_names_the_machine_as_unservable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """409 on POST: the host cannot serve the engine, with the backend's sentence."""
    engines = _import_engines()
    monkeypatch.setattr(
        engines, "_fetch_json", lambda *_args, **_kwargs: {"installed": False, "job": {}}
    )

    def conflict(*_args: object, **_kwargs: object) -> object:
        raise engines._HttpError(
            engines.HTTP_CONFLICT, json.dumps({"detail": "no CUDA on this host"})
        )

    monkeypatch.setattr(engines, "_post_json", conflict)
    with pytest.raises(RuntimeError) as caught:
        engines._ensure_engine("http://127.0.0.1:3900", "cosyvoice")
    assert "cosyvoice: VoiceStudio cannot install it on this machine" in str(caught.value)
    assert "no CUDA on this host" in str(caught.value)


def test_a_job_error_raises_with_error_and_remediation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed install job carries what broke and what settles it."""
    engines = _import_engines()
    status = {
        "installed": False,
        "job": {
            "state": "failed",
            "steps": ["fetch"],
            "error": "disk full",
            "remediation": "free 10 GB",
        },
    }
    monkeypatch.setattr(engines, "_fetch_json", lambda *_args, **_kwargs: status)
    monkeypatch.setattr(engines, "_post_json", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(engines, "ENGINE_POLL_S", 0.0)
    with pytest.raises(RuntimeError) as caught:
        engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2")
    assert "disk full" in str(caught.value)
    assert "free 10 GB" in str(caught.value)


def test_an_install_that_never_finishes_raises_and_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A patched clock past the budget: the run fails, the next run resumes the job."""
    engines = _import_engines()
    status = {"installed": False, "job": {"state": "running", "steps": ["fetch"]}}
    monkeypatch.setattr(engines, "_fetch_json", lambda *_args, **_kwargs: status)
    monkeypatch.setattr(engines, "_post_json", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(engines, "ENGINE_POLL_S", 0.0)
    ticks = [1000.0, 1000.0 + 6000.0]
    monkeypatch.setattr(engines.time, "monotonic", lambda: ticks.pop(0))
    with pytest.raises(RuntimeError) as caught:
        engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2")
    assert "install not finished after 5400 s" in str(caught.value)
    assert "facet run again resumes it" in str(caught.value)


def test_a_transient_install_failure_retries_once_then_installs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Transient flake (uv pip exit 1): one retry POST, then installed."""
    engines = _import_engines()
    transient = {
        "installed": False,
        "job": {
            "state": "failed",
            "steps": ["fetch"],
            "error": "uv pip install exit 1",
            "remediation": "retry the install",
        },
    }
    running = {"installed": False, "job": {"state": "running", "steps": ["fetch"]}}
    installed = {"installed": True, "install_dir": "/d/voxcpm2"}
    statuses = [
        {"installed": False, "job": {}},
        transient,
        running,
        installed,
    ]
    posts: list[tuple[object, ...]] = []

    def scripted_fetch(*_args: object, **_kwargs: object) -> dict[str, object]:
        return dict(statuses.pop(0))

    def record_post(*args: object, **_kwargs: object) -> dict[str, object]:
        posts.append(args)
        return {}

    monkeypatch.setattr(engines, "_fetch_json", scripted_fetch)
    monkeypatch.setattr(engines, "_post_json", record_post)
    monkeypatch.setattr(engines, "ENGINE_POLL_S", 0.0)
    assert engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2") is None
    initial_post_plus_retry = 2
    assert len(posts) == initial_post_plus_retry
    progress = capsys.readouterr().err
    retry_line = (
        "voicestudio: installing voxcpm2: retrying after transient failure: uv pip install exit 1"
    )
    assert progress.count(retry_line) == 1


def test_a_409_answer_never_retries(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """409 on POST: fatal at once, with the machine sentence, one POST."""
    engines = _import_engines()
    monkeypatch.setattr(
        engines, "_fetch_json", lambda *_args, **_kwargs: {"installed": False, "job": {}}
    )
    posts: list[tuple[object, ...]] = []

    def conflict(*args: object, **_kwargs: object) -> object:
        posts.append(args)
        raise engines._HttpError(
            engines.HTTP_CONFLICT, json.dumps({"detail": "no CUDA on this host"})
        )

    monkeypatch.setattr(engines, "_post_json", conflict)
    monkeypatch.setattr(engines, "ENGINE_POLL_S", 0.0)
    with pytest.raises(RuntimeError) as caught:
        engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2")
    assert len(posts) == 1
    assert "VoiceStudio cannot install it on this machine" in str(caught.value)
    assert "no CUDA on this host" in str(caught.value)
    assert "retrying after transient failure" not in capsys.readouterr().err


def test_a_compiler_job_error_never_retries(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """NEEDS_CXX text in the job: fatal at once, one POST, no retry line."""
    engines = _import_engines()
    status = {
        "installed": False,
        "job": {
            "state": "failed",
            "steps": ["fetch"],
            "error": "cosyvoice builds pyworld from source; g++ is not on PATH",
            "remediation": "sudo apt install build-essential",
        },
    }
    statuses = [{"installed": False, "job": {}}, status]
    posts: list[tuple[object, ...]] = []

    def scripted_fetch(*_args: object, **_kwargs: object) -> dict[str, object]:
        return dict(statuses.pop(0))

    def record_post(*args: object, **_kwargs: object) -> dict[str, object]:
        posts.append(args)
        return {}

    monkeypatch.setattr(engines, "_fetch_json", scripted_fetch)
    monkeypatch.setattr(engines, "_post_json", record_post)
    monkeypatch.setattr(engines, "ENGINE_POLL_S", 0.0)
    with pytest.raises(RuntimeError) as caught:
        engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2")
    assert len(posts) == 1
    assert "pyworld" in str(caught.value)
    assert "retrying after transient failure" not in capsys.readouterr().err


def test_two_transient_failures_in_a_row_fail_with_the_job_detail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Transient twice: exactly one retry, then the job detail as today."""
    engines = _import_engines()
    first = {
        "installed": False,
        "job": {
            "state": "failed",
            "steps": ["fetch"],
            "error": "connection reset by peer",
            "remediation": "retry the install",
        },
    }
    second = {
        "installed": False,
        "job": {
            "state": "error",
            "steps": ["fetch"],
            "error": "network timeout fetching wheels",
            "remediation": "check the network",
        },
    }
    statuses = [{"installed": False, "job": {}}, first, second]
    posts: list[tuple[object, ...]] = []

    def scripted_fetch(*_args: object, **_kwargs: object) -> dict[str, object]:
        return dict(statuses.pop(0))

    def record_post(*args: object, **_kwargs: object) -> dict[str, object]:
        posts.append(args)
        return {}

    monkeypatch.setattr(engines, "_fetch_json", scripted_fetch)
    monkeypatch.setattr(engines, "_post_json", record_post)
    monkeypatch.setattr(engines, "ENGINE_POLL_S", 0.0)
    with pytest.raises(RuntimeError) as caught:
        engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2")
    initial_post_plus_retry = 2
    assert len(posts) == initial_post_plus_retry
    assert "network timeout fetching wheels" in str(caught.value)
    assert "check the network" in str(caught.value)
    assert capsys.readouterr().err.count("retrying after transient failure") == 1


def test_a_poll_past_the_timeout_leaves_the_resumable_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patched clock past the budget: resume sentence, job left for next run."""
    engines = _import_engines()
    status = {"installed": False, "job": {"state": "running", "steps": ["fetch"]}}
    posts: list[tuple[object, ...]] = []
    monkeypatch.setattr(engines, "_fetch_json", lambda *_args, **_kwargs: status)
    monkeypatch.setattr(
        engines,
        "_post_json",
        lambda *args, **_kwargs: posts.append(args) or {},
    )
    monkeypatch.setattr(engines, "ENGINE_POLL_S", 0.0)
    ticks = [2000.0, 2000.0 + 6000.0]
    monkeypatch.setattr(engines.time, "monotonic", lambda: ticks.pop(0))
    with pytest.raises(RuntimeError) as caught:
        engines._ensure_engine("http://127.0.0.1:3900", "voxcpm2")
    assert "install not finished after 5400 s" in str(caught.value)
    assert "facet run again resumes it" in str(caught.value)
    assert len(posts) == 1
