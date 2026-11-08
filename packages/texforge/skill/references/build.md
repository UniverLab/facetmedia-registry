# The staged project and the invocations

`packages/texforge/runner.py` ports the shapes below from the texforge
sources: the `[document]`/`[build]` keys are `src/domain/project.rs`, and each
command is `src/commands/{build,check,pdf,preview}.rs`. Nothing here is
summarized: the keys and the command lines are the real ones.

## The staged project.toml

The runner copies the main file and its sibling sources into a scratch build
directory and writes this file itself:

```toml
[document]
title = "tesis"
author = "Ada Lovelace"
template = "general"

[build]
entry = "main.tex"
bibliography = "refs.bib"
```

- `[document]` has exactly `title`, `author` and `template`. `title` is the
  piece's `nombre`, `author` is `autor`, and `template` is always `general`.
- `[build]` has `entry`, the main file's own name as it sits in the stage —
  `main.tex` above, or `hola-mundo.tex` when `principal` names that file.
- `bibliography` is written only when a `.bib` file sits beside the piece; with
  no `.bib` beside it the key is absent and no bibliography is read.
- `texforge init` never runs: it is interactive and would overwrite the file
  the runner just wrote. Do not stage a `project.toml` of your own either.

## The general template

`template = "general"` resolves to the copy embedded in the binary
(`embedded_general()` in `src/templates/mod.rs`, with its own `main.tex`,
`body.tex`, `template.toml` and `references.bib`). The build therefore needs
no network and no template checkout: the machine stays offline, and a build
does not download anything.

## The invocations the runner runs

```bash
texforge build
texforge check
texforge pdf info
texforge pdf check
texforge preview --out <dir>
```

- `texforge build` compiles the staged project from `[build] entry`; the runner
  allows it 900 s. It names the PDF after the sanitized title, so `nombre`
  decides the file: `tesis` gives `tesis.pdf`.
- `texforge check` is the linter, and `verify` gates on it: a broken `\ref`, a
  missing `\cite` or a missing `\input` is an error and fails the run.
- `texforge pdf info` prints the page count as `pages: N`; `verify` passes only
  when `N` is at least 1.
- `texforge pdf check` is the source-to-PDF fidelity probe. It prints
  `WARNINGS (N)` and is recorded as warnings only: it never gates.
- `texforge preview --out <dir>` rasterizes the PDF into `page-NN.png`, one
  image per page in `<dir>`; the runner collects them into `preview/page-NN.png`
  and writes the document preview beside the asset.
