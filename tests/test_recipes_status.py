"""The recipes status verb: handoff state beside a plan, no registry.

The runner is a subprocess of the host `python` — the package is stdlib
only. Its `PYTHONPATH` carries a stub `facet_runner_sdk`, so the test
proves the status report from plan fixtures and folders with done, missing,
stale and shared-file steps without running any capability.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "recipes"
RUNNER = PACKAGE / "runner.py"

STUB_SDK = """
import json
import sys
from pathlib import Path


class Request:
    def __init__(self, data):
        self.verb = str(data.get("verb", ""))
        self.capability = str(data.get("capability", ""))
        self.depth = str(data.get("depth", "quick"))
        self.inputs = dict(data.get("inputs") or {})
        self.out_dir = Path(str(data.get("out_dir", "")))
        self.piece_dir = Path(str(data.get("piece_dir", "")))
        self.assets = [Path(str(item)) for item in data.get("assets") or []]
        self._models = {str(k): Path(str(v)) for k, v in (data.get("models") or {}).items()}

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def model_path(self, model_id):
        return self._models[model_id]


class Runner:
    def __init__(self):
        self._verbs = {}

    def verb(self, name):
        def register(function):
            self._verbs[name] = function
            return function

        return register

    def run(self, argv):
        verb, *rest = argv
        values = {rest[index]: rest[index + 1] for index in range(0, len(rest), 2)}
        result = self._verbs[verb](Request.from_file(values["--input"]))
        Path(values["--result"]).write_text(json.dumps(result))
        return 0

    def main(self):
        raise SystemExit(self.run(sys.argv[1:]))
"""


def _stub_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "stub-modules"
    folder.mkdir(exist_ok=True)
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    return folder


def _request(plan: Path, out_dir: Path) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": "status",
        "capability": "recipes.status",
        "depth": "quick",
        "inputs": {"plan": str(plan)},
        "out_dir": str(out_dir),
        "piece_dir": str(plan.parent),
        "models": {},
        "assets": [str(plan)],
    }


def _call(
    stub_dir: Path, request: dict[str, object], tmp_path: Path, tag: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    input_path = tmp_path / f"{tag}-request.json"
    result_path = tmp_path / f"{tag}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    result_path.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONPATH": str(stub_dir)}
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "status",
            "--input",
            str(input_path),
            "--result",
            str(result_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
    return done, result


def _write_record(path: Path, capability: str, created: str) -> None:
    record = {"created": created, "provenance": {"capability": capability}}
    Path(str(path) + ".facet.json").write_text(json.dumps(record), encoding="utf-8")


def _touch(path: Path, capability: str, created: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    _write_record(path, capability, created)


def _write_plan(folder: Path, name: str, steps: list[dict[str, Any]]) -> Path:
    plan = {"recipe": name, "summary": name, "steps": steps}
    path = folder / f"{name}.plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _status(
    tmp_path: Path, plan: Path, tag: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, Path]:
    stub_dir = _stub_dir(tmp_path)
    out_dir = tmp_path / f"out-{tag}"
    out_dir.mkdir()
    done, result = _call(stub_dir, _request(plan, out_dir), tmp_path, tag)
    status_path = plan.parent / f"{plan.stem.split('.')[0]}.status.json"
    return done, result, status_path


def _assert_matches_file(result: dict[str, Any], status_path: Path) -> None:
    assert status_path.is_file()
    on_disk = json.loads(status_path.read_text(encoding="utf-8"))
    assert on_disk == result


EXPLAINER = [
    {"step": 1, "capability": "voicestudio.speak", "handoff": "voice.wav", "verify": "v"},
    {"step": 2, "capability": "acestep.bed", "handoff": "bed.wav", "verify": "v"},
    {
        "step": 3,
        "capability": "ffmpeg.normalize",
        "handoff": ("voice-normalized.wav (clip voice.wav, target-lufs -16.0, true-peak-db -1.5)"),
        "verify": "v",
    },
    {
        "step": 4,
        "capability": "ffmpeg.mix",
        "handoff": (
            "mix.wav (voice voice-normalized.wav, bed bed.wav, ducking true, "
            "duck-db -12.0, target-lufs -16.0)"
        ),
        "verify": "v",
    },
    {
        "step": 5,
        "capability": "whisper.transcribe",
        "handoff": "transcript.txt + transcript.srt + transcript.json (audio voice-normalized.wav)",
        "verify": "v",
    },
    {
        "step": 6,
        "capability": "whisper-subs.subtitles",
        "handoff": "transcript.srt (source transcript.json, format srt)",
        "verify": "v",
    },
    {
        "step": 7,
        "capability": "hyperframes.narrated",
        "handoff": (
            "narrated.mp4 (composition narrated/, voice voice-normalized.wav, "
            "music bed.wav, subtitles transcript.srt)"
        ),
        "verify": "v",
    },
]


def _make_explainer_done(folder: Path, transcript_cap: str = "whisper-subs.subtitles") -> None:
    times = [
        "2026-01-01T00:00:01Z",
        "2026-01-01T00:00:02Z",
        "2026-01-01T00:00:03Z",
        "2026-01-01T00:00:04Z",
        "2026-01-01T00:00:05Z",
        "2026-01-01T00:00:06Z",
        "2026-01-01T00:00:07Z",
    ]
    _touch(folder / "voice.wav", "voicestudio.speak", times[0])
    _touch(folder / "bed.wav", "acestep.bed", times[1])
    _touch(folder / "voice-normalized.wav", "ffmpeg.normalize", times[2])
    _touch(folder / "mix.wav", "ffmpeg.mix", times[3])
    _touch(folder / "transcript.txt", "whisper.transcribe", times[4])
    _touch(folder / "transcript.json", "whisper.transcribe", times[4])
    _touch(folder / "transcript.srt", transcript_cap, times[5])
    _touch(folder / "narrated.mp4", "hyperframes.narrated", times[6])


def test_explainer_chain_complete_is_all_done(tmp_path: Path) -> None:
    folder = tmp_path / "piece"
    folder.mkdir()
    plan = _write_plan(folder, "explainer-video", EXPLAINER)
    _make_explainer_done(folder)
    done, result, status_path = _status(tmp_path, plan, "all-done")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert all(step["state"] == "done" for step in result["steps"])
    assert result["next_step"] is None
    _assert_matches_file(result, status_path)


def test_step6_undone_keeps_step5_done_via_shared_file(tmp_path: Path) -> None:
    folder = tmp_path / "piece"
    folder.mkdir()
    plan = _write_plan(folder, "explainer-video", EXPLAINER)
    _make_explainer_done(folder, transcript_cap="whisper.transcribe")
    done, result, status_path = _status(tmp_path, plan, "step6")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    by_index = {step["index"]: step for step in result["steps"]}
    undone_step = 6
    assert by_index[5]["state"] == "done"
    assert by_index[undone_step]["state"] == "stale"
    assert result["next_step"] == undone_step
    _assert_matches_file(result, status_path)


def test_missing_file_marks_step_missing(tmp_path: Path) -> None:
    folder = tmp_path / "piece"
    folder.mkdir()
    steps = [{"step": 1, "capability": "pkg.make", "handoff": "out.txt", "verify": "v"}]
    plan = _write_plan(folder, "tiny", steps)
    done, result, status_path = _status(tmp_path, plan, "missing")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert result["steps"][0]["state"] == "missing"
    assert result["steps"][0]["files"] == [{"file": "out.txt", "state": "missing"}]
    assert result["next_step"] == 1
    _assert_matches_file(result, status_path)


def test_stale_record_wrong_cap_and_old_created(tmp_path: Path) -> None:
    folder = tmp_path / "piece"
    folder.mkdir()
    steps = [
        {"step": 1, "capability": "pkg.a", "handoff": "a.txt", "verify": "v"},
        {"step": 2, "capability": "pkg.b", "handoff": "b.txt", "verify": "v"},
        {"step": 3, "capability": "pkg.c", "handoff": "c.txt", "verify": "v"},
    ]
    plan = _write_plan(folder, "stale", steps)
    _touch(folder / "a.txt", "pkg.a", "2026-01-01T00:00:02Z")
    _touch(folder / "b.txt", "pkg.wrong", "2026-01-01T00:00:03Z")
    _touch(folder / "c.txt", "pkg.c", "2026-01-01T00:00:01Z")
    done, result, status_path = _status(tmp_path, plan, "stale")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    by_index = {step["index"]: step for step in result["steps"]}
    first_bad = 2
    assert by_index[1]["state"] == "done"
    assert by_index[first_bad]["state"] == "stale"
    assert by_index[first_bad]["files"] == [{"file": "b.txt", "state": "stale"}]
    assert by_index[3]["state"] == "stale"
    assert by_index[3]["files"] == [{"file": "c.txt", "state": "stale"}]
    assert result["next_step"] == first_bad
    _assert_matches_file(result, status_path)


def test_directory_handoff_must_be_non_empty(tmp_path: Path) -> None:
    folder = tmp_path / "piece"
    folder.mkdir()
    steps = [{"step": 1, "capability": "pkg.dir", "handoff": "out/", "verify": "v"}]
    plan = _write_plan(folder, "dir", steps)

    (folder / "out").mkdir()
    done, result, status_path = _status(tmp_path, plan, "dir-empty")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert result["steps"][0]["state"] == "missing"
    assert result["steps"][0]["files"] == [{"file": "out/", "state": "missing"}]
    assert result["next_step"] == 1
    _assert_matches_file(result, status_path)

    (folder / "out" / "file.txt").write_text("x", encoding="utf-8")
    _write_record(folder / "out", "pkg.dir", "2026-01-01T00:00:01Z")
    # status file name for recipe "dir" is dir.status.json beside plan; previous call wrote it
    done2, result2, status_path2 = _status(tmp_path, plan, "dir-full")
    assert done2.returncode == 0, done2.stdout + done2.stderr
    assert result2 is not None
    assert result2["steps"][0]["state"] == "done"
    assert result2["steps"][0]["files"] == [{"file": "out/", "state": "done"}]
    assert result2["next_step"] is None
    _assert_matches_file(result2, status_path2)
