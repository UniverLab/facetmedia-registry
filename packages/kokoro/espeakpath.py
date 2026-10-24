"""A short path to espeak-ng's data, which it cannot read from a long one.

espeak-ng copies its data directory into a fixed-size buffer: from a path
longer than about 160 characters it silently falls back to the directory
compiled into the wheel (``/home/runner/work/...``) and fails on
``phontab``. It does not follow a symlink to the data either (measured
2026-10-24 with espeakng-loader 0.2.4), so a facet home under a long path
gets a one-time copy of the data (about 19 MB) in the temp directory.
Stdlib only, so the root tests import it without the environment.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

#: The longest data path handed to espeak-ng as is; longer ones get a copy.
MAX_DATA_PATH = 150
#: The file that proves a data directory is complete.
MARKER = "phontab"


def short_data_path(data_path: str, base: Path, limit: int = MAX_DATA_PATH) -> str:
    """``data_path`` itself when it is short enough, else a short copy of it.

    The copy lives in ``base`` (the temp directory), named by a hash of the
    source path so every run of the same environment reuses it. It is built
    in a sibling temp directory and renamed into place, so a run that dies
    mid-copy leaves no half directory behind; a copy without its marker file
    is rebuilt.
    """
    if len(data_path) <= limit:
        return data_path
    digest = hashlib.sha256(data_path.encode()).hexdigest()[:12]
    target = base / f"facet-espeak-{digest}"
    if (target / MARKER).is_file():
        return str(target)
    if target.exists():
        shutil.rmtree(target)
    staging = Path(tempfile.mkdtemp(prefix=f"{target.name}-", dir=base))
    try:
        shutil.copytree(data_path, staging / "data")
        (staging / "data").rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return str(target)
