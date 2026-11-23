"""The run verb's pre-flight: backend readiness, then the licence forward.

``run`` resolves the backend URL, waits here until ``GET /model/status``
says ready, then forwards the facet-recorded acceptance to the backend's
own Model Catalogue before any narration. An ``omnivoice`` piece is gated
twice: the core gates on the facet-side acceptance
(``facet license accept omnivoice``) before the runner starts, and the
backend gates on its own catalogue before it narrates. On the facet-managed
server (loopback) the forward POSTs the recorded acceptance once per
catalogue repo and stores the receipt beside the facet record; on a remote
backend it only ever reads. Any refusal is ``license_not_accepted`` naming
the exact repos and the fixing command.

Stdlib only, no facetmedia import: the package environment ships only the
runner SDK, so where the core is importable its ``record_backend`` writes
the receipt, otherwise the identical shape is written by hand.
"""

from __future__ import annotations

import importlib
import json
import os
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Endpoint paths of the VoiceStudio backend this runner talks to.
STATUS_PATH = "/model/status"
#: Seconds a connection gets.
CONNECT_TIMEOUT_S = 10.0
#: Seconds the readiness wait may take in total.
READY_TIMEOUT_S = 600.0
#: Seconds between readiness polls.
READY_POLL_S = 1.0
#: How long ``idle`` must persist before the wait treats it as "nothing
#: preloaded" and proceeds: the lab's 30 s, so a preload that starts right
#: after the backend did (idle → loading → ready) is never raced.
READY_IDLE_GRACE_S = 30.0
#: The backend Model Catalogue's licence routes: every route mounts without prefix.
LICENSE_ACCEPTANCE_PREFIX = "/models/licenses/acceptance/"
LICENSE_DETAILS_PREFIX = "/models/licenses/details/"
LICENSE_ACCEPT_PATH = "/models/licenses/accept"
#: Hosts of the facet-managed server, where check_admin passes without credential.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
#: Backend catalogue states the forward decides on (the pinned response shapes).
LICENSE_ACCEPTED = "accepted"
LICENSE_NOT_ACCEPTED = "not_accepted"
LICENSE_NOT_REQUIRED = "not_required"
LICENSE_TERMS_UPDATED = "terms_updated"
LICENSE_WITHDRAWN = "withdrawn"


def _status(base_url: str) -> dict[str, Any]:
    """GET /model/status; facet starts the backend for each run."""
    try:
        payload = _get_json(base_url, STATUS_PATH)
    except ValueError as exc:
        raise RuntimeError(f"{base_url}{STATUS_PATH} answered no JSON: {exc}") from None
    except OSError as exc:
        raise RuntimeError(
            f"no VoiceStudio backend at {base_url} ({exc}); "
            "facet starts it for each run — see facet doctor voicestudio"
        ) from None
    if not isinstance(payload, dict):
        raise RuntimeError(f"{base_url}{STATUS_PATH} answered no JSON object")
    return payload


def _state(payload: Any) -> str:
    """The backend's reported state, whichever key the response uses."""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("state") or payload.get("status") or "").lower()


def _idle_since(state: str, idle_since: float | None, now: float) -> float | None:
    """When the current idle stretch began; any other state resets it."""
    if state != "idle":
        return None
    return now if idle_since is None else idle_since


def _ready_detail(state: str, payload: dict[str, Any]) -> str:
    """What the readiness wait reports back to the run."""
    return f"{state}: {json.dumps(payload)[:120]}"


def _wait_ready(base_url: str) -> str:
    """Poll GET /model/status until the backend is ready to synthesise.

    ``ready`` returns at once; ``idle`` returns only after it *stays* idle for
    ``READY_IDLE_GRACE_S`` — a backend that is still starting reports idle
    first and loading right after, so proceeding on the first idle would race
    the preload. A report carrying ``error`` (the backend's shape: status
    stays idle/loading and the failure travels in that field) fails naming it;
    /health alone is never trusted, because it answers ok while the background
    import is still running.
    """
    started = time.monotonic()
    idle_since: float | None = None
    while True:
        payload = _status(base_url)
        state = _state(payload)
        now = time.monotonic()
        if state == "ready":
            return _ready_detail(state, payload)
        if state == "error" or payload.get("error"):
            raise RuntimeError(f"backend state error: {json.dumps(payload)[:200]}")
        idle_since = _idle_since(state, idle_since, now)
        if idle_since is not None and now - idle_since >= READY_IDLE_GRACE_S:
            return _ready_detail(state, payload)
        if now - started > READY_TIMEOUT_S:
            raise RuntimeError(f"backend not ready after {READY_TIMEOUT_S:.0f} s (state {state!r})")
        time.sleep(READY_POLL_S)


class _RunnerLicenseError(Exception):
    """``license_not_accepted`` when the core contract is not importable.

    Where facet is installed (tests) the real ``FacetError`` is raised
    instead. Same code, hint, details and exit code either way.
    """

    code = "license_not_accepted"
    exit_code = 4

    def __init__(
        self,
        message: str,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.details = details if details is not None else {}


def _license_error(message: str, hint: str, details: dict[str, Any]) -> Exception:
    """The refusal: the core ``FacetError`` where facet is installed, else the same shape."""
    try:
        module = importlib.import_module("facetmedia.contract")
    except ImportError:
        return _RunnerLicenseError(message, hint, details)
    return module.FacetError("license_not_accepted", message, hint=hint, details=details)


def _is_loopback(base_url: str) -> bool:
    """Whether the backend is the facet-managed server: loopback means managed."""
    return urllib.parse.urlsplit(base_url).hostname in LOOPBACK_HOSTS


def _manifest() -> dict[str, Any]:
    """The parsed package.toml beside this module, for the engine's repos."""
    text = (Path(__file__).parent / "package.toml").read_text(encoding="utf-8")
    loaded = tomllib.loads(text)
    return loaded if isinstance(loaded, dict) else {}


def _license_repos(manifest: dict[str, Any], engine: str) -> tuple[str, ...]:
    """The backend repos the piece's engine gates on: its manifest ``acceptance_repos``."""
    repos: list[str] = []
    for entry in manifest.get("models", []):
        if isinstance(entry, dict) and entry.get("id") == engine:
            claimed = entry.get("acceptance_repos") or []
            repos.extend(str(repo) for repo in claimed)
    return tuple(repos)


def _license_model(manifest: dict[str, Any], repo: str) -> str:
    """The facet model id whose acceptance covers ``repo``: its ``acceptance_repos`` owner."""
    for entry in manifest.get("models", []):
        if isinstance(entry, dict) and repo in (entry.get("acceptance_repos") or []):
            return str(entry.get("id"))
    return ""


def _model_spdx(manifest: dict[str, Any], model_id: str) -> str:
    """The manifest spdx of ``model_id``: a record matches on this exact string."""
    for entry in manifest.get("models", []):
        if isinstance(entry, dict) and entry.get("id") == model_id:
            return str(entry.get("spdx") or "")
    return ""


def _accept_command(model_id: str) -> str:
    """The command that records the facet acceptance the forward keys off."""
    return f"facet license accept {model_id}"


def _licenses_path() -> Path:
    """The acceptance store: ``FACET_HOME``'s state file, as the core lays it out."""
    root = os.environ.get("FACET_HOME") or str(Path.home() / ".facet")
    return Path(root) / "state" / "licenses.json"


def _read_records() -> tuple[Path, list[dict[str, Any]]]:
    """The licenses file and its accepted records; absent or broken means none."""
    path = _licenses_path()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return path, []
    if not isinstance(loaded, dict):
        return path, []
    records = loaded.get("accepted")
    if not isinstance(records, list):
        return path, []
    return path, [record for record in records if isinstance(record, dict)]


def _facet_acceptance(
    records: list[dict[str, Any]], manifest: dict[str, Any], model_id: str
) -> dict[str, Any] | None:
    """The recorded facet acceptance for ``model_id``, matched on the exact spdx."""
    spdx = _model_spdx(manifest, model_id)
    for record in records:
        if record.get("model") == model_id and record.get("spdx") == spdx:
            return record
    return None


def _now_z() -> str:
    """The UTC instant stamp, in the core record's shape."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_records(path: Path, records: list[dict[str, Any]]) -> None:
    """The licenses file, atomically: a temp file in the same directory, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(
        json.dumps({"version": 1, "accepted": records}, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _get_json(base_url: str, path: str) -> Any:
    """One GET decoded as JSON; the caller decides what a failure means."""
    request = urllib.request.Request(f"{base_url}{path}", method="GET")
    with urllib.request.urlopen(request, timeout=CONNECT_TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def _license_get(base_url: str, path: str) -> dict[str, Any]:
    """One catalogue GET decoded as a JSON object; any failure names the route."""
    try:
        payload = _get_json(base_url, path)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"{base_url}{path} failed: {exc}") from None
    if not isinstance(payload, dict):
        raise RuntimeError(f"{base_url}{path} answered no JSON object")
    return payload


def _license_post(base_url: str, body: dict[str, Any]) -> None:
    """One catalogue accept POST; any failure names the route and the answer."""
    request = urllib.request.Request(
        f"{base_url}{LICENSE_ACCEPT_PATH}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=CONNECT_TIMEOUT_S) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(
            f"{base_url}{LICENSE_ACCEPT_PATH} answered {exc.code}: {detail}"
        ) from None
    except OSError as exc:
        raise RuntimeError(f"no VoiceStudio backend at {base_url}: {exc}") from None


def _acceptance_status(payload: dict[str, Any]) -> tuple[bool, str, str]:
    """``(accepted, state, fingerprint)`` from a catalogue status object."""
    if not isinstance(payload, dict):
        raise RuntimeError("the catalogue acceptance is no JSON object")
    state = payload.get("state")
    fingerprint = payload.get("fingerprint")
    if not isinstance(state, str) or not state:
        raise RuntimeError("the catalogue acceptance has no state")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise RuntimeError("the catalogue acceptance has no fingerprint")
    return payload.get("accepted") is True, state, fingerprint


def _missing_message(manifest: dict[str, Any], missing: list[str]) -> str:
    """Every unaccepted repo id with its mapped accept command, never a bare pointer."""
    parts = ", ".join(
        f"{repo} ({_accept_command(_license_model(manifest, repo))})" for repo in missing
    )
    return f"backend catalogue acceptance missing for {parts}"


def _missing_hint(manifest: dict[str, Any], missing: list[str]) -> str:
    """The mapped accept commands, deduplicated in first-seen order."""
    commands: list[str] = []
    for repo in missing:
        command = _accept_command(_license_model(manifest, repo))
        if command not in commands:
            commands.append(command)
    return "; ".join(commands)


def _terms_message(manifest: dict[str, Any], repo: str, detail: str) -> str:
    """The terms-changed guidance: the repo, what changed, and the re-accept command."""
    model = _license_model(manifest, repo)
    return (
        f"backend catalogue terms changed for {repo} ({detail}); "
        f"re-accept with {_accept_command(model)}"
    )


def _store_receipt(
    model_id: str,
    repo_id: str,
    fingerprint: str,
    path: Path,
    records: list[dict[str, Any]],
    record: dict[str, Any],
) -> None:
    """Persist the catalogue receipt through the core writer, or the same shape by hand.

    The package environment ships only the runner SDK, never facetmedia: where
    the core is importable its ``record_backend`` writes the receipt; otherwise
    the runner writes the identical shape itself (model+spdx match, a backend
    map of repo ids to fingerprint receipts).
    """
    try:
        module = importlib.import_module("facetmedia.licenses")
    except ImportError:
        module = None
    writer = getattr(module, "record_backend", None) if module is not None else None
    if callable(writer):
        writer(model_id, repo_id, fingerprint)
        return
    backend = record.get("backend")
    if not isinstance(backend, dict):
        backend = {}
        record["backend"] = backend
    backend[repo_id] = {"fingerprint": fingerprint, "at": _now_z()}
    _write_records(path, records)


def _confirm_receipt(
    manifest: dict[str, Any], records: list[dict[str, Any]], repo: str, fingerprint: str
) -> None:
    """The stored receipt still matches the catalogue's current fingerprint."""
    model = _license_model(manifest, repo)
    record = _facet_acceptance(records, manifest, model)
    stored: Any = None
    if isinstance(record, dict):
        backend = record.get("backend")
        if isinstance(backend, dict):
            stored = backend.get(repo)
    current = stored.get("fingerprint") if isinstance(stored, dict) else None
    if current != fingerprint:
        detail = "fingerprint mismatch" if stored is not None else "no stored receipt"
        raise _license_error(
            _terms_message(manifest, repo, detail),
            _accept_command(model),
            {"repos": [repo]},
        )


def _forward_accept(
    base_url: str,
    manifest: dict[str, Any],
    path: Path,
    records: list[dict[str, Any]],
    repo: str,
) -> None:
    """POST the recorded facet acceptance to the managed catalogue and store its receipt."""
    details = _license_get(base_url, f"{LICENSE_DETAILS_PREFIX}{repo}")
    nested = details.get("acceptance")
    if not isinstance(nested, dict):
        raise RuntimeError(f"{base_url}{LICENSE_DETAILS_PREFIX}{repo} nests no acceptance object")
    fingerprint = _acceptance_status(nested)[2]
    model = _license_model(manifest, repo)
    record = _facet_acceptance(records, manifest, model)
    if record is None:  # the fail-fast above guarantees this; never silently POST
        raise _license_error(
            _missing_message(manifest, [repo]),
            _missing_hint(manifest, [repo]),
            {"repos": [repo]},
        )
    _license_post(base_url, {"repo_id": repo, "fingerprint": fingerprint, "accepted": True})
    _store_receipt(model, repo, fingerprint, path, records, record)


def _forward_loopback_repo(
    base_url: str,
    manifest: dict[str, Any],
    path: Path,
    records: list[dict[str, Any]],
    repo: str,
) -> None:
    """One repo on the managed server: forward a recorded acceptance, or fail closed."""
    accepted, state, fingerprint = _acceptance_status(
        _license_get(base_url, f"{LICENSE_ACCEPTANCE_PREFIX}{repo}")
    )
    if state == LICENSE_NOT_ACCEPTED:
        _forward_accept(base_url, manifest, path, records, repo)
    elif state == LICENSE_ACCEPTED and accepted:
        _confirm_receipt(manifest, records, repo, fingerprint)
    elif state == LICENSE_NOT_REQUIRED:
        return
    else:
        raise _license_error(
            _terms_message(manifest, repo, state),
            _accept_command(_license_model(manifest, repo)),
            {"repos": [repo]},
        )


def _check_remote_repos(base_url: str, repos: tuple[str, ...]) -> None:
    """Read-only catalogue check on a remote backend: every repo must report accepted."""
    refused: list[str] = []
    for repo in repos:
        accepted = _acceptance_status(_license_get(base_url, f"{LICENSE_ACCEPTANCE_PREFIX}{repo}"))[
            0
        ]
        if not accepted:
            refused.append(repo)
    if refused:
        names = ", ".join(refused)
        raise _license_error(
            f"backend catalogue acceptance missing for {names}; "
            "accept each in that backend's own catalogue",
            f"accept each in that backend's own catalogue ({base_url})",
            {"repos": refused},
        )


def forward_licenses(base_url: str, engine: str) -> None:
    """Forward facet-recorded acceptance to the backend catalogue, when the engine gates any repo.

    On the facet-managed server (loopback) a recorded facet acceptance is POSTed
    to the catalogue once per repo and its receipt stored; a remote backend is
    only ever read. Any refusal is ``license_not_accepted`` naming the repos.
    """
    manifest = _manifest()
    repos = _license_repos(manifest, engine)
    if not repos:
        return
    path, records = _read_records()
    missing = [
        repo
        for repo in repos
        if _facet_acceptance(records, manifest, _license_model(manifest, repo)) is None
    ]
    if missing:
        raise _license_error(
            _missing_message(manifest, missing),
            _missing_hint(manifest, missing),
            {"repos": list(missing)},
        )
    if _is_loopback(base_url):
        for repo in repos:
            _forward_loopback_repo(base_url, manifest, path, records, repo)
    else:
        _check_remote_repos(base_url, repos)
