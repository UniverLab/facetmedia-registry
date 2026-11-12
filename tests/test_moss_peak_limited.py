"""Peak-limited verify for moss.sfx: quiet at the ceiling passes, recorded.

The normaliser caps gain so the peak stays at or below ``PEAK_CAP_DBFS``
(-1.0 dBFS); a transient-heavy effect reaches that ceiling before its
loudness target and lands below ``target-lufs``. ``_verify_one`` accepts
such a file and records ``peak_limited: true`` instead of failing it.
Synthetic samples only: a fake audio object returns canned loudness and
peak, so no model runs here.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "packages" / "moss" / "runner.py"

TARGET = -23.0


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


class _FakeAudio:
    """Canned loudness and peak; the path on disk is never read."""

    PEAK_CAP_DBFS = -1.0

    def __init__(self, lufs: float, peak: float) -> None:
        self._lufs = lufs
        self._peak = peak

    def read_wav(self, path: Path) -> tuple[str, int]:
        return ("samples", 48000)

    def integrated_lufs(self, samples: Any, rate: int) -> float:
        return self._lufs

    def peak_dbfs(self, samples: Any) -> float:
        return self._peak

    def duration_s(self, samples: Any, rate: int) -> float:
        return 2.0


def _verdict(lufs: float, peak: float) -> dict[str, Any]:
    runner = _load_runner()
    audio = _FakeAudio(lufs, peak)
    return runner._verify_one(audio, Path("pasos-madera.wav"), {"target-lufs": TARGET})


def test_within_tolerance_passes_without_peak_limited() -> None:
    verdict = _verdict(-23.0, -3.0)
    assert verdict["passed"] is True
    assert verdict["metrics"]["peak_limited"] is False
    assert verdict["thresholds"]["peak_cap_dbfs"] == -1.0


def test_quiet_at_the_ceiling_passes_as_peak_limited() -> None:
    verdict = _verdict(-24.11, -1.0)
    assert verdict["passed"] is True
    assert verdict["metrics"]["peak_limited"] is True
    assert verdict["thresholds"]["peak_cap_dbfs"] == -1.0


def test_quiet_below_the_ceiling_fails() -> None:
    verdict = _verdict(-26.0, -3.0)
    assert verdict["passed"] is False
    assert verdict["metrics"]["peak_limited"] is False
    assert verdict["thresholds"]["peak_cap_dbfs"] == -1.0


def test_too_loud_fails_even_at_the_ceiling() -> None:
    verdict = _verdict(-20.0, -1.0)
    assert verdict["passed"] is False
    assert verdict["metrics"]["peak_limited"] is False
    assert verdict["thresholds"]["peak_cap_dbfs"] == -1.0


def test_unreadable_wav_carries_no_peak_limited_key() -> None:
    runner = _load_runner()

    class _BrokenAudio(_FakeAudio):
        def read_wav(self, path: Path) -> tuple[str, int]:
            raise OSError("no such file")

    verdict = runner._verify_one(
        _BrokenAudio(-24.11, -1.0), Path("missing.wav"), {"target-lufs": TARGET}
    )
    assert verdict["passed"] is False
    assert "peak_limited" not in verdict["metrics"]
    assert verdict["thresholds"]["peak_cap_dbfs"] == -1.0
