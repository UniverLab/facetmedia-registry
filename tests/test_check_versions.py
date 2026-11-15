"""The version gate refuses any package change without a version bump.

``scripts/check-versions.py`` compares each ``packages/<name>/`` touched
between a base ref and HEAD: the ``version`` in its ``package.toml`` must be
a valid PEP 440 version greater than the base's. A package that is new in
the head passes. These tests build a throwaway git repo per case and run
the script against it the way CI does.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-versions.py"

MANIFEST = """\
name = "foo"
version = "{version}"
facet = "image"
"""


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", message)


def _base_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    pkg = repo / "packages" / "foo"
    pkg.mkdir(parents=True)
    (pkg / "package.toml").write_text(MANIFEST.format(version="0.1.0"), encoding="utf-8")
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _run_script(repo: Path, base: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--base", base],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


def _write_version(repo: Path, name: str, version: str) -> None:
    path = repo / "packages" / name / "package.toml"
    path.write_text(MANIFEST.format(version=version), encoding="utf-8")


def test_readme_only_change_passes(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    _commit(repo, "docs")
    proc = _run_script(repo, base)
    assert proc.returncode == 0, proc.stdout


def test_changed_package_without_bump_fails(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    path = repo / "packages" / "foo" / "package.toml"
    path.write_text(path.read_text(encoding="utf-8") + "# touch\n", encoding="utf-8")
    _commit(repo, "touch foo")
    proc = _run_script(repo, base)
    assert proc.returncode == 1
    assert "foo" in proc.stdout
    assert "0.1.0" in proc.stdout


def test_changed_package_with_bump_passes(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    _write_version(repo, "foo", "0.1.1")
    _commit(repo, "bump foo")
    proc = _run_script(repo, base)
    assert proc.returncode == 0, proc.stdout
    assert "OK foo" in proc.stdout


def test_version_going_down_fails(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    _write_version(repo, "foo", "0.0.9")
    _commit(repo, "downgrade foo")
    proc = _run_script(repo, base)
    assert proc.returncode == 1
    assert "foo" in proc.stdout
    assert "0.1.0" in proc.stdout
    assert "0.0.9" in proc.stdout


def test_new_package_passes(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    bar = repo / "packages" / "bar"
    bar.mkdir(parents=True)
    (bar / "package.toml").write_text(MANIFEST.format(version="0.1.0"), encoding="utf-8")
    _commit(repo, "add bar")
    proc = _run_script(repo, base)
    assert proc.returncode == 0, proc.stdout


def test_invalid_version_fails(tmp_path: Path) -> None:
    repo, base = _base_repo(tmp_path)
    _write_version(repo, "foo", "not-a-version")
    _commit(repo, "break foo version")
    proc = _run_script(repo, base)
    assert proc.returncode == 1
    assert "foo" in proc.stdout
    assert "not-a-version" in proc.stdout
