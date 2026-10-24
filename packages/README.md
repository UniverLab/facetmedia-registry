# Packages

A **package** is one directory under `packages/`, named `[a-z][a-z0-9-]*`,
equal to the `name` in its manifest. It is the unit facet installs, runs and
updates. The manifest and the skill formats are defined by the core, not by
this repository: see
[docs/registry.md](https://github.com/UniverLab/facetmedia/blob/main/docs/registry.md)
for the manifest and the layout, and
[docs/skill.md](https://github.com/UniverLab/facetmedia/blob/main/docs/skill.md)
for the skill.

## What a package directory holds

```text
packages/<name>/
├── package.toml        # the manifest: name, version, requires_facet,
│                       # protocol, provider, tool_name, description,
│                       # facet, [engine], [transport], capabilities,
│                       # [requirements], [[licenses]], [[models]]
├── pyproject.toml      # the environment's dependencies, with
│                       # [tool.uv] package = false
├── uv.lock             # the pinned lock, authoritative
├── runner.py           # the package runner
├── README.md           # what the tool is, what the package adds
├── skill/
│   ├── SKILL.md        # the package skill (core's format)
│   └── references/     # optional: <ref>.md files, `facet skill <pkg> --reference <ref>`
└── examples/           # optional: sample inputs a person or agent can try
```

- **`package.toml`** — the manifest. Its `facet` (`voice`, `audio`, `image`,
  `video`, `cad`, `text`, `presentation`) places the package in a domain; its
  `[[capabilities]]` each declare the **kind** of asset they write, which
  picks the preview schema and the viewer, and name the viewer directory with
  `[capabilities.<c>.preview] viewer` — the core's default is `generic`, so a
  kind's viewer is reached by naming it.
- **`pyproject.toml`** — the tool's dependencies for its own environment,
  with `[tool.uv] package = false` so uv treats it as a virtual project.
- **`uv.lock`** — the pinned environment; CI checks it against the
  `pyproject.toml` and audits it.
- **`runner.py`** — one script, four verbs (below).
- **`skill/SKILL.md`** — how an agent learns the package, printed by
  `facet skill <package>`; never installed into agent directories.

## The runner verbs

Every package runner implements all four. `facet registry validate` rejects a
runner that does not register `doctor`; it also rejects a package missing its
`pyproject.toml`, `uv.lock` or entry, missing the `viewers/<viewer>/index.html`
a capability names, or missing a valid skill:

| Verb | What it does |
|------|--------------|
| `run` | do the work: inputs in, one or more assets out, each recorded with kind, mime, properties, params, seed, inputs |
| `verify` | measure the output: one verdict per asset, so a bad run is caught without a human looking |
| `preview` | write `<asset>.preview.json` beside the asset — the preview file of the asset's kind, matching the schema in `schemas/preview/<kind>.schema.json` |
| `doctor` | check the tool on this machine: `quick` (about 2 s, writes nothing) checks imports, files and versions; `full` (up to 30 s) makes one throwaway output; every failing check names its fix |

The runner talks to facet over the runner protocol
([docs/run.md](https://github.com/UniverLab/facetmedia/blob/main/docs/run.md#the-runner-protocol))
through the `facet_runner_sdk` module facet copies into every environment.
