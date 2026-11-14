"""Every metre a piece may write reaches the body as its beats-per-bar number.

The pinned ACE-Step accepts only ``2``, ``3``, ``4`` and ``6`` as
``time_signature``; the runner maps the human metres ``2/4``, ``3/4``,
``4/4`` and ``6/8`` onto them. ``_submit`` is driven with each metre the
manifest declares, its POST stubbed, so every mapping is pinned in the
request body itself: no server, no GPU and no cycle.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "packages" / "acestep" / "runner.py"

#: Each declared metre and the beats-per-bar string the pinned server accepts.
METRES = (("2/4", "2"), ("3/4", "3"), ("4/4", "4"), ("6/8", "6"))


def _load_runner() -> Any:
    """The acestep runner with the runner SDK stubbed, loaded once per session."""
    cached = sys.modules.get("acestep_runner_under_test")
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
    spec = importlib.util.spec_from_file_location("acestep_runner_under_test", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["acestep_runner_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_the_body_carries_every_metre_as_its_beats_per_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each declared metre maps to its beats-per-bar string in the request body."""
    runner = _load_runner()
    bodies: list[dict[str, Any]] = []

    def fake_post(path: str, payload: dict[str, Any], timeout: float = 0.0) -> dict[str, Any]:
        bodies.append(payload)
        return {"data": {"task_id": "stub-task"}}

    monkeypatch.setattr(runner, "_post", fake_post)
    sent = {"seed": 0, "steps": 8, "guidance": 7.0}
    for metre, beats in METRES:
        bodies.clear()
        runner._submit("strings and harpsichord", 30.0, {**sent, "time-signature": metre})
        assert bodies[0]["time_signature"] == beats
