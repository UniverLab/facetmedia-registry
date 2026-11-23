"""Speak-voice validation for voicestudio: narradora passes, own clones are
redirected to voicestudio.clone, unknown ids get the profile recipe.

The runner module is imported in-process over the stub SDK (whose main()
is a no-op) and _profile_rows is stubbed: no backend, no model download.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "voicestudio"


def _import_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """The runner module in-process, over the stub SDK (main() is a no-op)."""
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("STUB_SDK_NO_MAIN", "1")
    (stub_dir / "facet_runner_sdk.py").write_text(
        "STUB_SDK_NO_MAIN = True\n"
        "import os\n"
        "class Request:\n"
        "    def __init__(self, data=None):\n"
        "        self.inputs = dict((data or {}).get('inputs') or {})\n"
        "class Runner:\n"
        "    def __init__(self):\n"
        "        self._verbs = {}\n"
        "    def verb(self, name):\n"
        "        def wrap(fn):\n"
        "            self._verbs[name] = fn\n"
        "            return fn\n"
        "        return wrap\n"
        "    def main(self):\n"
        "        assert os.environ.get('STUB_SDK_NO_MAIN') == '1', 'stub main must stand down'\n",
        encoding="utf-8",
    )
    facet_lib = stub_dir / "facet_lib"
    facet_lib.mkdir(exist_ok=True)
    (facet_lib / "__init__.py").write_text("", encoding="utf-8")
    (facet_lib / "textnorm.py").write_text(
        (ROOT / "lib" / "textnorm.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(stub_dir))
    spec = importlib.util.spec_from_file_location(
        "voicestudio_runner_speak_voice", PACKAGE / "runner.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rows(*entries: dict[str, str]) -> list[dict[str, str]]:
    return list(entries)


def test_narradora_passes_without_listing_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default narrator voice never needs a backend round-trip to pass."""
    module = _import_runner(monkeypatch, tmp_path)
    module._check_speak_voice("http://127.0.0.1:3900", "narradora")


def test_unknown_voice_names_the_profile_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unregistered id fails with the profile creation recipe."""
    module = _import_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module, "_profile_rows", lambda _url: _rows({"id": "abc123", "name": "narradora"})
    )
    with pytest.raises(ValueError, match="unknown"):
        module._check_speak_voice("http://127.0.0.1:3900", "f83d0139")
    try:
        module._check_speak_voice("http://127.0.0.1:3900", "f83d0139")
    except ValueError as exc:
        assert "voicestudio.profile" in str(exc)


def test_own_clone_points_at_the_clone_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A registered non-narradora id fails naming clone on cosyvoice."""
    module = _import_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "_profile_rows",
        lambda _url: _rows(
            {"id": "f83d0139", "name": "mi-voz"},
            {"id": "narradora", "name": "narradora"},
        ),
    )
    with pytest.raises(ValueError, match="clone profile"):
        module._check_speak_voice("http://127.0.0.1:3900", "f83d0139")
    try:
        module._check_speak_voice("http://127.0.0.1:3900", "f83d0139")
    except ValueError as exc:
        assert "voicestudio.clone" in str(exc)
        assert "cosyvoice" in str(exc)
        assert "two voices go in two pieces" in str(exc)


def test_unreadable_profiles_fail_without_a_recipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable /profiles surfaces the fetch failure, not a recipe."""
    module = _import_runner(monkeypatch, tmp_path)

    def broken(_url: str) -> list[dict[str, str]]:
        raise ValueError("/profiles answered an unexpected body")

    monkeypatch.setattr(module, "_profile_rows", broken)
    with pytest.raises(RuntimeError, match="GET /profiles failed"):
        module._check_speak_voice("http://127.0.0.1:3900", "f83d0139")
