"""The whisper-subs runner against a stub SDK, no model and no device.

The runner is a subprocess of the host ``python`` — the package is stdlib
only, so there is nothing to pull. Its ``PYTHONPATH`` carries a stub
``facet_runner_sdk`` (the pull-time SDK surface), so the test proves the
``.srt`` and ``.vtt`` byte shapes from a stub sidecar, the
``<source-stem>.<format>`` filename, the plain ``ValueError``s that facet
reports as ``runner_failed`` (exit 1, naming the 1-based cue), the verify
verdicts, the generic previews and the doctor checks without any real
transcription.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "whisper-subs"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
RUNNER = PACKAGE / "runner.py"
PREVIEW_FIELDS = {"preview", "kind", "summary", "cues", "duration_s", "format"}

#: The stub sidecar cue count and the last cue end, in seconds.
CUE_COUNT = 2
DURATION_S = 3.25

#: The five readability inputs exactly as the manifest and runner default them.
LIMIT_DEFAULTS = {
    "max-cps": 20.0,
    "max-line-chars": 42,
    "max-lines": 2,
    "min-cue-seconds": 0.8,
    "max-cue-seconds": 7.0,
}

#: Shaping counts asserted below: the worded segment's pieces by default,
#: under a four-second ceiling, the stub's cue durations, failing overs.
SHAPED_CUES = 2
TIGHT_CUES = 4
TIGHT_CEILING_S = 4.0
FIRST_CUE_S = 1.5
LAST_CUE_S = 1.75
OVER_CUES = 2

#: Two touching cues, exactly the shape whisper writes into its sidecar.
SIDECAR = {
    "segments": [
        {"start_s": 0.0, "end_s": 1.5, "text": "Hola."},
        {"start_s": 1.5, "end_s": 3.25, "text": "Mundo."},
    ]
}
EXPECTED_SRT = (
    "1\n00:00:00,000 --> 00:00:01,500\nHola.\n\n2\n00:00:01,500 --> 00:00:03,250\nMundo.\n"
)
EXPECTED_VTT = (
    "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHola.\n\n00:00:01.500 --> 00:00:03.250\nMundo.\n"
)

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


def _piece(tmp_path: Path, sidecar: dict[str, Any], name: str = "laboratorio.json") -> Path:
    """A piece dir whose sidecar is the two touching cues."""
    piece = tmp_path / "piece"
    piece.mkdir(exist_ok=True)
    (piece / name).write_text(json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")
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
        "capability": "whisper-subs.subtitles",
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
    tmp_path: Path,
    inputs: dict[str, object] | None = None,
    sidecar: dict[str, Any] | None = None,
    tag: str = "run",
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, Path, Path]:
    """One ``run`` against a fresh piece and out dir; returns all the paths."""
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path, SIDECAR if sidecar is None else sidecar)
    out = tmp_path / f"out-{tag}"
    out.mkdir()
    request = _request("run", out, piece, inputs or {"source": "laboratorio.json"})
    done, result = _call(stub_dir, "run", request, tmp_path, tag)
    return done, result, piece, out


def test_run_writes_the_srt_beside_the_piece_from_the_stem(tmp_path: Path) -> None:
    done, result, _piece, out = _run(tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    path = out / "laboratorio.srt"
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == EXPECTED_SRT
    asset = result["assets"][0]
    assert asset["file"] == "laboratorio.srt"
    assert asset["name"] == "laboratorio"
    assert asset["kind"] == "text"
    assert asset["mime"] == "application/x-subrip"
    assert asset["properties"] == {"cues": CUE_COUNT, "duration_s": DURATION_S, "format": "srt"}
    assert asset["seed"] is None
    assert asset["inputs"] == ["laboratorio.json"]
    assert asset["params"] == {"source": "laboratorio.json", "format": "srt", **LIMIT_DEFAULTS}
    assert result["tool"]["name"] == MANIFEST["tool_name"]


def test_run_writes_the_vtt_with_the_header_and_dot_times(tmp_path: Path) -> None:
    done, result, _piece, out = _run(
        tmp_path, inputs={"source": "laboratorio.json", "format": "vtt"}, tag="vtt"
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    path = out / "laboratorio.vtt"
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == EXPECTED_VTT
    asset = result["assets"][0]
    assert asset["mime"] == "text/vtt"
    assert asset["properties"] == {"cues": CUE_COUNT, "duration_s": DURATION_S, "format": "vtt"}


def test_run_fails_a_missing_source_as_a_plain_error(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path, SIDECAR)
    out = tmp_path / "out-missing"
    out.mkdir()
    done, result = _call(
        stub_dir,
        "run",
        _request("run", out, piece, {"source": "otro.json"}),
        tmp_path,
        "missing",
    )
    assert done.returncode != 0
    assert result is None
    assert "no such source" in done.stderr


def test_run_fails_an_overlap_naming_the_second_cue(tmp_path: Path) -> None:
    sidecar = {
        "segments": [
            {"start_s": 0.0, "end_s": 1.5, "text": "Hola."},
            {"start_s": 1.0, "end_s": 3.0, "text": "Mundo."},
        ]
    }
    done, result, _piece, out = _run(tmp_path, sidecar=sidecar, tag="overlap")
    assert done.returncode != 0
    assert result is None
    assert "cue 2: starts before cue 1 ends" in done.stderr
    assert not any(out.iterdir()), list(out.iterdir())


def test_run_fails_a_regression_naming_the_third_cue(tmp_path: Path) -> None:
    sidecar = {
        "segments": [
            {"start_s": 0.0, "end_s": 1.0, "text": "Hola."},
            {"start_s": 1.0, "end_s": 2.0, "text": "Mundo."},
            {"start_s": 1.5, "end_s": 3.0, "text": "Loco."},
        ]
    }
    done, result, _piece, out = _run(tmp_path, sidecar=sidecar, tag="regresion")
    assert done.returncode != 0
    assert result is None
    assert "cue 3: starts before cue 2 ends" in done.stderr


def test_verify_passes_the_run_outputs_and_rejects_a_broken_file(tmp_path: Path) -> None:
    done, result, _piece, out = _run(tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    (out / "laboratorio.vtt").write_text(EXPECTED_VTT, encoding="utf-8")
    broken = tmp_path / "wrong.srt"
    broken.write_text("2\n00:00:01,000 --> 00:00:02,000\nMundo.\n", encoding="utf-8")
    stub_dir = _stub_dir(tmp_path)
    request = _request(
        "verify",
        out,
        tmp_path / "piece",
        {"source": "laboratorio.json"},
        assets=(out / "laboratorio.srt", out / "laboratorio.vtt", broken),
    )
    done, verdict = _call(stub_dir, "verify", request, tmp_path, "verify")
    assert done.returncode == 0, done.stdout + done.stderr
    assert verdict is not None
    srt, vtt, bad = verdict["assets"]
    assert srt["file"] == "laboratorio.srt" and srt["passed"] is True
    assert srt["verifier"] == "whisper-subs"
    assert srt["thresholds"] == {"cues_min": 1}
    assert srt["metrics"]["cues"] == CUE_COUNT
    assert srt["metrics"]["duration_s"] == DURATION_S
    assert srt["metrics"]["monotonic"] is True
    assert srt["metrics"]["header"] is True
    assert vtt["passed"] is True and vtt["metrics"]["header"] is True
    assert bad["passed"] is False and bad["metrics"]["header"] is False


def test_verify_rejects_an_overlapping_file_and_a_missing_header(tmp_path: Path) -> None:
    overlap = tmp_path / "solape.srt"
    overlap.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHola.\n\n2\n00:00:01,000 --> 00:00:03,000\nMundo.\n",
        encoding="utf-8",
    )
    headerless = tmp_path / "sin-cabecera.vtt"
    headerless.write_text("00:00:00.000 --> 00:00:01.500\nHola.\n", encoding="utf-8")
    stub_dir = _stub_dir(tmp_path)
    tmp_path.joinpath("out-empty").mkdir()
    done, verdict = _call(
        stub_dir,
        "verify",
        _request(
            "verify",
            tmp_path / "out-empty",
            tmp_path / "piece",
            {},
            assets=(overlap, headerless),
        ),
        tmp_path,
        "verify-overlay",
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert verdict is not None
    solape, cabecera = verdict["assets"]
    assert solape["passed"] is False
    assert solape["metrics"]["monotonic"] is False
    assert solape["metrics"]["cues"] == CUE_COUNT
    assert cabecera["passed"] is False
    assert cabecera["metrics"]["header"] is False


def test_preview_writes_the_generic_fields_per_asset(tmp_path: Path) -> None:
    for tag, inputs, name in (
        ("srt", {"source": "laboratorio.json"}, "laboratorio.srt"),
        ("vtt", {"source": "laboratorio.json", "format": "vtt"}, "laboratorio.vtt"),
    ):
        done, _result, _piece, out = _run(tmp_path, inputs=inputs, tag=f"preview-{tag}")
        assert done.returncode == 0, done.stdout + done.stderr
        stub_dir = _stub_dir(tmp_path)
        done, preview = _call(
            stub_dir,
            "preview",
            _request("preview", out, tmp_path / "piece", inputs, assets=(out / name,)),
            tmp_path,
            f"preview-{tag}",
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert preview is not None
        assert [entry["file"] for entry in preview["assets"]] == [name]
        assert [entry["preview"] for entry in preview["assets"]] == [f"{name}.preview.json"]
        assert [entry["images"] for entry in preview["assets"]] == [[]]
        data = json.loads((out / f"{name}.preview.json").read_text(encoding="utf-8"))
        assert set(data) == {"preview", "kind", "summary", "fields"}
        assert data["preview"] == 1
        assert data["kind"] == "text"
        assert set(data["fields"]) == {"cues", "duration_s", "format"}
        assert data["fields"] == {"cues": CUE_COUNT, "duration_s": DURATION_S, "format": tag}
        assert data["summary"] == "2 cues \u00b7 3.2 s \u00b7 " + tag


def test_doctor_quick_reports_files_and_formats(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path, SIDECAR)
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
    assert set(checks) == {"files", "formats"}
    assert checks["files"]["ok"] is True
    assert "skill/SKILL.md" in checks["files"]["detail"]
    assert checks["formats"]["ok"] is True
    assert "00:00:01,500" in checks["formats"]["detail"]
    assert "00:00:01.500" in checks["formats"]["detail"]


def _stamp(seconds: float) -> str:
    """One ``HH:MM:SS,mmm`` stamp, the way the runner writes SRT times."""
    total = round(seconds * 1000)
    hours, rest = divmod(total, 3600000)
    minutes, rest = divmod(rest, 60000)
    whole, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def _srt(cues: list[tuple[float, float, str]]) -> str:
    """A subtitle fixture from ``(start, end, text)`` cues, never a model."""
    blocks = [
        f"{number}\n{_stamp(start)} --> {_stamp(end)}\n{text}\n"
        for number, (start, end, text) in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)


def _worded_sidecar() -> dict[str, Any]:
    """One ten-second segment with even word timings, the splittable case."""
    words = [
        {
            "start_s": index * 0.5,
            "end_s": index * 0.5 + 0.4,
            "word": f"w{index}",
            "probability": 0.9,
        }
        for index in range(20)
    ]
    text = " ".join(f"w{index}" for index in range(20))
    return {"segments": [{"start_s": 0.0, "end_s": 10.0, "text": text, "words": words}]}


def _verify_file(
    tmp_path: Path, text: str, inputs: dict[str, object] | None = None, tag: str = "rule"
) -> dict[str, Any] | None:
    """One ``verify`` of a written subtitle fixture; returns the verdict."""
    path = tmp_path / f"{tag}.srt"
    path.write_text(text, encoding="utf-8")
    stub_dir = _stub_dir(tmp_path)
    out = tmp_path / f"out-{tag}"
    out.mkdir(exist_ok=True)
    _done, verdict = _call(
        stub_dir,
        "verify",
        _request("verify", out, tmp_path / "piece", inputs or {}, assets=(path,)),
        tmp_path,
        tag,
    )
    assert _done.returncode == 0, _done.stdout + _done.stderr
    assert verdict is not None
    return verdict["assets"][0]


def test_run_shapes_a_long_word_timed_segment(tmp_path: Path) -> None:
    done, result, _piece, out = _run(tmp_path, sidecar=_worded_sidecar(), tag="shaped")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    text = (out / "laboratorio.srt").read_text(encoding="utf-8")
    assert text.count("-->") == SHAPED_CUES
    assert result["assets"][0]["properties"]["cues"] == SHAPED_CUES
    assert result["assets"][0]["params"] == {
        "source": "laboratorio.json",
        "format": "srt",
        **LIMIT_DEFAULTS,
    }


def test_run_honors_a_tighter_cue_ceiling(tmp_path: Path) -> None:
    inputs: dict[str, object] = {"source": "laboratorio.json", "max-cue-seconds": TIGHT_CEILING_S}
    done, result, _piece, _out = _run(
        tmp_path, inputs=inputs, sidecar=_worded_sidecar(), tag="tight"
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert result["assets"][0]["properties"]["cues"] == TIGHT_CUES
    assert result["assets"][0]["params"]["max-cue-seconds"] == TIGHT_CEILING_S


def test_run_rejects_a_bad_limit_as_a_plain_error(tmp_path: Path) -> None:
    inputs: dict[str, object] = {"source": "laboratorio.json", "max-cps": "fast"}
    done, result, _piece, _out = _run(tmp_path, inputs=inputs, tag="bad-limit")
    assert done.returncode != 0
    assert result is None
    assert "bad readability limit" in done.stderr


def test_verify_reports_the_readability_metrics(tmp_path: Path) -> None:
    done, result, _piece, out = _run(tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    stub_dir = _stub_dir(tmp_path)
    request = _request(
        "verify",
        out,
        tmp_path / "piece",
        {"source": "laboratorio.json"},
        assets=(out / "laboratorio.srt",),
    )
    _done, verdict = _call(stub_dir, "verify", request, tmp_path, "metrics")
    assert _done.returncode == 0, _done.stdout + _done.stderr
    assert verdict is not None
    metrics = verdict["assets"][0]["metrics"]
    assert metrics["worst-cps"] == round(6 / 1.75, 3)
    assert metrics["longest-line-chars"] == len("Mundo.")
    assert metrics["most-lines"] == 1
    assert metrics["shortest-cue-seconds"] == FIRST_CUE_S
    assert metrics["longest-cue-seconds"] == LAST_CUE_S
    assert metrics["cues-over-limit"] == 0
    assert verdict["assets"][0]["passed"] is True


def test_verify_passes_a_single_forced_cue(tmp_path: Path) -> None:
    verdict = _verify_file(tmp_path, _srt([(0.0, 1.0, "x" * 60)]), tag="single")
    assert verdict is not None
    assert verdict["metrics"]["cues-over-limit"] == 1
    assert verdict["passed"] is True


def test_verify_fails_two_over_cues_in_ten(tmp_path: Path) -> None:
    cues = [(float(index), float(index + 1), "ok") for index in range(8)]
    cues += [(8.0, 9.0, "x" * 60), (9.0, 10.0, "y" * 60)]
    verdict = _verify_file(tmp_path, _srt(cues), tag="two-in-ten")
    assert verdict is not None
    assert verdict["metrics"]["cues-over-limit"] == OVER_CUES
    assert verdict["passed"] is False


def test_verify_passes_two_over_cues_in_a_hundred(tmp_path: Path) -> None:
    cues = [(float(index), float(index + 1), "ok") for index in range(98)]
    cues += [(98.0, 99.0, "x" * 60), (99.0, 100.0, "y" * 60)]
    verdict = _verify_file(tmp_path, _srt(cues), tag="two-in-hundred")
    assert verdict is not None
    assert verdict["metrics"]["cues-over-limit"] == OVER_CUES
    assert verdict["passed"] is True


def test_verify_honors_the_raised_limits_it_is_given(tmp_path: Path) -> None:
    cues = [(float(index), float(index + 1), "ok") for index in range(8)]
    cues += [(8.0, 9.0, "x" * 60), (9.0, 10.0, "y" * 60)]
    text = _srt(cues)
    failing = _verify_file(tmp_path, text, tag="raised-fails")
    assert failing is not None and failing["passed"] is False
    raised = _verify_file(
        tmp_path, text, {"max-cps": 100.0, "max-line-chars": 100}, tag="raised-passes"
    )
    assert raised is not None
    assert raised["metrics"]["cues-over-limit"] == 0
    assert raised["passed"] is True


def test_doctor_full_builds_both_formats_and_cleans_up(tmp_path: Path) -> None:
    stub_dir = _stub_dir(tmp_path)
    piece = _piece(tmp_path, SIDECAR)
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
    assert checks["subtitles"]["ok"] is True, checks["subtitles"]
    # The doctor leaves nothing in the out dir: build, check, remove.
    assert not list(out.iterdir())
