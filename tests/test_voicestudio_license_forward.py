"""The licence forward: facet acceptance reaches the backend Model Catalogue.

A scripted catalogue (threaded, in-process) pins the response shapes: the
acceptance GET returns a status object ``{accepted, state, fingerprint}``
and details nests the same object under ``acceptance``. Against it the
forward proves: recorded acceptance POSTs once per repo with its receipt
written, a missing facet acceptance fails fast naming every repo with its
mapped accept command, terms-changed and withdrawn paths never POST and fail
with re-accept guidance, a remote backend passes read-only with zero POSTs
and fails naming the unaccepted repos. The core receipt writer is exercised
through the refreshed facet install; where the core predates it those probes
skip instead of failing.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "voicestudio"
REPO_ONE = "k2-fsa/OmniVoice"
REPO_TWO = "eustlb/higgs-audio-v2-tokenizer"
REPOS = (REPO_ONE, REPO_TWO)
#: Exit code of the ``license_not_accepted`` refusal.
LICENSE_EXIT = 4


def _load_preflight() -> Any:
    """The preflight module by path: stdlib only, no runner SDK needed."""
    spec = importlib.util.spec_from_file_location("voicestudio_preflight", PACKAGE / "preflight.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREFLIGHT = _load_preflight()


def _status(accepted: bool, state: str, fingerprint: str = "fp") -> dict[str, Any]:
    """One pinned catalogue status object."""
    return {"accepted": accepted, "state": state, "fingerprint": fingerprint}


class _Catalogue:
    """The scripted backend: per-repo statuses, recorded GETs and POST bodies."""

    def __init__(self, acceptance: dict[str, dict[str, Any]]) -> None:
        self.acceptance = dict(acceptance)
        self.details = dict(acceptance)
        self.gets: list[str] = []
        self.posts: list[dict[str, Any]] = []


def _serve(catalogue: _Catalogue, host: str) -> ThreadingHTTPServer:
    """The stub catalogue on an ephemeral port of ``host``."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            return None

        def _send(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            catalogue.gets.append(self.path)
            if self.path.startswith("/models/licenses/acceptance/"):
                repo = self.path[len("/models/licenses/acceptance/") :]
                self._send(catalogue.acceptance[repo])
                return
            if self.path.startswith("/models/licenses/details/"):
                repo = self.path[len("/models/licenses/details/") :]
                self._send({"acceptance": catalogue.details[repo]})
                return
            self.send_error(404)

        def do_POST(self) -> None:
            if self.path != "/models/licenses/accept":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            catalogue.posts.append(json.loads(self.rfile.read(length).decode("utf-8")))
            self._send({})

    server = ThreadingHTTPServer((host, 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _url(server: ThreadingHTTPServer, host: str) -> str:
    """The base URL of a stub catalogue server."""
    return f"http://{host}:{server.server_address[1]}"


def _write_home(
    home: Path,
    spdx: str = "CC-BY-NC",
    backend: dict[str, Any] | None = None,
) -> Path:
    """A scratch FACET_HOME with one omnivoice acceptance record."""
    record: dict[str, Any] = {
        "model": "omnivoice",
        "spdx": spdx,
        "terms_url": "https://huggingface.co/k2-fsa/OmniVoice",
        "commercial_use": False,
        "by": "tester",
        "at": "2026-01-01T00:00:00Z",
        "method": "flag",
    }
    if backend is not None:
        record["backend"] = backend
    path = home / "state" / "licenses.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "accepted": [record]}), encoding="utf-8")
    return path


def _read_home(home: Path) -> dict[str, Any]:
    """The scratch licenses file decoded."""
    return json.loads((home / "state" / "licenses.json").read_text(encoding="utf-8"))


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A scratch FACET_HOME with the registry checkout as the active registry."""
    facet_home = tmp_path / "facet-home"
    monkeypatch.setenv("FACET_HOME", str(facet_home))
    monkeypatch.setenv("FACET_REGISTRY", str(ROOT))
    return facet_home


def _code(exc: BaseException) -> str:
    """The licence code of a refusal, real FacetError or runner twin alike."""
    return str(getattr(exc, "code", ""))


def _exit_code(exc: BaseException) -> int:
    """The exit code of a refusal, real FacetError or runner twin alike."""
    return int(getattr(exc, "exit_code", -1))


def test_no_gated_engine_is_a_noop(home: Path) -> None:
    """An ungated engine never touches the network: closed port, no error."""
    PREFLIGHT.forward_licenses("http://127.0.0.1:1", "voxcpm2")
    PREFLIGHT.forward_licenses("http://127.0.0.1:1", "cosyvoice")


def test_tokenizer_model_gates_nothing() -> None:
    """The tokenizer entry carries no acceptance_repos of its own."""
    manifest = PREFLIGHT._manifest()
    assert PREFLIGHT._license_repos(manifest, "omnivoice") == REPOS
    assert PREFLIGHT._license_repos(manifest, "higgs-audio-v2-tokenizer") == ()
    assert PREFLIGHT._license_repos(manifest, "voxcpm2") == ()
    assert PREFLIGHT._license_model(manifest, REPO_ONE) == "omnivoice"
    assert PREFLIGHT._license_model(manifest, REPO_TWO) == "omnivoice"


@pytest.mark.parametrize(
    ("base_url", "loopback"),
    [
        ("http://127.0.0.1:3900", True),
        ("http://localhost:9", True),
        ("http://[::1]:9", True),
        ("http://127.0.0.2:9", False),
        ("http://192.168.1.5:1", False),
        ("https://voice.example.com", False),
        ("127.0.0.1:3900", False),
    ],
)
def test_loopback_is_literal(base_url: str, loopback: bool) -> None:
    """Only the three listed hostnames mean the facet-managed server."""
    assert PREFLIGHT._is_loopback(base_url) is loopback


def _needs_core_writer() -> Any:
    """The core receipt writer, skipped when the installed core predates it."""
    module = importlib.import_module("facetmedia.licenses")
    if not hasattr(module, "record_backend"):
        pytest.skip("installed facet predates backend receipts")
    return module


def test_forward_posts_once_per_repo_and_writes_receipts(home: Path) -> None:
    """Recorded acceptance POSTs per repo with the current fingerprint, then receipts land."""
    licenses_module = _needs_core_writer()
    _write_home(home)
    catalogue = _Catalogue(
        {
            REPO_ONE: _status(False, "not_accepted", "fp-one"),
            REPO_TWO: _status(False, "not_accepted", "fp-two"),
        }
    )
    server = _serve(catalogue, "127.0.0.1")
    try:
        calls: list[tuple[str, str, str]] = []
        real = licenses_module.record_backend

        def spy(model_id: str, repo_id: str, fingerprint: str) -> Any:
            calls.append((model_id, repo_id, fingerprint))
            return real(model_id, repo_id, fingerprint)

        licenses_module.record_backend = spy  # type: ignore[method-assign]
        try:
            PREFLIGHT.forward_licenses(_url(server, "127.0.0.1"), "omnivoice")
        finally:
            licenses_module.record_backend = real  # type: ignore[method-assign]
    finally:
        server.shutdown()
    assert catalogue.posts == [
        {"repo_id": REPO_ONE, "fingerprint": "fp-one", "accepted": True},
        {"repo_id": REPO_TWO, "fingerprint": "fp-two", "accepted": True},
    ]
    assert calls == [("omnivoice", REPO_ONE, "fp-one"), ("omnivoice", REPO_TWO, "fp-two")]
    stored = _read_home(home)["accepted"][0]["backend"]
    assert stored[REPO_ONE]["fingerprint"] == "fp-one"
    assert stored[REPO_TWO]["fingerprint"] == "fp-two"
    assert stored[REPO_ONE]["at"].endswith("Z")
    detail_paths = [path for path in catalogue.gets if "/details/" in path]
    assert len(detail_paths) == len(REPOS)


def test_already_forwarded_record_passes_without_posts(home: Path) -> None:
    """Stored receipts matching the catalogue fingerprints are a silent pass."""
    _write_home(
        home,
        backend={
            REPO_ONE: {"fingerprint": "fp-one", "at": "2026-01-02T00:00:00Z"},
            REPO_TWO: {"fingerprint": "fp-two", "at": "2026-01-02T00:00:00Z"},
        },
    )
    catalogue = _Catalogue(
        {
            REPO_ONE: _status(True, "accepted", "fp-one"),
            REPO_TWO: _status(True, "accepted", "fp-two"),
        }
    )
    server = _serve(catalogue, "127.0.0.1")
    try:
        PREFLIGHT.forward_licenses(_url(server, "127.0.0.1"), "omnivoice")
    finally:
        server.shutdown()
    assert catalogue.posts == []
    assert len(catalogue.gets) == len(REPOS)


def test_fail_fast_names_every_repo_with_mapped_commands(home: Path) -> None:
    """No facet acceptance: one refusal naming every repo id with its accept command."""
    catalogue = _Catalogue(
        {
            REPO_ONE: _status(False, "not_accepted"),
            REPO_TWO: _status(False, "not_accepted"),
        }
    )
    server = _serve(catalogue, "127.0.0.1")
    try:
        with pytest.raises(Exception) as caught:
            PREFLIGHT.forward_licenses(_url(server, "127.0.0.1"), "omnivoice")
    finally:
        server.shutdown()
    exc = caught.value
    assert _code(exc) == "license_not_accepted"
    assert _exit_code(exc) == LICENSE_EXIT
    message = str(exc)
    assert REPO_ONE in message and REPO_TWO in message
    assert message.count("facet license accept omnivoice") == len(REPOS)
    assert "Model Catalogue" not in message
    assert getattr(exc, "hint", "") == "facet license accept omnivoice"
    assert getattr(exc, "details", {}).get("repos") == [REPO_ONE, REPO_TWO]
    assert catalogue.gets == [] and catalogue.posts == []


def test_fail_fast_on_spdx_mismatch(home: Path) -> None:
    """A record under a stale spdx is no acceptance: same fail-fast, no network."""
    _write_home(home, spdx="CC-BY-NC-4.0")
    with pytest.raises(Exception) as caught:
        PREFLIGHT.forward_licenses("http://127.0.0.1:1", "omnivoice")
    assert _code(caught.value) == "license_not_accepted"
    assert REPO_ONE in str(caught.value)


def test_terms_updated_fails_with_reaccept_guidance(home: Path) -> None:
    """New catalogue terms never POST: the refusal tells the person to re-accept."""
    _write_home(home)
    catalogue = _Catalogue(
        {
            REPO_ONE: _status(True, "terms_updated", "fp-new"),
            REPO_TWO: _status(False, "not_accepted", "fp-new"),
        }
    )
    server = _serve(catalogue, "127.0.0.1")
    try:
        with pytest.raises(Exception) as caught:
            PREFLIGHT.forward_licenses(_url(server, "127.0.0.1"), "omnivoice")
    finally:
        server.shutdown()
    exc = caught.value
    assert _code(exc) == "license_not_accepted"
    assert _exit_code(exc) == LICENSE_EXIT
    assert REPO_ONE in str(exc) and "re-accept" in str(exc)
    assert "facet license accept omnivoice" in str(exc)
    assert catalogue.posts == []


def test_withdrawn_is_never_overridden(home: Path) -> None:
    """A withdrawn backend record fails even with a matching older receipt."""
    _write_home(
        home,
        backend={REPO_ONE: {"fingerprint": "fp-one", "at": "2026-01-02T00:00:00Z"}},
    )
    catalogue = _Catalogue({REPO_ONE: _status(False, "withdrawn", "fp-one")})
    server = _serve(catalogue, "127.0.0.1")
    try:
        with pytest.raises(Exception) as caught:
            PREFLIGHT.forward_licenses(_url(server, "127.0.0.1"), "omnivoice")
    finally:
        server.shutdown()
    assert _code(caught.value) == "license_not_accepted"
    assert "withdrawn" in str(caught.value)
    assert catalogue.posts == []


def test_fingerprint_mismatch_fails(home: Path) -> None:
    """An accepted backend with a stale stored receipt fails the same way."""
    _write_home(
        home,
        backend={REPO_ONE: {"fingerprint": "fp-old", "at": "2026-01-02T00:00:00Z"}},
    )
    catalogue = _Catalogue({REPO_ONE: _status(True, "accepted", "fp-new")})
    server = _serve(catalogue, "127.0.0.1")
    try:
        with pytest.raises(Exception) as caught:
            PREFLIGHT.forward_licenses(_url(server, "127.0.0.1"), "omnivoice")
    finally:
        server.shutdown()
    assert _code(caught.value) == "license_not_accepted"
    assert "fingerprint mismatch" in str(caught.value)
    assert catalogue.posts == []


def test_missing_receipt_on_accepted_backend_fails(home: Path) -> None:
    """An accepted backend with no stored receipt fails outside the forward case."""
    _write_home(home)
    catalogue = _Catalogue({REPO_ONE: _status(True, "accepted", "fp-one")})
    server = _serve(catalogue, "127.0.0.1")
    try:
        with pytest.raises(Exception) as caught:
            PREFLIGHT.forward_licenses(_url(server, "127.0.0.1"), "omnivoice")
    finally:
        server.shutdown()
    assert _code(caught.value) == "license_not_accepted"
    assert "no stored receipt" in str(caught.value)
    assert catalogue.posts == []


def test_remote_accepted_passes_with_zero_posts(home: Path) -> None:
    """A remote backend is read-only: accepted everywhere passes, nothing POSTs."""
    _write_home(home)
    catalogue = _Catalogue(
        {
            REPO_ONE: _status(True, "accepted", "fp-one"),
            REPO_TWO: _status(True, "accepted", "fp-two"),
        }
    )
    server = _serve(catalogue, "127.0.0.2")
    try:
        PREFLIGHT.forward_licenses(_url(server, "127.0.0.2"), "omnivoice")
    finally:
        server.shutdown()
    assert catalogue.posts == []
    assert sorted(catalogue.gets) == sorted(
        [
            f"/models/licenses/acceptance/{REPO_ONE}",
            f"/models/licenses/acceptance/{REPO_TWO}",
        ]
    )


def test_remote_unaccepted_fails_naming_repos(home: Path) -> None:
    """A remote backend that gates a repo fails naming it and its own catalogue."""
    _write_home(home)
    catalogue = _Catalogue(
        {
            REPO_ONE: _status(True, "accepted", "fp-one"),
            REPO_TWO: _status(False, "not_accepted", "fp-two"),
        }
    )
    server = _serve(catalogue, "127.0.0.2")
    try:
        with pytest.raises(Exception) as caught:
            PREFLIGHT.forward_licenses(_url(server, "127.0.0.2"), "omnivoice")
    finally:
        server.shutdown()
    exc = caught.value
    assert _code(exc) == "license_not_accepted"
    assert _exit_code(exc) == LICENSE_EXIT
    assert REPO_TWO in str(exc) and REPO_ONE not in str(exc)
    assert "that backend's own catalogue" in str(exc)
    assert catalogue.posts == []


def test_pinned_response_shapes() -> None:
    """The status object carries accepted, state and fingerprint; details nests it."""
    accepted, state, fingerprint = PREFLIGHT._acceptance_status(_status(True, "accepted", "fp"))
    assert (accepted, state, fingerprint) == (True, "accepted", "fp")
    assert PREFLIGHT._acceptance_status(_status(False, "not_accepted", "fp"))[0] is False
    for bad in (
        {"accepted": True, "state": "accepted"},
        {"accepted": True, "fingerprint": "fp"},
        {"accepted": True, "state": "", "fingerprint": "fp"},
        {"accepted": True, "state": "accepted", "fingerprint": ""},
    ):
        with pytest.raises(RuntimeError):
            PREFLIGHT._acceptance_status(bad)
    with pytest.raises(RuntimeError):
        PREFLIGHT._acceptance_status(["accepted"])  # type: ignore[arg-type]


def test_fallback_writer_matches_core_shape(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an importable core the runner writes the identical receipt shape."""
    _write_home(home)
    monkeypatch.setitem(sys.modules, "facetmedia.licenses", None)
    catalogue = _Catalogue(
        {
            REPO_ONE: _status(False, "not_accepted", "fp-one"),
            REPO_TWO: _status(False, "not_accepted", "fp-two"),
        }
    )
    server = _serve(catalogue, "127.0.0.1")
    try:
        PREFLIGHT.forward_licenses(_url(server, "127.0.0.1"), "omnivoice")
    finally:
        server.shutdown()
    stored = _read_home(home)["accepted"][0]["backend"]
    assert set(stored) == {REPO_ONE, REPO_TWO}
    assert stored[REPO_ONE]["fingerprint"] == "fp-one"
    assert stored[REPO_TWO]["fingerprint"] == "fp-two"


def test_refusal_without_core_carries_code(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an importable core the refusal still reads license_not_accepted, exit 4."""
    monkeypatch.setitem(sys.modules, "facetmedia.contract", None)
    monkeypatch.setitem(sys.modules, "facetmedia.licenses", None)
    with pytest.raises(Exception) as caught:
        PREFLIGHT.forward_licenses("http://127.0.0.1:1", "omnivoice")
    exc = caught.value
    assert _code(exc) == "license_not_accepted"
    assert _exit_code(exc) == LICENSE_EXIT
    assert "facet license accept omnivoice" in str(exc)


def test_run_calls_forward_between_ready_and_narration() -> None:
    """The pre-flight sits after the readiness wait and before engine ensure."""
    source = (PACKAGE / "runner.py").read_text(encoding="utf-8")
    run_body = source[source.index("def run(") :]
    ready = run_body.index("preflight._wait_ready(base_url)")
    forward = run_body.index("preflight.forward_licenses(base_url")
    ensure = run_body.index("_engines()._ensure_engine")
    assert ready < forward < ensure
