"""HyperFrames verify runs the pinned tool's ``lint --json`` on the composition.

The runner probes the MP4 with the pinned ``ffprobe`` and lints the source
composition with the pinned HyperFrames CLI. The lint passes when its
``errorCount`` is 0; each error finding fails the asset naming the finding's
code and location. facet adds no composition-id or clip-duration check of its
own: the linter covers them. The CLI is stubbed through ``FACET_TEST_LINT_JSON``,
so no test renders a real composition.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from test_hyperframes_runner import (
    CLIP,
    FFPROBE,
    NODE,
    PACKAGE,
    _composition,
    _dirs,
    _environment,
    _fixture,
    _invoke,
    _request,
)

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not available")

#: The stubbed lint answer for a clean composition: no errors, no findings.
CLEAN_LINT = json.dumps({"ok": True, "errorCount": 0, "findings": []})


def _verify_with_lint(
    tmp_path: Path, lint: str, **inputs: Any
) -> tuple[subprocess.CompletedProcess[str], Any]:
    packages = _fixture(tmp_path)
    piece, _comp, _clip = _composition(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    asset = out / "good.mp4"
    shutil.copyfile(CLIP, asset)
    return _verify_asset(tmp_path, packages, piece, asset, lint, **inputs)


def _verify_asset(
    tmp_path: Path,
    packages: dict[str, Path],
    piece: Path,
    asset: Path,
    lint: str,
    **inputs: Any,
) -> tuple[subprocess.CompletedProcess[str], Any]:
    out = asset.parent
    env = _environment(tmp_path, _dirs(packages))
    env["FACET_TEST_LINT_JSON"] = lint
    request = _request("verify", out, piece, composition="comp", prompt="a brief", **inputs)
    request["assets"] = [str(asset)]
    return _invoke(tmp_path, "verify", request, env)


@pytest.mark.skipif(FFPROBE is None, reason="ffprobe is not available")
def test_verify_passes_a_clean_lint_and_records_its_counts(tmp_path: Path) -> None:
    done, result = _verify_with_lint(tmp_path, CLEAN_LINT)
    assert done.returncode == 0, done.stderr
    verdict = result["assets"][0]
    assert verdict["passed"] is True
    assert verdict["metrics"]["lint_ok"] is True
    assert verdict["metrics"]["lint_errorCount"] == 0
    assert verdict["metrics"]["lint_errors"] == []


@pytest.mark.skipif(FFPROBE is None, reason="ffprobe is not available")
def test_verify_fails_a_lint_error_and_names_its_code(tmp_path: Path) -> None:
    lint = json.dumps(
        {
            "ok": False,
            "errorCount": 1,
            "findings": [
                {
                    "code": "duplicate_composition_id",
                    "severity": "error",
                    "message": "composition main repeats id main",
                }
            ],
        }
    )
    done, result = _verify_with_lint(tmp_path, lint)
    assert done.returncode == 0, done.stderr
    verdict = result["assets"][0]
    assert verdict["passed"] is False
    assert verdict["metrics"]["lint_errorCount"] == 1
    assert verdict["metrics"]["lint_errors"] == [
        "duplicate_composition_id at composition main repeats id main"
    ]
    assert "duplicate_composition_id" in verdict["metrics"]["error"]


@pytest.mark.skipif(FFPROBE is None, reason="ffprobe is not available")
@pytest.mark.parametrize("folder", ["basic", "character", "diagram", "narrated", "turntable"])
def test_verify_passes_each_example_composition(tmp_path: Path, folder: str) -> None:
    packages = _fixture(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    asset = out / "good.mp4"
    shutil.copyfile(CLIP, asset)
    relative = os.path.relpath(PACKAGE / "examples" / folder / "composition", PACKAGE)
    env = _environment(tmp_path, _dirs(packages))
    env["FACET_TEST_LINT_JSON"] = CLEAN_LINT
    request = _request("verify", out, PACKAGE, composition=relative, prompt="a brief")
    request["assets"] = [str(asset)]
    done, result = _invoke(tmp_path, "verify", request, env)
    assert done.returncode == 0, done.stderr
    assert result["assets"][0]["passed"] is True
