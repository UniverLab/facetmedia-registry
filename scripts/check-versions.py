"""Require a version bump on every changed package.

For each ``packages/<name>/`` with any changed file between the PR's base
and head, the ``version`` in its ``package.toml`` must be a valid PEP 440
version greater than the base's version. A package that is new in the head
passes. Exits non-zero naming each offending package.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib

from packaging.version import InvalidVersion, Version


def git(*args: str, quiet: bool = False) -> str:
    stderr = subprocess.DEVNULL if quiet else None
    return subprocess.check_output(["git", *args], text=True, stderr=stderr)


#: Segments in ``packages/<name>/<file>``: the minimum for a package path.
_MIN_PACKAGE_SEGMENTS = 3


def changed_packages(base: str, head: str = "HEAD") -> list[str]:
    out = git("diff", "--name-only", f"{base}...{head}")
    names: list[str] = []
    for line in out.splitlines():
        parts = line.split("/")
        if (
            len(parts) >= _MIN_PACKAGE_SEGMENTS
            and parts[0] == "packages"
            and parts[1]
            and parts[1] not in names
        ):
            names.append(parts[1])
    return names


def version_at(ref: str, name: str) -> str | None:
    try:
        content = git("show", f"{ref}:packages/{name}/package.toml", quiet=True)
    except subprocess.CalledProcessError:
        return None
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return None
    version = data.get("version")
    return version if isinstance(version, str) else None


def check(name: str, base: str) -> str | None:
    head_version = version_at("HEAD", name)
    if head_version is None:
        return "package.toml missing or has no version"
    base_version = version_at(base, name)
    if base_version is None:
        return None
    try:
        head_parsed = Version(head_version)
    except InvalidVersion:
        return f"invalid version: {head_version}"
    try:
        base_parsed = Version(base_version)
    except InvalidVersion:
        return f"invalid base version: {base_version}"
    if head_parsed <= base_parsed:
        return f"version must increase: base {base_version} head {head_version}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base ref to diff against")
    args = parser.parse_args()
    ok = True
    for name in changed_packages(args.base):
        error = check(name, args.base)
        if error is None:
            print(f"OK {name}")
        else:
            print(f"FAIL {name}: {error}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
