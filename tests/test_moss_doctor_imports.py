"""The moss doctor's imports check at both depths.

The quick depth runs inside a ten second budget, so it proves each module in
``DOCTOR_IMPORTS`` exists and reports its distribution version without
importing it: a cold ``import torch`` alone costs more than the whole budget.
The full depth still imports every module, so it catches one that is present
but broken. ``find_spec`` and ``import_module`` are monkeypatched here; no
real torch is touched.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "packages" / "moss" / "runner.py"

PULL_FIX = "facet pull moss"


def _load_runner() -> Any:
    """The moss runner with the runner SDK stubbed, loaded once per session."""
    cached = sys.modules.get("moss_runner_under_test")
    if cached is not None:
        return cached
    sdk = types.ModuleType("facet_runner_sdk")

    class Request:
        pass

    class Runner:
        def verb(self, name: str) -> Any:
            def register(function: Any) -> Any:
                return function

            return register

        def main(self, *args: Any) -> int:
            return 0

    sdk.Request = Request  # type: ignore[attr-defined]
    sdk.Runner = Runner  # type: ignore[attr-defined]
    sys.modules["facet_runner_sdk"] = sdk
    spec = importlib.util.spec_from_file_location("moss_runner_under_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["moss_runner_under_test"] = module
    spec.loader.exec_module(module)
    return module


class _ImportProbe:
    """Count the imports the check makes and answer with canned modules."""

    def __init__(self, broken: dict[str, Exception] | None = None) -> None:
        self.imported: list[str] = []
        self.broken = broken or {}

    def import_module(self, name: str) -> types.SimpleNamespace:
        self.imported.append(name)
        if name in self.broken:
            raise self.broken[name]
        return types.SimpleNamespace(__version__="2.1.0")


@pytest.fixture
def runner_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The runner loaded, with no MOSS checkout in the environment."""
    monkeypatch.delenv("FACET_SOURCE_DIR", raising=False)
    monkeypatch.delenv("MOSS_DIR", raising=False)
    return _load_runner()


def _patch_find_spec(monkeypatch: pytest.MonkeyPatch, missing: frozenset[str]) -> None:
    """Every module resolves to a spec, but for the ``missing`` ones."""

    def find_spec(name: str, *args: Any, **kwargs: Any) -> types.SimpleNamespace | None:
        return None if name in missing else types.SimpleNamespace(name=name)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)


def _patch_import_module(monkeypatch: pytest.MonkeyPatch, probe: _ImportProbe) -> None:
    monkeypatch.setattr(importlib, "import_module", probe.import_module)


def test_the_quick_check_imports_nothing(
    runner_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_find_spec(monkeypatch, frozenset())
    probe = _ImportProbe()
    _patch_import_module(monkeypatch, probe)
    check = runner_module._doctor_imports("quick")
    assert check["ok"] is True, check["detail"]
    assert probe.imported == []
    for module_name, _distribution in runner_module.DOCTOR_IMPORTS:
        assert module_name in check["detail"]


def test_the_quick_check_reports_a_missing_module_broken(
    runner_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_find_spec(monkeypatch, frozenset({"torch"}))
    probe = _ImportProbe()
    _patch_import_module(monkeypatch, probe)
    check = runner_module._doctor_imports("quick")
    assert check["ok"] is False
    assert check["detail"] == "torch: No module named 'torch'"
    assert check["fix"] == PULL_FIX
    assert probe.imported == []


def test_the_full_check_imports_every_module(
    runner_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_find_spec(monkeypatch, frozenset(name for name, _ in runner_module.DOCTOR_IMPORTS))
    probe = _ImportProbe()
    _patch_import_module(monkeypatch, probe)
    check = runner_module._doctor_imports("full")
    assert check["ok"] is True, check["detail"]
    assert probe.imported == [name for name, _ in runner_module.DOCTOR_IMPORTS]
    assert "torch 2.1.0" in check["detail"]


def test_the_full_check_reports_a_broken_import(
    runner_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_find_spec(monkeypatch, frozenset())
    probe = _ImportProbe({"torch": RuntimeError("torch exploded")})
    _patch_import_module(monkeypatch, probe)
    check = runner_module._doctor_imports("full")
    assert check["ok"] is False
    assert "torch: torch exploded" in check["detail"]
    assert check["fix"] == PULL_FIX
