"""The whisper runner against a stub SDK and a stub faster-whisper, no model.

The runner is a subprocess of the host ``python`` with a stub
``facet_runner_sdk`` on ``PYTHONPATH`` (the pull-time surface the real one
copies in) and a stub ``faster_whisper`` that records every ``transcribe``
call and returns scripted segments. The registry's own ``lib/textnorm.py`` is
copied into the stub ``facet_lib``. No model, no network, no GPU: these cases
check the arguments the runner hands the model, which is exactly where the
glossary lives.

What a person must be able to read from this file: a piece's ``glossary``
reaches the model as its ``initial_prompt``; a piece without one leaves the
prompt empty rather than inventing one; a glossary over 400 characters is a
plain ``ValueError`` that facet reports as ``runner_failed`` instead of being
silently truncated into the prompt window; and the run record keeps the
glossary used beside the other params.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "whisper"
RUNNER = PACKAGE / "runner.py"

#: The glossary this lab's transcripts keep misspelling without one.
GLOSSARY = "UniverLab, facetMedia, Canopy, ComfyUI."
#: The manifest's bound, mirrored here so the test states what it enforces.
GLOSSARY_LIMIT = 400
#: A glossary of 401 characters: one over the limit, so it must be refused.
TOO_LONG = "UniverLab " * 41
#: The manifest's fixed decode setup, mirrored so the call is fully asserted.
BEAM_SIZE = 5
SEGMENT_TEXT = " En UniverLab hablamos de Canopy."

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

#: A stub faster-whisper: each load and each transcribe is recorded verbatim,
#: so the test reads the kwargs the runner actually passed.
STUB_WHISPER = """
import json
import os

CALLS = os.environ["STUB_CALLS"]
HEARD = os.environ.get("STUB_HEARD", "En UniverLab hablamos de Canopy.")


def _record(item):
    with open(CALLS, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(item) + "\\n")


class _Word:
    def __init__(self, start, end, word, probability):
        self.start = start
        self.end = end
        self.word = word
        self.probability = probability


class _Segment:
    def __init__(self, text):
        self.start = 0.0
        self.end = 1.5
        self.text = text
        self.avg_logprob = -0.2
        self.no_speech_prob = 0.01
        self.words = [_Word(0.0, 0.4, " " + text.split()[0], 0.99)]


class _Info:
    def __init__(self, language):
        self.language = language or "es"
        self.language_probability = 0.98
        self.duration = 1.5


class WhisperModel:
    def __init__(self, path, device="cpu", compute_type="int8"):
        _record({"call": "load", "path": path, "device": device,
                 "compute_type": compute_type})

    def transcribe(self, path, language=None, beam_size=None, vad_filter=False,
                   word_timestamps=False, initial_prompt=None):
        _record({"call": "transcribe", "path": path, "language": language,
                 "beam_size": beam_size, "vad_filter": vad_filter,
                 "word_timestamps": word_timestamps,
                 "initial_prompt": initial_prompt})
        return [_Segment(HEARD)], _Info(language)
"""


def _stub_dir(tmp_path: Path) -> Path:
    """The PYTHONPATH stub: SDK, faster-whisper and facet_lib with textnorm."""
    folder = tmp_path / "stub"
    folder.mkdir()
    (folder / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    (folder / "faster_whisper.py").write_text(STUB_WHISPER, encoding="utf-8")
    facet_lib = folder / "facet_lib"
    facet_lib.mkdir()
    (facet_lib / "__init__.py").write_text("", encoding="utf-8")
    (facet_lib / "textnorm.py").write_text(
        (ROOT / "lib" / "textnorm.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return folder


def _request(out: Path, piece: Path, inputs: dict[str, object], audio: Path, model: Path) -> dict:
    return {
        "protocol": 1,
        "verb": "run",
        "capability": "whisper.transcribe",
        "depth": "quick",
        "inputs": inputs,
        "out_dir": str(out),
        "piece_dir": str(piece),
        "models": {"faster-whisper-small-transcribe": str(model)},
        "assets": [],
    }


def _run(
    tmp_path: Path, inputs: dict[str, object], tag: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, list[dict[str, Any]]]:
    """One ``run`` verb as a subprocess over the stub environment."""
    stub_dir = _stub_dir(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    piece = tmp_path / "piece"
    piece.mkdir()
    audio = out / "laboratorio.flac"
    audio.write_bytes(b"fLaC" + b"\x00" * 16)
    model = tmp_path / "faster-whisper-small-transcribe"
    model.mkdir()
    calls = tmp_path / f"{tag}-whisper-calls.jsonl"
    calls.touch()
    request_path = tmp_path / f"{tag}-request.json"
    result_path = tmp_path / f"{tag}-result.json"
    request_path.write_text(
        json.dumps(_request(out, piece, inputs, audio, model)), encoding="utf-8"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "STUB_CALLS": str(calls),
        "STUB_HEARD": SEGMENT_TEXT,
    }
    done = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "run",
            "--input",
            str(request_path),
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
    lines = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines() if line]
    return done, result, lines


def _transcriptions(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [call for call in calls if call.get("call") == "transcribe"]


def _inputs(**extra: object) -> dict[str, object]:
    """The reference piece's fields, with whatever the case adds."""
    return {
        "audio": "laboratorio.flac",
        "name": "laboratorio",
        "language": "es",
        **extra,
    }


def test_the_glossary_reaches_the_model_as_its_initial_prompt(tmp_path: Path) -> None:
    """The piece's glossary is the model's ``initial_prompt``, nothing else."""
    done, result, calls = _run(tmp_path, _inputs(glossary=GLOSSARY), "glossary")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    heard = _transcriptions(calls)
    assert len(heard) == 1
    assert heard[0]["initial_prompt"] == GLOSSARY
    assert heard[0]["language"] == "es"
    assert heard[0]["vad_filter"] is True
    assert heard[0]["word_timestamps"] is True


def test_a_piece_without_a_glossary_passes_no_prompt(tmp_path: Path) -> None:
    """Absent glossary: the call is exactly as before it existed."""
    done, result, calls = _run(tmp_path, _inputs(), "no-glossary")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    heard = _transcriptions(calls)
    assert len(heard) == 1
    assert heard[0]["initial_prompt"] is None
    assert heard[0]["beam_size"] == BEAM_SIZE


def test_a_blank_glossary_passes_no_prompt(tmp_path: Path) -> None:
    """Whitespace is not a glossary: it must not become the prompt."""
    done, result, calls = _run(tmp_path, _inputs(glossary="   "), "blank-glossary")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert _transcriptions(calls)[0]["initial_prompt"] is None
    assert "glossary" not in result["assets"][0]["params"]


def test_the_record_keeps_the_glossary_used(tmp_path: Path) -> None:
    """The params carry the glossary beside the audio, the language and the name."""
    done, result, calls = _run(tmp_path, _inputs(glossary=f"  {GLOSSARY}  "), "record")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    params = result["assets"][0]["params"]
    assert params["glossary"] == GLOSSARY
    assert params["audio"] == "laboratorio.flac"
    assert params["language"] == "es"
    assert params["name"] == "laboratorio"
    assert _transcriptions(calls)[0]["initial_prompt"] == GLOSSARY


def test_a_glossary_over_the_limit_fails_the_run(tmp_path: Path) -> None:
    """401 characters is refused, not truncated; the model is never loaded."""
    assert len(TOO_LONG) > GLOSSARY_LIMIT
    done, result, calls = _run(tmp_path, _inputs(glossary=" " + TOO_LONG), "too-long")
    assert done.returncode != 0
    assert result is None
    assert "glossary" in done.stderr
    assert str(GLOSSARY_LIMIT) in done.stderr
    assert calls == []


def test_a_glossary_exactly_at_the_limit_is_accepted(tmp_path: Path) -> None:
    """400 characters fit the prompt window: the bound is inclusive."""
    at_limit = "U" * GLOSSARY_LIMIT
    done, result, calls = _run(tmp_path, _inputs(glossary=at_limit), "at-limit")
    assert done.returncode == 0, done.stdout + done.stderr
    assert result is not None
    assert _transcriptions(calls)[0]["initial_prompt"] == at_limit
    assert result["assets"][0]["params"]["glossary"] == at_limit
