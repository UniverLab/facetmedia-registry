# Contributing a package

Adding a tool to facet means adding one package directory to this registry —
never touching the core. CI validates every manifest with the core's own
`facet registry validate`, so a broken manifest never reaches `main`. Work on
a branch, open a pull request, and check your work with
`scripts/try-package.sh` (see the end).

The formats are defined by the core:
[registry](https://github.com/UniverLab/facetmedia/blob/main/docs/registry.md),
[skill](https://github.com/UniverLab/facetmedia/blob/main/docs/skill.md),
[preview](https://github.com/UniverLab/facetmedia/blob/main/docs/preview.md),
[doctor](https://github.com/UniverLab/facetmedia/blob/main/docs/doctor.md),
[run](https://github.com/UniverLab/facetmedia/blob/main/docs/run.md).

## Step by step

1. **Pick the name, the facet and the kinds.** The name is `[a-z][a-z0-9-]*`
   and equals the directory name. The **facet** (`voice`, `audio`, `image`,
   `video`, `cad`, `text`, `presentation`) is the domain; the **kind** of each
   capability is the kind of asset it writes — it picks the preview schema
   and the viewer. Kokoro and Whisper are both `voice`; a speech-to-text
   capability writes `text` assets.
2. **Create `packages/<name>/package.toml`.** The manifest's keys, `[engine]`,
   `[transport]`, the capabilities, `[requirements]`, `[[licenses]]`,
   `[[models]]` — the reference machine is 8 GB VRAM, 19 GB RAM, one heavy job
   at a time, and your `requirements` must say what you need within it.
3. **Create `packages/<name>/pyproject.toml`** with the tool's dependencies
   and `[tool.uv] package = false`, then `uv lock --project packages/<name>`
   and commit the `uv.lock`.
4. **Write `runner.py`** with the four verbs: `run`, `verify`, `preview`,
   `doctor`. Use the `facet_runner_sdk` facet copies into every environment.
5. **Write `skill/SKILL.md`** in the core's format, plus optional
   `skill/references/<ref>.md`.
6. **Add the preview schema and the viewer if the kind is new**: a first
   package writing a kind that has none adds
   `schemas/preview/<kind>.schema.json` and `viewers/<kind>/` in the same
   change. A capability reaches that viewer by naming it —
   `[capabilities.<c>.preview] viewer = "<kind>"` — because the core's
   default viewer is `generic`.
7. **Add the package to `index.toml`** as `[[packages]]` with its `name`.
8. **Run `scripts/try-package.sh <package> <capability> <piece>`** — a real
   `facet run` against your working copy, then `facet preview`, `facet
   doctor` and `facet skill`. It is the manual heavy test: run heavy packages
   alone on the lab machine.
9. **Open the pull request.** CI runs the quality gate, `facet registry
   validate`, `uv lock --check` and `pip-audit` on your package's locked set.

## Entry criteria

These are the conditions a package is merged under; the checklist a
reviewer applies.

### 1. Its facet, declared in the manifest

`facet = "voice"` (or another of `audio`, `image`, `video`, `cad`, `text`,
`presentation`) in `package.toml`. Every capability declares the kind of
asset it writes.

### 2. A declared licence for the tool and for every model

`[[licenses]]` for the tool, `[[models]]` for each model with its `spdx`,
`commercial_use` and `requires_acceptance` keys — an agent must be able to
tell, from the manifest alone, whether it may use the tool and whether a
person must first accept a model's terms. A missing licence is a review
blocker, not a note.

### 3. An output that `verify` can measure

`run` produces assets; `verify` returns a verdict per asset that a machine
can judge — a measurable property of the output, not "it did not crash".
If nothing about the output is measurable, the tool is not ready for the
registry.

### 4. Its own `doctor` verb

At **`quick`** depth (about 2 s, writes nothing) `doctor` checks imports,
files and versions — is the tool chain present and the right version. At
**`full`** depth (up to 30 s) it makes one throwaway output in the directory
facet gives it. Every failing check names its fix: `facet registry validate`
rejects a runner without `@runner.verb("doctor")`. A minimal one:

```python
from facet_runner_sdk import Request, Runner

runner = Runner()


@runner.verb("doctor")
def doctor(req: Request) -> dict:
    checks = [{"name": "imports", "ok": True, "detail": "tool imports", "fix": ""}]
    if req.depth == "full":
        # may run the tool once on a throwaway output in req.out_dir
        ...
    return {"checks": checks}


runner.main()
```

Every check needs `name`, `ok`, `detail` and `fix`, and the list must not be
empty; the full SDK shape is in
[docs/doctor.md](https://github.com/UniverLab/facetmedia/blob/main/docs/doctor.md#writing-a-packages-doctor-with-the-sdk).

### 5. Its skill, `skill/SKILL.md`, in the core's format

Front matter with `name` and `description`; then the four sections `## When
to use`, `## Pieces`, `## Judging the result`, `## Pitfalls`; every
capability id named. An agent learns the package from `facet skill <package>`
— skills are **never installed** into `~/.claude/skills`, `~/.agents` or any
other agent directory. `facet registry validate` rejects a package without a
valid skill.

### 6. It fits the reference machine

The reference machine is 8 GB VRAM, 19 GB RAM, one heavy job at a time. Say
what you need in `[requirements]` (`gpu`, `ram_gb`, `disk_gb`, `exclusive`,
`platforms`, `host_libs`, `host_hint`) — and stay within it. A package that
needs more must say so and wait for a different spec.

### 7. A `preview` that writes the preview file of its kind

The `preview` verb writes `<asset>.preview.json` beside the asset, matching
`schemas/preview/<kind>.schema.json`. A kind that has no schema and no
viewer yet adds both — `schemas/preview/<kind>.schema.json` and
`viewers/<kind>/` — in the same change.

### 8. No text or data inside generated images

Images carry image content only: no watermarks, no captions, no embedded
metadata carrying the input or the result. A human reads the output; an
agent reads the preview file and the record.

### 9. Heavy local tests run alone

Local tests that exercise the real tool are run one package at a time on the
lab machine — never in parallel, never in CI. Tests must not download
anything; CI validates manifests, locks and licences, not model runs.

## What CI runs

`ruff format --check` and `ruff check`, `facet registry validate` (from the
core at `FACETMEDIA_REF`), per package `uv lock --check` and `pip-audit` on
its locked set, and the lab quality gate
([UniverLab/workflows](https://github.com/UniverLab/workflows)). A pull
request must be green before it merges.
