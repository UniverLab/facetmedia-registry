"""The texforge pull/run/verify/preview/doctor cycle, with no real texforge.

The test stands in for the package environment: it runs ``runner.py`` as a
subprocess against a stub ``facet_runner_sdk`` and a stub ``texforge``
executable placed on ``PATH``. The stub records every invocation (its argv,
its cwd and the ``project.toml`` it found), writes the PDF ``build`` would,
answers ``pdf info``, ``pdf check`` and ``preview``, and can be told to fail
``check`` like a broken ``\\ref`` would. No test touches the real binary.
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
PACKAGE = ROOT / "packages" / "texforge"
MANIFEST = tomllib.loads((PACKAGE / "package.toml").read_text(encoding="utf-8"))
HOST_HINT = MANIFEST["requirements"]["host_hint"]

NAME = "tesis"
AUTHOR = "Ada Lovelace"
PRINCIPAL = "doc/main.tex"
MIN_VERSION = "0.10.0"
STUB_PAGES = 2
STUB_WARNINGS = 2
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

#: The stub binary. ``__PYTHON__`` becomes the running interpreter so the
#: executable needs nothing on PATH, and STUB_* env vars steer its answers.
STUB_TEXFORGE = """#!__PYTHON__
import json
import os
import sys
import tomllib
from pathlib import Path


def project():
    path = Path("project.toml")
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def record():
    log = os.environ.get("STUB_LOG")
    if not log:
        return
    root = Path.cwd()
    entry = {
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "project": project(),
        "files": sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()),
    }
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry) + "\\n")


def build():
    data = project()
    target = Path.cwd() / f"{data['document']['title']}.pdf"
    target.write_bytes(b"%PDF-1.4\\nstub\\n")
    print(f"  ◇ {target}")
    return 0


def fail_check():
    print("ERRORS (1)", file=sys.stderr)
    print("  ERROR [main.tex:12]", file=sys.stderr)
    print("    broken \\\\ref to a missing label", file=sys.stderr)
    return 1


def preview(args):
    out = Path(args[args.index("--out") + 1])
    out.mkdir(parents=True, exist_ok=True)
    pages = int(os.environ.get("STUB_PAGES", "2"))
    for number in range(1, pages + 1):
        (out / f"page-{number:02d}.png").write_bytes(b"\\x89PNG\\r\\n\\x1a\\n")
    return 0


def main():
    record()
    if sys.argv[1:] == ["--version"]:
        print("texforge " + os.environ.get("STUB_VERSION", "0.10.0"))
        return 0
    command, *rest = sys.argv[1:]
    if command == "build":
        return build()
    if command == "check":
        return fail_check() if os.environ.get("STUB_CHECK_FAIL") == "1" else 0
    if command == "pdf" and rest[:1] == ["info"]:
        print("pages: " + os.environ.get("STUB_PAGES", "2"))
        return 0
    if command == "pdf" and rest[:1] == ["check"]:
        if os.environ.get("STUB_PDF_CHECK_FAIL") == "1":
            return 1
        print("WARNINGS (2)")
        print("  WARNING [main.tex]")
        print("    a word missing from the PDF")
        return 0
    if command == "preview":
        return preview(rest)
    print(f"stub texforge: unknown command {command}", file=sys.stderr)
    return 2


raise SystemExit(main())
"""


def _stubs(tmp_path: Path) -> tuple[Path, Path]:
    """The PYTHONPATH stub dir and the PATH bin dir holding the stub binary."""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    (stub_dir / "facet_runner_sdk.py").write_text(STUB_SDK, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    texforge = bin_dir / "texforge"
    texforge.write_text(STUB_TEXFORGE.replace("__PYTHON__", sys.executable), encoding="utf-8")
    texforge.chmod(0o755)
    return stub_dir, bin_dir


def _environment(
    stub_dir: Path, bin_dir: Path, extra: dict[str, str] | None = None
) -> dict[str, str]:
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    if extra:
        env.update(extra)
    return env


def _piece(tmp_path: Path, with_bib: bool = True) -> Path:
    """A piece dir whose ``doc/`` holds the main and its sibling sources."""
    piece_dir = tmp_path / "piece"
    doc = piece_dir / "doc"
    (doc / "figures").mkdir(parents=True)
    (doc / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nHello.\n\\end{document}\n",
        encoding="utf-8",
    )
    if with_bib:
        (doc / "refs.bib").write_text("@article{key, title={A}}\n", encoding="utf-8")
    (doc / "figures" / "fig.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (piece_dir / "tesis.toml").write_text(
        f'[inputs]\nmain = "{PRINCIPAL}"\nname = "{NAME}"\nauthor = "{AUTHOR}"\n',
        encoding="utf-8",
    )
    return piece_dir


def _request(
    verb: str,
    out: Path,
    piece: Path,
    inputs: dict[str, object],
    assets: tuple[Path, ...] = (),
    depth: str = "quick",
) -> dict[str, object]:
    return {
        "protocol": 1,
        "verb": verb,
        "capability": "texforge.document",
        "depth": depth,
        "inputs": dict(inputs),
        "out_dir": str(out),
        "piece_dir": str(piece),
        "assets": [str(path) for path in assets],
    }


def _invoke(
    verb: str,
    request: dict[str, object],
    tmp_path: Path,
    env: dict[str, str],
    tag: str = "",
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
) -> tuple[dict[str, Any], str]:
    done, result_path = _invoke(verb, request, tmp_path, env, tag)
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(result_path.read_text(encoding="utf-8")), done.stdout


def _inputs(**overrides: object) -> dict[str, object]:
    inputs: dict[str, object] = {"main": PRINCIPAL, "name": NAME, "author": AUTHOR}
    inputs.update(overrides)
    return inputs


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _built(tmp_path: Path, env: dict[str, str]) -> tuple[Path, Path, dict[str, Any]]:
    """One successful run; returns its out dir, piece dir and result."""
    piece_dir = _piece(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    result, _printed = _call("run", _request("run", out, piece_dir, _inputs()), tmp_path, env)
    return out, piece_dir, result


def test_run_stages_the_sources_and_writes_the_real_project(tmp_path: Path) -> None:
    stub_dir, bin_dir = _stubs(tmp_path)
    log = tmp_path / "stub.jsonl"
    env = _environment(stub_dir, bin_dir, {"STUB_LOG": str(log)})
    out, _piece_dir, result = _built(tmp_path, env)

    asset = result["assets"][0]
    assert asset["file"] == f"{NAME}.pdf"
    assert asset["name"] == NAME
    assert (asset["kind"], asset["mime"]) == ("document", "application/pdf")
    assert asset["params"] == {"main": PRINCIPAL, "name": NAME, "author": AUTHOR}
    assert (out / f"{NAME}.pdf").is_file()
    assert result["tool"] == {"name": "texforge", "version": "0.1.2"}
    assert not any(path.name.startswith("_stage_") for path in out.iterdir())

    entries = _read_lines(log)
    build = next(entry for entry in entries if entry["argv"][0] == "build")
    staged = build["files"]
    assert "main.tex" in staged
    assert "refs.bib" in staged
    assert "figures/fig.png" in staged
    assert "project.toml" in staged

    project = build["project"]
    assert project["document"] == {"title": NAME, "author": AUTHOR, "template": "general"}
    assert project["build"]["entry"] == "main.tex"
    assert project["build"]["bibliography"] == "refs.bib"
    assert all(entry["argv"][0] != "init" for entry in entries)


def test_run_stages_a_main_at_the_piece_root(tmp_path: Path) -> None:
    """The core stages inside the piece (``.facet-tmp-*``); never copy that dir.

    A main beside the piece file is the common layout. The runner's own
    out dir then sits inside the source tree, and copying it would recurse
    into the stage until the path blows up.
    """
    stub_dir, bin_dir = _stubs(tmp_path)
    piece_dir = tmp_path / "piece"
    piece_dir.mkdir()
    (piece_dir / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nHi.\n\\end{document}\n",
        encoding="utf-8",
    )
    (piece_dir / "refs.bib").write_text("@article{key, title={A}}\n", encoding="utf-8")
    (piece_dir / "tesis.toml").write_text(
        f'[inputs]\nmain = "main.tex"\nname = "{NAME}"\nauthor = "{AUTHOR}"\n',
        encoding="utf-8",
    )
    out = piece_dir / ".facet-tmp-run"
    out.mkdir()
    (out / "request.json").write_text("{}", encoding="utf-8")
    env = _environment(stub_dir, bin_dir)

    inputs = {"main": "main.tex", "name": NAME, "author": AUTHOR}
    result, _ = _call("run", _request("run", out, piece_dir, inputs), tmp_path, env)
    assert result["assets"][0]["file"] == f"{NAME}.pdf"
    assert (out / f"{NAME}.pdf").is_file()
    assert not any(path.name.startswith("_stage_") for path in out.iterdir())


def test_run_omits_bibliography_without_a_bib_file(tmp_path: Path) -> None:
    stub_dir, bin_dir = _stubs(tmp_path)
    piece_dir = _piece(tmp_path, with_bib=False)
    out = tmp_path / "out"
    out.mkdir()
    log = tmp_path / "stub.jsonl"
    env = _environment(stub_dir, bin_dir, {"STUB_LOG": str(log)})
    _call("run", _request("run", out, piece_dir, _inputs()), tmp_path, env)
    build = next(entry for entry in _read_lines(log) if entry["argv"][0] == "build")
    assert "bibliography" not in build["project"]["build"]


def test_a_broken_reference_fails_as_the_stub_check(tmp_path: Path) -> None:
    stub_dir, bin_dir = _stubs(tmp_path)
    env = _environment(stub_dir, bin_dir)
    out, piece_dir, _result = _built(tmp_path, env)
    pdf = out / f"{NAME}.pdf"
    broken = _environment(stub_dir, bin_dir, {"STUB_CHECK_FAIL": "1"})

    done, result_path = _invoke(
        "verify",
        _request("verify", out, piece_dir, _inputs(), (pdf,)),
        tmp_path,
        broken,
        tag="-broken",
    )
    output = done.stdout + done.stderr
    assert done.returncode != 0
    assert "texforge check failed" in output
    assert "broken \\ref" in output
    assert not result_path.exists()


def test_verify_counts_pages_and_records_fidelity_as_warnings_only(tmp_path: Path) -> None:
    stub_dir, bin_dir = _stubs(tmp_path)
    env = _environment(stub_dir, bin_dir, {"STUB_PAGES": "2"})
    out, piece_dir, _result = _built(tmp_path, env)
    pdf = out / f"{NAME}.pdf"

    verdict, _ = _call(
        "verify",
        _request("verify", out, piece_dir, _inputs(), (pdf,)),
        tmp_path,
        env,
        tag="-ok",
    )
    entry = verdict["assets"][0]
    assert entry["file"] == f"{NAME}.pdf"
    assert entry["passed"] is True
    assert entry["metrics"]["page_count"] == STUB_PAGES
    assert entry["metrics"]["fidelity_warnings"] == STUB_WARNINGS
    assert entry["metrics"]["fidelity_exit"] == 0
    assert entry["thresholds"] == {"page_count_min": 1}
    assert entry["verifier"] == "texforge-check-pdf-info"

    warning_only = _environment(stub_dir, bin_dir, {"STUB_PAGES": "2", "STUB_PDF_CHECK_FAIL": "1"})
    warned, _ = _call(
        "verify",
        _request("verify", out, piece_dir, _inputs(), (pdf,)),
        tmp_path,
        warning_only,
        tag="-warn",
    )
    assert warned["assets"][0]["passed"] is True
    assert warned["assets"][0]["metrics"]["fidelity_exit"] == 1


def test_a_pdf_with_no_pages_fails(tmp_path: Path) -> None:
    stub_dir, bin_dir = _stubs(tmp_path)
    env = _environment(stub_dir, bin_dir)
    out, piece_dir, _result = _built(tmp_path, env)
    empty = _environment(stub_dir, bin_dir, {"STUB_PAGES": "0"})
    done, result_path = _invoke(
        "verify",
        _request("verify", out, piece_dir, _inputs(), (out / f"{NAME}.pdf",)),
        tmp_path,
        empty,
        tag="-empty",
    )
    assert done.returncode != 0
    assert "reported no pages" in done.stdout + done.stderr
    assert not result_path.exists()


def test_preview_rasterizes_pages_in_the_core_shape(tmp_path: Path) -> None:
    stub_dir, bin_dir = _stubs(tmp_path)
    env = _environment(stub_dir, bin_dir, {"STUB_PAGES": "2"})
    out, _piece_dir, _result = _built(tmp_path, env)
    _call(
        "preview",
        # The core previews from the asset's own directory, not the piece: the
        # sources are gone from here, so preview must not need them.
        _request("preview", out, out, _inputs(), (out / f"{NAME}.pdf",)),
        tmp_path,
        env,
    )
    assert (out / "preview" / "page-01.png").is_file()
    assert (out / "preview" / "page-02.png").is_file()

    data = json.loads((out / f"{NAME}.pdf.preview.json").read_text(encoding="utf-8"))
    assert set(data) == {"preview", "kind", "summary", "page_count", "pages"}
    assert data["preview"] == 1
    assert data["kind"] == "document"
    assert data["page_count"] == STUB_PAGES
    assert data["pages"] == ["preview/page-01.png", "preview/page-02.png"]
    assert len(data["summary"]) <= SUMMARY_MAX


def _doctor(tmp_path: Path, env: dict[str, str]) -> dict[str, Any]:
    out = tmp_path / "doctor-out"
    out.mkdir(exist_ok=True)
    result, _ = _call(
        "doctor",
        _request("doctor", out, tmp_path, {}, depth="full"),
        tmp_path,
        env,
    )
    return result


def test_the_doctor_passes_the_installed_version(tmp_path: Path) -> None:
    stub_dir, bin_dir = _stubs(tmp_path)
    result = _doctor(tmp_path, _environment(stub_dir, bin_dir))
    check = result["checks"][0]
    assert check["name"] == "texforge"
    assert check["ok"] is True
    assert MIN_VERSION in check["detail"]
    assert check["fix"] == ""


def test_the_doctor_reports_a_missing_binary_with_the_install_line(tmp_path: Path) -> None:
    stub_dir, _bin_dir = _stubs(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    env = {
        **os.environ,
        "PYTHONPATH": str(stub_dir),
        "PATH": str(empty),
    }
    check = _doctor(tmp_path, env)["checks"][0]
    assert check["ok"] is False
    assert check["fix"] == HOST_HINT
    assert "not found on PATH" in check["detail"]


def test_the_doctor_reports_a_binary_older_than_the_minimum(tmp_path: Path) -> None:
    stub_dir, bin_dir = _stubs(tmp_path)
    old = _environment(stub_dir, bin_dir, {"STUB_VERSION": "0.9.0"})
    check = _doctor(tmp_path, old)["checks"][0]
    assert check["ok"] is False
    assert check["fix"] == HOST_HINT
    assert f"older than {MIN_VERSION}" in check["detail"]
