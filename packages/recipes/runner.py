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


runner.main()
