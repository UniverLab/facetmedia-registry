"""The recipes package runner: ordered plans for complete pieces.

Four verbs on the runner SDK (``facet_runner_sdk``, copied into the
environment at pull): ``run`` reads the in-package ``recipes.json`` and
writes ``<recipe>.plan.json`` beside the piece, one ordered step per
capability to run with its handoff files and its verification; ``verify``
re-parses a plan and judges step count, order and completeness; ``preview``
writes the generic viewer's fields; ``doctor`` checks the package files and
the recipes data at quick depth and builds one plan at full depth. The
runner is stdlib only and receives no registry path in its environment, so
it never resolves capability ids against the registry — that check lives in
the repository tests; the runner only checks the data's self-consistency.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from facet_runner_sdk import Request, Runner

runner = Runner()

#: The manifest's ``recipe`` enum, repeated so run never drifts from it.
RECIPES = ("explainer-video", "architecture-render", "voice-material", "tool-demo")
#: The manifest's verify threshold, repeated for the same reason.
STEPS_MIN = 1
#: The files the package must carry after a pull.
PACKAGE_FILES = ("package.toml", "recipes.json", "runner.py", "skill/SKILL.md")


def _package_dir() -> Path:
    """The package directory beside this runner, for the in-package data."""
    return Path(__file__).resolve().parent


def _recipes() -> dict[str, Any]:
    """The parsed recipes data file, beside the runner."""
    return json.loads((_package_dir() / "recipes.json").read_text(encoding="utf-8"))


def _manifest() -> dict[str, Any]:
    """The parsed package.toml, for the tool identity."""
    return tomllib.loads((_package_dir() / "package.toml").read_text(encoding="utf-8"))


def _tool() -> dict[str, str]:
    """The manifest's tool name and version, named for the record."""
    manifest = _manifest()
    return {"name": str(manifest["tool_name"]), "version": str(manifest["version"])}


def _recipe(params: dict[str, Any]) -> str:
    """The planned recipe, refused when the manifest's enum does not name it."""
    name = str(params.get("recipe", ""))
    if name not in _recipes().get("recipes", {}):
        raise ValueError(f"unknown recipe {name!r}: use {', '.join(RECIPES)}")
    return name


def _steps(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """The recipe's steps numbered from one, each carrying its three facts."""
    return [
        {
            "step": index,
            "capability": str(step["capability"]),
            "handoff": str(step["handoff"]),
            "verify": str(step["verify"]),
        }
        for index, step in enumerate(recipe["steps"], start=1)
    ]


def _plan(name: str) -> dict[str, Any]:
    """A recipe as an ordered plan: the recipe, its summary and its steps."""
    recipe = _recipes()["recipes"][name]
    return {"recipe": name, "summary": str(recipe["summary"]), "steps": _steps(recipe)}


def _packages(steps: list[dict[str, Any]]) -> int:
    """How many distinct packages the plan's capabilities belong to."""
    prefixes = {
        str(step.get("capability", "")).split(".", 1)[0] for step in steps if step.get("capability")
    }
    return len(prefixes)


def _asset(name: str, plan: dict[str, Any], path: Path) -> dict[str, Any]:
    """One plan record: a text asset describing an ordered plan."""
    return {
        "file": path.name,
        "name": name,
        "kind": "text",
        "mime": "application/json",
        "properties": {
            "recipe": name,
            "steps": len(plan["steps"]),
            "packages": _packages(plan["steps"]),
        },
        "params": {"recipe": name},
        "seed": None,
        "inputs": [],
    }


@runner.verb("run")
def run(req: Request) -> dict[str, Any]:
    """Write the recipe's ordered plan beside the piece."""
    name = _recipe(dict(req.inputs))
    plan = _plan(name)
    path = req.out_dir / f"{name}.plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"tool": _tool(), "assets": [_asset(name, plan, path)]}


def _plan_metrics(plan: dict[str, Any]) -> dict[str, Any]:
    """What verify reports: the steps, the packages, the order, completeness."""
    steps = plan.get("steps") or []
    numbers = [step.get("step") for step in steps]
    ordered = numbers == list(range(1, len(steps) + 1))
    complete = bool(steps) and all(
        step.get("capability") and step.get("handoff") and step.get("verify") for step in steps
    )
    return {
        "steps": len(steps),
        "packages": _packages(steps),
        "ordered": ordered,
        "complete": complete,
    }


def _verdict(file: str, passed: bool, metrics: dict[str, Any]) -> dict[str, Any]:
    """One verdict; the manifest's threshold stands even on a broken plan."""
    return {
        "file": file,
        "passed": passed,
        "metrics": metrics,
        "thresholds": {"steps_min": STEPS_MIN},
        "verifier": "recipes",
    }


def _verify_asset(path: Path) -> dict[str, Any]:
    """The plan re-parses: enough steps, in order, each carrying its facts."""
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
        metrics = _plan_metrics(plan)
    except (OSError, ValueError) as exc:
        return _verdict(path.name, False, {"error": str(exc), "steps": 0})
    passed = metrics["steps"] >= STEPS_MIN and metrics["ordered"] and metrics["complete"]
    return _verdict(path.name, passed, metrics)


@runner.verb("verify")
def verify(req: Request) -> dict[str, Any]:
    return {"assets": [_verify_asset(path) for path in req.assets]}


def _preview_data(plan: dict[str, Any]) -> dict[str, Any]:
    """The generic preview: the recipe, its step count and its packages."""
    metrics = _plan_metrics(plan)
    fields = {
        "recipe": str(plan.get("recipe", "")),
        "steps": metrics["steps"],
        "packages": metrics["packages"],
    }
    summary = f"{fields['recipe']} \u00b7 {fields['steps']} steps"
    return {"preview": 1, "kind": "text", "summary": summary, "fields": fields}


@runner.verb("preview")
def preview(req: Request) -> dict[str, Any]:
    """One generic preview file per plan, like the viewer expects."""
    entries = []
    for path in req.assets:
        preview_name = f"{path.name}.preview.json"
        plan = json.loads(path.read_text(encoding="utf-8"))
        data = _preview_data(plan)
        (req.out_dir / preview_name).write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        entries.append({"file": path.name, "preview": preview_name, "images": []})
    return {"assets": entries}


def _check(name: str, ok: bool, detail: str, fix: str = "") -> dict[str, Any]:
    """One doctor check; every failure names the pull that fixes it."""
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix}


def _doctor_files() -> dict[str, Any]:
    """The package's files are pulled: manifest, data, runner and skill."""
    package = _package_dir()
    missing = [name for name in PACKAGE_FILES if not (package / name).is_file()]
    if missing:
        return _check("files", False, f"missing: {', '.join(missing)}", "facet pull recipes")
    return _check("files", True, ", ".join(PACKAGE_FILES))


def _doctor_recipes() -> dict[str, Any]:
    """The recipes data parses and names every recipe the manifest's enum does."""
    try:
        recipes = _recipes().get("recipes", {})
    except (OSError, ValueError) as exc:
        return _check("recipes", False, str(exc), "facet pull recipes")
    missing = [name for name in RECIPES if name not in recipes]
    if missing:
        return _check("recipes", False, f"missing: {', '.join(missing)}", "facet pull recipes")
    return _check("recipes", True, f"{len(RECIPES)} recipes")


def _doctor_answers() -> dict[str, Any]:
    """``plan`` answers every enum value with at least one ordered step."""
    try:
        counts = {name: len(_plan(name)["steps"]) for name in RECIPES}
    except (OSError, ValueError, KeyError) as exc:
        return _check("answers", False, str(exc), "facet pull recipes")
    detail = ", ".join(f"{name}: {count}" for name, count in counts.items())
    return _check("answers", True, detail)


def _doctor_plan(req: Request) -> dict[str, Any]:
    """Full depth: one plan written to the out dir, judged and removed."""
    path = req.out_dir / f"{RECIPES[0]}.plan.json"
    try:
        plan = _plan(RECIPES[0])
        path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        metrics = _plan_metrics(json.loads(path.read_text(encoding="utf-8")))
        if not (metrics["ordered"] and metrics["complete"]):
            raise ValueError(f"the plan is not well formed: {metrics!r}")
    except (OSError, ValueError, KeyError) as exc:
        return _check("plan", False, str(exc), "facet pull recipes")
    finally:
        path.unlink(missing_ok=True)
    return _check("plan", True, f"{RECIPES[0]} plan beside the piece")


@runner.verb("doctor")
def doctor(req: Request) -> dict[str, Any]:
    """Quick: the files, the data and every answer. Full: also one plan."""
    checks = [_doctor_files(), _doctor_recipes(), _doctor_answers()]
    if req.depth == "full":
        checks.append(_doctor_plan(req))
    return {"checks": checks}


def _handoff_files(h: str) -> list[tuple[str, bool]]:
    """File names from a handoff string: drop the parenthetical tail, split on +."""
    text = h.split("(", 1)[0]
    files: list[tuple[str, bool]] = []
    for part in text.split("+"):
        name = part.strip()
        if not name:
            continue
        files.append((name, name.endswith("/")))
    return files


def _record(path: Path) -> dict[str, Any] | None:
    """The facet record beside an asset, or None when missing or not valid JSON."""
    record_path = Path(str(path) + ".facet.json")
    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _record_capability(record: dict[str, Any]) -> str | None:
    """The producing capability named by a record, when present."""
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return None
    capability = provenance.get("capability")
    return str(capability) if capability is not None else None


def _record_created(record: dict[str, Any]) -> str | None:
    """The record's UTC created time, comparable as a string."""
    created = record.get("created")
    return str(created) if created is not None else None


def _file_missing(base: Path, name: str, is_dir: bool) -> bool:
    """A named handoff is missing, or a directory handoff is empty."""
    path = base / name
    if not path.exists():
        return True
    if is_dir:
        return not path.is_dir() or not any(path.iterdir())
    return False


def _namers(steps: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Map each handoff file name to the step indices that name it."""
    out: dict[str, list[int]] = {}
    for step in steps:
        index = int(step.get("step", 0))
        for name, _is_dir in _handoff_files(str(step.get("handoff", ""))):
            out.setdefault(name, []).append(index)
    return out


def _cap_by_index(steps: list[dict[str, Any]]) -> dict[int, str]:
    """Map each step index to its capability id."""
    return {int(step.get("step", 0)): str(step.get("capability", "")) for step in steps}


def _allowed_caps(
    namers: dict[str, list[int]], caps: dict[int, str], name: str, index: int
) -> set[str]:
    """Capabilities that may legitimately own a file at this step."""
    return {caps[i] for i in namers.get(name, [index]) if i in caps and i >= index}


def _file_state(
    base: Path,
    name: str,
    is_dir: bool,
    allowed: set[str],
    max_created: str,
) -> tuple[str, str | None]:
    """Report one handoff file and the created time that counts for later steps."""
    if _file_missing(base, name, is_dir):
        return "missing", None
    record = _record(base / name)
    if record is None:
        return "stale", None
    cap = _record_capability(record)
    created = _record_created(record)
    if cap not in allowed or (created is not None and max_created and created < max_created):
        return "stale", created
    return "done", created


def _step_state(file_reports: list[dict[str, str]]) -> str:
    """Reduce per-file states to the step's state: missing beats stale beats done."""
    states = {item["state"] for item in file_reports}
    if "missing" in states:
        return "missing"
    if "stale" in states:
        return "stale"
    return "done"


def _compute_status(plan_path: Path) -> dict[str, Any]:
    """Compute the status report by reading the plan and its folder now."""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    base = plan_path.parent
    steps = plan.get("steps") or []
    namers = _namers(steps)
    caps = _cap_by_index(steps)

    max_created = ""
    report_steps = []
    for step in steps:
        index = int(step.get("step", 0))
        capability = str(step.get("capability", ""))
        file_reports = []
        created_values: list[str] = []
        for name, is_dir in _handoff_files(str(step.get("handoff", ""))):
            allowed = _allowed_caps(namers, caps, name, index)
            state, created = _file_state(base, name, is_dir, allowed, max_created)
            file_reports.append({"file": name, "state": state})
            if created is not None:
                created_values.append(created)
        if created_values:
            max_created = max(max_created, *created_values)
        report_steps.append(
            {
                "index": index,
                "capability": capability,
                "state": _step_state(file_reports),
                "files": file_reports,
            }
        )

    next_step = next((step["index"] for step in report_steps if step["state"] != "done"), None)
    return {"steps": report_steps, "next_step": next_step}


@runner.verb("status")
def status(req: Request) -> dict[str, Any]:
    """Inspect the folder beside a plan and report each step's handoff state."""
    plan_path = req.assets[0]
    report = _compute_status(plan_path)
    out_name = f"{plan_path.stem.split('.')[0]}.status.json"
    out_path = plan_path.parent / out_name
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if _compute_status(plan_path) != report:
        raise ValueError("status report did not match the folder on re-read")
    return report


runner.main()
