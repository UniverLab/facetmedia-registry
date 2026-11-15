"""The rhubarb pull/run/verify/preview/doctor cycle, with no real Rhubarb.

The test stands in for the package environment: it runs ``runner.py`` as a
subprocess against a stub ``facet_runner_sdk`` and a stub Rhubarb zip holding
an executable ``rhubarb`` script. The stub records its argv (so the phonetic
flag is proven, not assumed), writes the ``mouths.json`` Rhubarb writes, and can
be told to fail, or to be a binary this machine cannot start. No test touches
the real 87 MB zip.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "rhubarb"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
MODEL_ID = "rhubarb-lip-sync-1.14.0-linux"
TOP_DIR = "Rhubarb-Lip-Sync-1.14.0-Linux"
ELF_NAME = "rhubarb"
MARKER_NAME = "zip.sha256"
EXTRACT_ENV = "RHUBARB_HOME"
VOICE = "character/voz.wav"
DIALOGUE = "character/dialogue.txt"
DIALOG_TEXT = "Hola, soy un zorro de dibujo."
PULL_FIX = "facet pull rhubarb"
CUES = [
    {"start": 0.0, "end": 0.2, "value": "X"},
    {"start": 0.2, "end": 0.45, "value": "B"},
    {"start": 0.45, "end": 0.6, "value": "A"},
    {"start": 0.6, "end": 0.8, "value": "C"},
    {"start": 0.8, "end": 0.95, "value": "E"},
    {"start": 0.95, "end": 1.2, "value": "X"},
]
DURATION = 1.2
MOUTHS = "XABCE"
SUMMARY_MAX = 160

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

#: The stub ELF the zip holds. ``__PYTHON__`` becomes the running interpreter,
#: and STUB_RHUBARB_LOG / STUB_RHUBARB_FAIL steer its answers.
STUB_ELF = """#!__PYTHON__
import json
import os
import sys
from pathlib import Path

CUES = [
    {"start": 0.0, "end": 0.2, "value": "X"},
    {"start": 0.2, "end": 0.45, "value": "B"},
    {"start": 0.45, "end": 0.6, "value": "A"},
    {"start": 0.6, "end": 0.8, "value": "C"},
    {"start": 0.8, "end": 0.95, "value": "E"},
    {"start": 0.95, "end": 1.2, "value": "X"},
]


def record():
    log = os.environ.get("STUB_RHUBARB_LOG")
    if not log:
        return
    entry = {
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "cwd_res": Path("res").is_dir(),
        "elf_res": (Path(sys.argv[0]).resolve().parent / "res").is_dir(),
    }
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry) + "\\n")


def main():
    record()
    args = sys.argv[1:]
    if args[:1] == ["--help"]:
        print("usage: rhubarb [options] <audio-file>")
        return 0
    if os.environ.get("STUB_RHUBARB_FAIL") == "1":
        print("stub rhubarb: phonetic recognizer exploded", file=sys.stderr)
        return 3
    out = Path(args[args.index("-o") + 1])
    if not out.is_absolute():
        out = Path(os.getcwd()) / out
    if not out.parent.is_dir():
        print("basic_ios::clear: iostream error", file=sys.stderr)
        return 1
    out.write_text(json.dumps({"metadata": {"duration": 1.2}, "mouthCues": CUES}))
    return 0


raise SystemExit(main())
"""


def _stubs(tmp_path: Path) -> Path:
    """The PYTHONPATH stub dir holding ``facet_runner_sdk``."""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(exist_ok=True)
    (stub_dir / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    return stub_dir


def _zip_bytes(elf_text: str, pad: int = 0) -> bytes:
    """A zip shaped like the release: one top dir with the ELF and its res/."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        info = zipfile.ZipInfo(f"{TOP_DIR}/{ELF_NAME}")
        info.external_attr = 0o755 << 16
        bundle.writestr(info, elf_text)
        bundle.writestr(f"{TOP_DIR}/res/", b"")
        bundle.writestr(f"{TOP_DIR}/README.adoc", b"Rhubarb Lip Sync\n")
        if pad:
            # Stored, so each pad byte grows the file by exactly one byte.
            bundle.writestr(
                zipfile.ZipInfo(f"{TOP_DIR}/res/pad.bin"), b"\0" * pad, zipfile.ZIP_STORED
            )
    return buffer.getvalue()


def _sized_zip(elf_text: str, target: int) -> bytes:
    """A release-shaped zip whose *file* size is exactly ``target`` bytes.

    The doctor compares the archive with the manifest's byte count, so the
    doctor tests need a zip of that size; two builds pin it, because a stored
    member grows the file one byte per pad byte.
    """
    probe = _zip_bytes(elf_text, pad=1)
    pad = target - (len(probe) - 1)
    data = _zip_bytes(elf_text, pad=pad)
    assert len(data) == target, (len(data), target)
    return data


DECLARED_BYTES = int(MANIFEST["models"][0]["bytes"])
SHA256_HEX = 64


def _model(tmp_path: Path, elf_text: str | None = None, pad: int = 0) -> Path:
    """The pinned zip at the manifest's ``path`` under a fake models dir."""
    text = elf_text if elf_text is not None else STUB_ELF.replace("__PYTHON__", sys.executable)
    declared = MANIFEST["models"][0]["path"]
    target = tmp_path / "home" / "models" / "direct" / declared
    target.parent.mkdir(parents=True)
    target.write_bytes(_zip_bytes(text, pad=pad))
    return target


def _declared_model(tmp_path: Path, elf_text: str | None = None) -> Path:
    """The pinned zip padded to exactly the manifest's byte count."""
    text = elf_text if elf_text is not None else STUB_ELF.replace("__PYTHON__", sys.executable)
    declared = MANIFEST["models"][0]["path"]
    target = tmp_path / "home" / "models" / "direct" / declared
    target.parent.mkdir(parents=True)
    target.write_bytes(_sized_zip(text, DECLARED_BYTES))
    return target


def _piece(tmp_path: Path) -> Path:
    """A piece dir whose ``character/`` holds the voice and the dialog."""
    piece_dir = tmp_path / "piece"
    character = piece_dir / "character"
    character.mkdir(parents=True)
    (character / "voz.wav").write_bytes(b"RIFF0000WAVE")
    (character / "dialogue.txt").write_text(DIALOG_TEXT + "\n", encoding="utf-8")
    (piece_dir / "zorro.toml").write_text(
        f'[inputs]\nvoice = "{VOICE}"\ndialogue = "{DIALOGUE}"\n', encoding="utf-8"
    )
    return piece_dir


def _environment(
    stub_dir: Path, extract_dir: Path, extra: dict[str, str] | None = None
) -> dict[str, str]:
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        EXTRACT_ENV: str(extract_dir),
    }
    if extra:
        env.update(extra)
    return env


def _request(
    verb: str,
    out: Path,
    piece: Path,
    inputs: dict[str, object],
    models: dict[str, Path],
    assets: tuple[Path, ...] = (),
    depth: str = "quick",
) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "rhubarb.mouths",
        "depth": depth,
        "inputs": dict(inputs),
        "out_dir": str(out),
        "piece_dir": str(piece),
        "assets": [str(path) for path in assets],
        "models": {model_id: str(path) for model_id, path in models.items()},
    }


def _invoke(
    verb: str,
    request: dict[str, object],
    tmp_path: Path,
    env: dict[str, str],
    tag: str = "",
    cwd: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    input_path = tmp_path / f"{verb}{tag}-request.json"
    result_path = tmp_path / f"{verb}{tag}-result.json"
    input_path.write_text(json.dumps(request), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            str(PACKAGE / "runner.py"),
            verb,
            "--input",
            str(input_path),
            "--result",
            str(result_path),
        ],
        env=env,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return done, result_path


def _call(
    verb: str,
    request: dict[str, object],
    tmp_path: Path,
    env: dict[str, str],
    tag: str = "",
    cwd: Path | None = None,
) -> tuple[dict[str, Any], str]:
    done, result_path = _invoke(verb, request, tmp_path, env, tag, cwd)
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(result_path.read_text(encoding="utf-8")), done.stdout


def _inputs() -> dict[str, object]:
    return {"voice": VOICE, "dialogue": DIALOGUE}


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _run_cycle(
    tmp_path: Path, elf_text: str | None = None
) -> tuple[dict[str, Any], str, list[dict[str, Any]], Path, dict[str, str]]:
    """One successful run; its result, its output, the stub log, the out dir, env."""
    stub_dir = _stubs(tmp_path)
    archive = _model(tmp_path, elf_text)
    log = tmp_path / "rhubarb.jsonl"
    env = _environment(stub_dir, tmp_path / "extract", {"STUB_RHUBARB_LOG": str(log)})
    piece_dir = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    result, printed = _call(
        "run",
        _request("run", out, piece_dir, _inputs(), {MODEL_ID: archive}),
        tmp_path,
        env,
    )
    return result, printed, _read_lines(log), out, env


def test_run_passes_the_phonetic_recognizer_and_json_output(tmp_path: Path) -> None:
    """The flags the spec exists for: ``-r phonetic -f json`` are in the argv."""
    _result, _printed, entries, out, _env = _run_cycle(tmp_path)
    assert len(entries) == 1, entries
    argv = entries[0]["argv"]
    assert "-r" in argv and argv[argv.index("-r") + 1] == "phonetic"
    assert "-f" in argv and argv[argv.index("-f") + 1] == "json"
    assert "--dialogFile" in argv
    assert argv[argv.index("--dialogFile") + 1].endswith(DIALOGUE)
    assert argv[argv.index("-o") + 1].endswith("mouths.json")
    # Rhubarb's argv puts the WAV before -o; the ZIP keeps res/ beside the ELF,
    # but the run's cwd is the writable out dir, not the ELF's own directory.
    voice = next(index for index, token in enumerate(argv) if token.endswith(VOICE))
    assert voice < argv.index("-o")
    assert entries[0]["elf_res"] is True
    assert entries[0]["cwd_res"] is False
    assert entries[0]["cwd"] == str(out)


def test_the_run_uses_the_out_dir_as_cwd(tmp_path: Path) -> None:
    """The closure fix: the ELF runs from the writable out dir, not its own."""
    _result, _printed, entries, out, _env = _run_cycle(tmp_path)
    assert entries[0]["cwd"] == str(out)
    assert (out / "mouths.json").is_file()
    cues = json.loads((out / "mouths.json").read_text(encoding="utf-8"))["mouthCues"]
    assert cues
    assert all(cue["value"] in "XABCDEFGH" for cue in cues)


def test_the_relative_output_defect_is_reproduced(tmp_path: Path) -> None:
    """The real closure finding: a relative ``-o`` under a changed cwd writes nothing."""
    _result, _printed, _entries, _out, env = _run_cycle(tmp_path)
    elf = Path(env[EXTRACT_ENV]) / "_rhubarb-lip-sync-1.14.0-linux" / TOP_DIR / ELF_NAME
    job = tmp_path / ".facet-tmp-1"
    job.mkdir()
    nested = job / ".facet-tmp-1" / "mouths.json"
    failed = subprocess.run(
        [
            sys.executable,
            str(elf),
            "-r",
            "phonetic",
            "-f",
            "json",
            "-o",
            ".facet-tmp-1/mouths.json",
        ],
        cwd=job,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert failed.returncode == 1
    assert "basic_ios::clear" in failed.stderr
    assert not nested.exists()

    absolute = job / "mouths.json"
    passed = subprocess.run(
        [sys.executable, str(elf), "-r", "phonetic", "-f", "json", "-o", str(absolute)],
        cwd=elf.parent,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert passed.returncode == 0, passed.stderr
    assert json.loads(absolute.read_text(encoding="utf-8"))["mouthCues"]


def test_a_relative_out_dir_lands_mouths_json_with_its_cues(tmp_path: Path) -> None:
    """facet passes a relative out dir; the runner absolutizes cwd, ``-o`` and the read."""
    stub_dir = _stubs(tmp_path)
    archive = _model(tmp_path)
    log = tmp_path / "relative.jsonl"
    env = _environment(stub_dir, tmp_path / "extract", {"STUB_RHUBARB_LOG": str(log)})
    out_name = ".facet-tmp-1"
    out = tmp_path / out_name
    out.mkdir()
    request = _request("run", Path(out_name), _piece(tmp_path), _inputs(), {MODEL_ID: archive})
    result, _printed = _call("run", request, tmp_path, env, tag="-relative", cwd=tmp_path)

    target = out / "mouths.json"
    assert target.is_file()
    cues = json.loads(target.read_text(encoding="utf-8"))["mouthCues"]
    assert cues
    assert result["assets"][0]["properties"]["cues"] == len(cues)
    entry = _read_lines(log)[0]
    assert entry["cwd"] == str(out)
    assert Path(entry["argv"][entry["argv"].index("-o") + 1]).is_absolute()


def _runner_module(tmp_path: Path) -> Any:
    """``runner.py`` imported against the stub SDK, to reach the flag guard."""
    stub_dir = _stubs(tmp_path)
    sys.path.insert(0, str(stub_dir))
    try:
        spec = importlib.util.spec_from_file_location("rhubarb_runner_probe", PACKAGE / "runner.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(stub_dir))
        sys.modules.pop("facet_runner_sdk", None)
    return module


def test_a_run_without_the_phonetic_flag_is_refused(tmp_path: Path) -> None:
    """A Spanish run that lost ``-r phonetic`` exits 1 naming the English trap."""
    module = _runner_module(tmp_path)
    argv = ["rhubarb", "-f", "json", "voz.wav", "-o", "mouths.json"]
    try:
        module.check_phonetic(argv)
    except RuntimeError as exc:
        assert "-r phonetic" in str(exc)
        assert "English" in str(exc)
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("an argv without -r phonetic was accepted")
    module.check_phonetic(["rhubarb", "-r", "phonetic", "-f", "json", "voz.wav"])


def test_the_command_builder_always_carries_both_flags(tmp_path: Path) -> None:
    """The argv the runner builds is the one the guard accepts."""
    module = _runner_module(tmp_path)
    argv = module.command(
        Path("/x/rhubarb"), Path("voz.wav"), Path("dialogue.txt"), Path("mouths.json")
    )
    assert argv[1:5] == ["-r", "phonetic", "-f", "json"]
    module.check_phonetic(argv)


def test_the_run_writes_one_text_asset_with_the_mouth_properties(tmp_path: Path) -> None:
    result, _printed, _entries, out, _env = _run_cycle(tmp_path)
    asset = result["assets"][0]
    assert asset["file"] == "mouths.json"
    assert asset["name"] == "mouths"
    assert (asset["kind"], asset["mime"]) == ("text", "application/json")
    assert asset["properties"] == {"duration_s": DURATION, "cues": len(CUES), "mouths": 5}
    assert asset["params"] == {"voice": VOICE, "dialogue": DIALOGUE}
    assert asset["seed"] is None
    assert asset["inputs"] == [VOICE, DIALOGUE]
    assert result["tool"] == {"name": "rhubarb-lip-sync", "version": "1.14.0"}
    assert (out / "mouths.json").is_file()


def test_the_zip_is_extracted_once_beside_its_marker(tmp_path: Path) -> None:
    _result, _printed, _entries, _out, env = _run_cycle(tmp_path)
    root = Path(env[EXTRACT_ENV]) / "_rhubarb-lip-sync-1.14.0-linux"
    elf = root / TOP_DIR / ELF_NAME
    assert elf.is_file()
    assert os.access(elf, os.X_OK)
    assert (root / TOP_DIR / "res").is_dir()
    digest = (root / MARKER_NAME).read_text(encoding="utf-8").strip()
    assert len(digest) == SHA256_HEX
    stamp = elf.stat().st_mtime_ns

    piece_dir = tmp_path / "piece"
    out = tmp_path / "out2"
    out.mkdir()
    archive = tmp_path / "home" / "models" / "direct" / MANIFEST["models"][0]["path"]
    _call(
        "run",
        _request("run", out, piece_dir, _inputs(), {MODEL_ID: archive}),
        tmp_path,
        env,
        tag="-again",
    )
    assert elf.stat().st_mtime_ns == stamp, "a matching marker must not re-extract"


def test_a_failing_rhubarb_fails_the_run_as_runner_failed(tmp_path: Path) -> None:
    stub_dir = _stubs(tmp_path)
    archive = _model(tmp_path)
    env = _environment(stub_dir, tmp_path / "extract", {"STUB_RHUBARB_FAIL": "1"})
    piece_dir = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    done, result_path = _invoke(
        "run",
        _request("run", out, piece_dir, _inputs(), {MODEL_ID: archive}),
        tmp_path,
        env,
    )
    assert done.returncode != 0
    assert "exited 3" in done.stdout + done.stderr
    assert not result_path.exists()


def test_a_missing_zip_fails_the_run_naming_the_pull(tmp_path: Path) -> None:
    stub_dir = _stubs(tmp_path)
    missing = tmp_path / "home" / "models" / "direct" / MANIFEST["models"][0]["path"]
    env = _environment(stub_dir, tmp_path / "extract")
    out = tmp_path / "out"
    out.mkdir()
    done, _result_path = _invoke(
        "run",
        _request("run", out, _piece(tmp_path), _inputs(), {MODEL_ID: missing}),
        tmp_path,
        env,
    )
    assert done.returncode != 0
    assert PULL_FIX in done.stdout + done.stderr


def _verify(tmp_path: Path, body: str, tag: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    stub_dir = _stubs(tmp_path)
    env = _environment(stub_dir, tmp_path / "extract")
    out = tmp_path / f"verify-{tag}"
    out.mkdir()
    target = out / "mouths.json"
    target.write_text(body, encoding="utf-8")
    return _invoke(
        "verify",
        _request("verify", out, tmp_path / "piece", _inputs(), {MODEL_ID: target}, (target,)),
        tmp_path,
        env,
        tag=tag,
    )


def test_verify_passes_an_ordered_x_to_h_timeline(tmp_path: Path) -> None:
    body = json.dumps({"metadata": {"duration": DURATION}, "mouthCues": CUES})
    done, result_path = _verify(tmp_path, body, "-ok")
    assert done.returncode == 0, done.stdout + done.stderr
    verdict = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert verdict["passed"] is True
    assert verdict["metrics"] == {
        "duration_s": DURATION,
        "cues": len(CUES),
        "mouths": 5,
        "ordered": True,
    }
    assert verdict["thresholds"] == {"cues_min": 1.0}
    assert verdict["verifier"] == "rhubarb-lip-sync-1.14.0"


def test_verify_fails_a_letter_outside_the_mouth_alphabet(tmp_path: Path) -> None:
    body = json.dumps({"mouthCues": [{"start": 0.0, "end": 0.1, "value": "Z"}]})
    done, result_path = _verify(tmp_path, body, "-bad-letter")
    assert done.returncode == 0
    verdict = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert verdict["passed"] is False
    assert "Z" in verdict["metrics"]["error"]


def test_verify_fails_a_mouth_value_that_is_not_one_letter(tmp_path: Path) -> None:
    """``""`` and ``"XA"`` are substrings of the alphabet, not mouths in it."""
    for value in ("", "XA", "ABC"):
        cue = {"start": 0.0, "end": 0.1, "value": value}
        done, result_path = _verify(tmp_path, json.dumps({"mouthCues": [cue]}), f"-{value!r}")
        assert done.returncode == 0
        verdict = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
        assert verdict["passed"] is False, value


def test_verify_fails_a_timeline_out_of_order(tmp_path: Path) -> None:
    cues = [{"start": 0.5, "end": 0.6, "value": "B"}, {"start": 0.1, "end": 0.2, "value": "A"}]
    done, result_path = _verify(tmp_path, json.dumps({"mouthCues": cues}), "-unordered")
    assert done.returncode == 0
    verdict = json.loads(result_path.read_text(encoding="utf-8"))["assets"][0]
    assert verdict["passed"] is False
    assert verdict["metrics"]["ordered"] is False


def test_preview_writes_the_generic_mouth_timeline(tmp_path: Path) -> None:
    _result, _printed, _entries, out, env = _run_cycle(tmp_path)
    preview, _ = _call(
        "preview",
        _request(
            "preview", out, out, _inputs(), {MODEL_ID: out / "mouths.json"}, (out / "mouths.json",)
        ),
        tmp_path,
        env,
    )
    assert preview["assets"][0]["file"] == "mouths.json"
    data = json.loads((out / "mouths.json.preview.json").read_text(encoding="utf-8"))
    assert set(data) == {"preview", "kind", "summary", "fields"}
    assert data["preview"] == 1
    assert data["kind"] == "text"
    assert data["fields"]["mouths_used"] == MOUTHS
    assert data["fields"]["recognizer"] == "phonetic"
    assert data["fields"]["cues"] == len(CUES)
    assert len(data["summary"]) <= SUMMARY_MAX
    assert "mouth cues" in data["summary"]


def _doctor(tmp_path: Path, models: dict[str, Path], env: dict[str, str]) -> dict[str, Any]:
    out = tmp_path / "doctor-out"
    out.mkdir(exist_ok=True)
    result, _ = _call(
        "doctor",
        _request("doctor", out, tmp_path / "piece", {}, models),
        tmp_path,
        env,
        tag="-doctor",
    )
    return result


def test_doctor_passes_the_zip_and_the_extracted_binary(tmp_path: Path) -> None:
    stub_dir = _stubs(tmp_path)
    archive = _declared_model(tmp_path)
    log = tmp_path / "probe.jsonl"
    env = _environment(stub_dir, tmp_path / "extract", {"STUB_RHUBARB_LOG": str(log)})
    checks = _doctor(tmp_path, {MODEL_ID: archive}, env)["checks"]
    by_name = {check["name"]: check for check in checks}
    assert by_name["zip"]["ok"] is True
    assert str(archive.stat().st_size) in by_name["zip"]["detail"]
    assert by_name["zip"]["fix"] == ""
    assert by_name["binary"]["ok"] is True
    assert by_name["binary"]["fix"] == ""
    # The doctor's probe runs from the writable out dir too, never the ELF's.
    probe = _read_lines(log)
    assert [entry["argv"] for entry in probe] == [["--help"]]
    assert probe[0]["cwd"] == str(tmp_path / "doctor-out")
    assert probe[0]["elf_res"] is True


def test_doctor_reports_a_missing_zip_with_the_pull_fix(tmp_path: Path) -> None:
    stub_dir = _stubs(tmp_path)
    missing = tmp_path / "home" / "models" / "direct" / MANIFEST["models"][0]["path"]
    checks = _doctor(tmp_path, {MODEL_ID: missing}, _environment(stub_dir, tmp_path / "extract"))[
        "checks"
    ]
    by_name = {check["name"]: check for check in checks}
    assert by_name["zip"]["ok"] is False
    assert by_name["zip"]["fix"] == PULL_FIX
    assert by_name["binary"]["ok"] is False


def test_doctor_reports_a_wrong_size_zip_with_the_pull_fix(tmp_path: Path) -> None:
    stub_dir = _stubs(tmp_path)
    archive = _model(tmp_path)
    archive.write_bytes(archive.read_bytes() + b"truncated")
    checks = _doctor(tmp_path, {MODEL_ID: archive}, _environment(stub_dir, tmp_path / "extract"))[
        "checks"
    ]
    zip_check = next(check for check in checks if check["name"] == "zip")
    assert zip_check["ok"] is False
    assert zip_check["fix"] == PULL_FIX
    assert "manifest says" in zip_check["detail"]


def test_doctor_reports_an_unrunnable_binary_as_machine_cannot(tmp_path: Path) -> None:
    """A verified zip whose ELF this machine cannot start is not pull-fixable."""
    stub_dir = _stubs(tmp_path)
    # Not a script and not an ELF: every kernel refuses to exec it.
    archive = _declared_model(tmp_path, elf_text="\x00\x00\x00\x00 not an executable\n")
    checks = _doctor(tmp_path, {MODEL_ID: archive}, _environment(stub_dir, tmp_path / "extract"))[
        "checks"
    ]
    by_name = {check["name"]: check for check in checks}
    assert by_name["zip"]["ok"] is True
    assert by_name["binary"]["ok"] is False
    assert by_name["binary"]["fix"] == ""
    assert "cannot run on this machine" in by_name["binary"]["detail"]


def test_the_manifest_pins_the_upstream_zip_the_spec_names() -> None:
    model = MANIFEST["models"][0]
    assert model["id"] == MODEL_ID
    assert (
        model["url"]
        == "https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/Rhubarb-Lip-Sync-1.14.0-Linux.zip"
    )
    assert model["sha256"] == "a9a9074862cff47b2d59b8bf399a678a3b0b74f9452ad6ad94cb292913dd8667"
    assert model["bytes"] == DECLARED_BYTES
    assert model["path"] == "rhubarb-lip-sync-1.14.0-linux/Rhubarb-Lip-Sync-1.14.0-Linux.zip"
    assert (model["spdx"], model["commercial_use"], model["requires_acceptance"]) == (
        "MIT",
        True,
        False,
    )
    assert "hf_repo" not in model and "revision" not in model
