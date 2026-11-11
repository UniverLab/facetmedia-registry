"""The recetas runner against a stub SDK, no registry and no heavy tool.

The runner is a subprocess of the host ``python`` — the package is stdlib
only, so there is nothing to pull. Its ``PYTHONPATH`` carries a stub
``facet_runner_sdk`` (the pull-time SDK surface), so the test proves the
plan file's shape from the in-package recipes data, the exact ordered chains,
the ``<receta>.plan.json`` filename, the plain ``ValueError`` that facet
reports as ``runner_failed`` (exit 1), the verify verdicts, the generic
previews and the doctor checks without running any capability.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "recetas"
RUNNER = PACKAGE / "runner.py"

#: The exact decided chains, in order, one capability id per step.
CHAINS = {
    "video-explicativo": [
        "voicestudio.speak",
        "acestep.bed",
        "ffmpeg.normalize",
        "ffmpeg.mix",
        "whisper.transcribe",
        "whisper-subs.subtitulos",
        "hyperframes.narrated",
    ],
    "render-arq": ["cad.solid", "blender.assets", "blender.photo", "deck.pagina"],
    "material-voz": ["kokoro.speak", "acestep.bed", "deck.slides"],
    "demo-herramienta": ["demostage.demo", "deck.slides"],
}

#: The pull-time SDK surface the runner touches; the real one is copied in.
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
    """A directory holding the stub SDK, for PYTHONPATH."""
    folder = tmp_path / "stub-modules"
    folder.mkdir(exist_ok=True)
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    return folder


def _piece(tmp_path: Path) -> Path:
    """A piece directory; the recipe data lives in the package, not here."""
    piece = tmp_path / "piece"
    piece.mkdir(exist_ok=True)
    return piece


def _request(
    verb: str,
    out_dir: Path,
    piece_dir: Path,
    inputs: dict[str, object],
    assets: tuple[Path, ...] = (),
    depth: str = "quick",
) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "recetas.plan",
        "depth": depth,
        "inputs": inputs,
        "out_dir": str(out_dir),
        "piece_dir": str(piece_dir),
        "models": {},
        "assets": [str(path) for path in assets],
    }


def _call(
    stub_dir: Path,
    verb: str,
    request: dict[str, object],
    tmp_path: Path,
    tag: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    input_path = tmp_path / f"{tag}-{verb}-request.json"
    result_path = tmp_path / f"{tag}-{verb}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    result_path.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONPATH": str(stub_dir)}
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            verb,
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


def _run(
    tmp_path: Path, receta: str, tag: str = "run"
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, Path, Path]:
    """One ``run`` against a fresh piece and out dir; returns all the paths."""
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path)
    out = tmp_path / f"out-{tag}"
    out.mkdir()
    request = _request("run", out, piece, {"receta": receta})
    done, result = _call(stub_dir, "run", request, tmp_path, tag)
    return done, result, piece, out


def test_run_writes_each_recipe_plan_as_an_ordered_chain(tmp_path: Path) -> None:
    for receta, chain in CHAINS.items():
        done, result, _piece, out = _run(tmp_path, receta, tag=receta)
        assert done.returncode == 0, done.stdout + done.stderr
        assert result is not None
        path = out / f"{receta}.plan.json"
        assert path.is_file()
        plan = json.loads(path.read_text(encoding="utf-8"))
        assert plan["receta"] == receta
        assert isinstance(plan["summary"], str) and plan["summary"]
        assert [step["capability"] for step in plan["steps"]] == chain
        assert [step["step"] for step in plan["steps"]] == list(range(1, len(chain) + 1))
        for step in plan["steps"]:
            assert step["handoff"] and step["verify"]
        asset = result["assets"][0]
        assert asset["file"] == f"{receta}.plan.json"
        assert asset["kind"] == "text"
        assert asset["mime"] == "application/json"
        assert asset["properties"]["receta"] == receta
        assert asset["properties"]["steps"] == len(chain)
        assert asset["properties"]["packages"] == len({cap.split(".", 1)[0] for cap in chain})
        assert asset["params"] == {"receta": receta}


def test_the_video_recipe_carries_the_decided_handoffs(tmp_path: Path) -> None:
    done, _result, _piece, out = _run(tmp_path, "video-explicativo", tag="handoff")
    assert done.returncode == 0, done.stdout + done.stderr
    plan = json.loads((out / "video-explicativo.plan.json").read_text(encoding="utf-8"))
    handoffs = [step["handoff"] for step in plan["steps"]]
    assert "voz.wav" in handoffs[0]
    assert "voz-normalizada.wav" in handoffs[2] and "target-lufs -16.0" in handoffs[2]
    assert "true-peak-db -1.5" in handoffs[2]
    assert "ducking true" in handoffs[3] and "duck-db -12.0" in handoffs[3]
    assert "duck-db -12.0" in handoffs[3] and "target-lufs -16.0" in handoffs[3]
    assert "guion.srt" in handoffs[5] and "guion.json" in handoffs[5]
    assert "narrated.mp4" in handoffs[6]
    assert "composition narrated/" in handoffs[6]


def test_run_refuses_a_recipe_outside_the_enum(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path)
    out = tmp_path / "out-unknown"
    out.mkdir()
    done, result = _call(
        stub_dir,
        "run",
        _request("run", out, piece, {"receta": "otra"}),
        tmp_path,
        "unknown",
    )
    assert done.returncode != 0
    assert result is None
    assert "receta desconocida" in done.stderr
    assert not any(out.iterdir())


def test_verify_passes_a_run_plan_and_rejects_broken_ones(tmp_path: Path) -> None:
    done, _result, piece, out = _run(tmp_path, "material-voz", tag="verify-run")
    assert done.returncode == 0, done.stdout + done.stderr
    good = out / "material-voz.plan.json"
    out_of_order = tmp_path / "desordenado.plan.json"
    out_of_order.write_text(
        json.dumps(
            {
                "receta": "x",
                "summary": "",
                "steps": [{"step": 2, "capability": "a.b", "handoff": "h", "verify": "v"}],
            }
        ),
        encoding="utf-8",
    )
    incomplete = tmp_path / "incompleto.plan.json"
    incomplete.write_text(
        json.dumps(
            {
                "receta": "x",
                "summary": "",
                "steps": [{"step": 1, "capability": "a.b", "handoff": "", "verify": ""}],
            }
        ),
        encoding="utf-8",
    )
    stub_dir = _stub_dir(tmp_path)
    request = _request("verify", out, piece, {}, assets=(good, out_of_order, incomplete))
    done, verdict = _call(stub_dir, "verify", request, tmp_path, "verify")
    assert done.returncode == 0, done.stdout + done.stderr
    assert verdict is not None
    passed, desordenado, incompleto = verdict["assets"]
    assert passed["passed"] is True
    assert passed["verifier"] == "recetas"
    assert passed["thresholds"] == {"steps_min": 1}
    assert passed["metrics"]["steps"] == len(CHAINS["material-voz"])
    assert passed["metrics"]["ordered"] is True
    assert passed["metrics"]["complete"] is True
    assert desordenado["passed"] is False
    assert desordenado["metrics"]["ordered"] is False
    assert incompleto["passed"] is False
    assert incompleto["metrics"]["complete"] is False


def test_preview_writes_the_generic_scalars(tmp_path: Path) -> None:
    done, _result, piece, out = _run(tmp_path, "render-arq", tag="preview-run")
    assert done.returncode == 0, done.stdout + done.stderr
    name = "render-arq.plan.json"
    stub_dir = _stub_dir(tmp_path)
    request = _request("preview", out, piece, {"receta": "render-arq"}, assets=(out / name,))
    done, preview = _call(stub_dir, "preview", request, tmp_path, "preview")
    assert done.returncode == 0, done.stdout + done.stderr
    assert preview is not None
    assert [entry["file"] for entry in preview["assets"]] == [name]
    assert [entry["preview"] for entry in preview["assets"]] == [f"{name}.preview.json"]
    assert [entry["images"] for entry in preview["assets"]] == [[]]
    data = json.loads((out / f"{name}.preview.json").read_text(encoding="utf-8"))
    assert set(data) == {"preview", "kind", "summary", "fields"}
    assert data["preview"] == 1
    assert data["kind"] == "text"
    assert data["fields"] == {"receta": "render-arq", "steps": 4, "packages": 3}
    assert all(isinstance(value, (str, int)) for value in data["fields"].values())
    assert data["summary"] == "render-arq \u00b7 4 steps"


def test_doctor_quick_reports_files_recipes_and_answers(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path)
    out = tmp_path / "out-doctor"
    out.mkdir()
    quick, quick_result = _call(
        stub_dir,
        "doctor",
        _request("doctor", out, piece, {}, depth="quick"),
        tmp_path,
        "doctor-quick",
    )
    assert quick.returncode == 0, quick.stdout + quick.stderr
    assert quick_result is not None
    checks = {check["name"]: check for check in quick_result["checks"]}
    assert set(checks) == {"files", "recipes", "answers"}
    assert checks["files"]["ok"] is True
    assert "skill/SKILL.md" in checks["files"]["detail"]
    assert checks["recipes"]["ok"] is True
    assert checks["answers"]["ok"] is True
    for receta in CHAINS:
        assert receta in checks["answers"]["detail"]


def test_doctor_full_builds_one_plan_and_cleans_up(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path)
    out = tmp_path / "out-doctor-full"
    out.mkdir()
    full, full_result = _call(
        stub_dir,
        "doctor",
        _request("doctor", out, piece, {}, depth="full"),
        tmp_path,
        "doctor-full",
    )
    assert full.returncode == 0, full.stdout + full.stderr
    assert full_result is not None
    checks = {check["name"]: check for check in full_result["checks"]}
    assert checks["plan"]["ok"] is True, checks["plan"]
    assert not list(out.iterdir())
