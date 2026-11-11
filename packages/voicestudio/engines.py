"""First-use provisioning of the VoiceStudio sidecar engines.

``voxcpm2`` and ``cosyvoice`` live in sidecar virtualenvs under the facet
data dir. They install on first use through VoiceStudio's own loopback
API: ``POST /engines/sidecar/{engine_id}/install``, polled with
``GET /engines/sidecar/{engine_id}/install/status``. ``omnivoice`` is
in-process and never needs this.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

#: The engines that install on first use; ``omnivoice`` is in-process.
SIDECAR_ENGINES = ("voxcpm2", "cosyvoice")
#: Seconds between install-status polls, and the total install budget.
ENGINE_POLL_S = 5.0
ENGINE_INSTALL_TIMEOUT_S = 5400.0
#: What the doctor quotes for an engine the first run will install, in GB.
ENGINE_SIZES_GB = {"voxcpm2": 8, "cosyvoice": 13}
#: The POST answer that means the host cannot serve the engine.
HTTP_CONFLICT = 409


class _HttpError(RuntimeError):
    """One failed POST, with its code and body kept apart for the caller."""

    def __init__(self, code: int, body: str) -> None:
        self.code = code
        self.body = body
        super().__init__(f"answered {code}: {body}")


def _fetch_json(base_url: str, path: str, timeout_s: float) -> Any:
    """One GET decoded as JSON; the caller decides what a failure means."""
    request = urllib.request.Request(f"{base_url}{path}", method="GET")
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(base_url: str, path: str, timeout_s: float) -> Any:
    """One empty POST decoded as JSON; an HTTP error keeps code and body."""
    request = urllib.request.Request(f"{base_url}{path}", data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:500]
        raise _HttpError(exc.code, body) from None


def _install_path(engine: str) -> str:
    """The install endpoint for one sidecar engine."""
    return f"/engines/sidecar/{engine}/install"


def engine_status(base_url: str, engine: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """The install-status body for one sidecar engine, as a dict."""
    payload = _fetch_json(base_url, f"{_install_path(engine)}/status", timeout_s)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{_install_path(engine)}/status answered no JSON object")
    return payload


def _detail(body: str) -> str:
    """The sentence a 409 carries: the JSON detail when there is one."""
    try:
        payload = json.loads(body)
    except ValueError:
        return body
    if isinstance(payload, dict) and payload.get("detail"):
        return str(payload["detail"])
    return body


def _step_label(step: Any) -> str:
    """One step's label: its id and, once recorded, the detail sentence."""
    if isinstance(step, dict):
        name = str(step.get("id", ""))
        detail = str(step.get("detail") or "")
        return f"{name} {detail}".strip()
    return str(step)


def _current_step(job: dict[str, Any]) -> str:
    """The step the install is on: the last one that has started.

    VoiceStudio's job carries every step from the start (``pending``); the
    running one is the last that left that state, so ``steps[-1]`` would name
    the install's final step for the whole job.
    """
    steps = job.get("steps", [])
    if not isinstance(steps, list) or not steps:
        return ""
    started = [step for step in steps if isinstance(step, dict) and step.get("state") != "pending"]
    return _step_label(started[-1] if started else steps[0])


def _ensure_engine(base_url: str, engine: str) -> None:
    """Install ``engine`` on first use; return at once when already installed.

    Status first: when ``installed`` is true there is nothing to do.
    Otherwise POST the install, then poll the status until ``installed`` is
    true. A 409 on POST means this machine cannot serve the engine; a job
    state of ``error`` or ``failed`` carries its error and remediation; a
    poll past the timeout leaves the resumable job for the next run.
    """
    try:
        if bool(engine_status(base_url, engine).get("installed")):
            return
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"{engine}: no VoiceStudio backend at {base_url}: {exc}") from None
    try:
        _post_json(base_url, _install_path(engine), 10.0)
    except _HttpError as exc:
        if exc.code == HTTP_CONFLICT:
            raise RuntimeError(
                f"{engine}: VoiceStudio cannot install it on this machine: {_detail(exc.body)}"
            ) from None
        raise RuntimeError(f"{engine}: install POST answered {exc.code}: {exc.body}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"{engine}: no VoiceStudio backend at {base_url}: {exc}") from None
    started = time.monotonic()
    seen = ""
    while True:
        try:
            payload = engine_status(base_url, engine)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"{engine}: install status failed: {exc}") from None
        if bool(payload.get("installed")):
            return
        job = payload.get("job", {})
        if not isinstance(job, dict):
            job = {}
        state = str(job.get("state", ""))
        line = f"voicestudio: installing {engine}: {state} {_current_step(job)}".rstrip()
        if line != seen:
            print(line, file=sys.stderr, flush=True)
            seen = line
        if state in ("error", "failed"):
            detail = str(job.get("error", "") or state)
            remediation = str(job.get("remediation", "") or "")
            raise RuntimeError(f"{engine}: install {state}: {detail} {remediation}".rstrip())
        if time.monotonic() - started > ENGINE_INSTALL_TIMEOUT_S:
            raise RuntimeError(
                f"{engine}: install not finished after "
                f"{ENGINE_INSTALL_TIMEOUT_S:.0f} s; facet run again resumes it"
            )
        time.sleep(ENGINE_POLL_S)
