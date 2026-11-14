# texforge — long documents to a verified PDF

Long LaTeX documents — reports, articles and theses — built with the
person-installed [`texforge`](https://github.com/UniverLab/texforge)
binary (**Apache-2.0**). One capability, `texforge.document`, writing the
`document` kind as `<name>.pdf` plus one PNG per page. texforge gives
real pagination, footnotes, an index, a bibliography and mathematics,
which Chrome pagination cannot.

## texforge is person-installed

The `texforge` binary is the machine's own: facet never installs, upgrades
or bundles it. On a machine without it, `doctor` reports
`machine_cannot` with this install line (the manifest's `host_hint`):

```bash
curl -fsSL https://raw.githubusercontent.com/UniverLab/texforge/main/scripts/install.sh | sh
```

or `cargo install texforge`. The runner resolves the binary on `PATH`;
anything older than **0.10.0** fails `doctor` the same way.

## The piece

```toml
[inputs]
main = "tesis/main.tex"
name = "tesis"
author = "Ada Lovelace"
```

`main` is the main `.tex` file, resolved relative to the piece; its
sibling sources beside it are staged with it. `name` is the asset base
name (`[a-z0-9][a-z0-9-]*`), writing `<name>.pdf`. `author` is the
document author.

## The staged project.toml rule

The runner copies the main file's directory into a scratch build
directory and writes the `project.toml` texforge reads — it never runs the
interactive `texforge init`. The keys are texforge's real ones:

```toml
[document]
title = "tesis"
author = "Ada Lovelace"
template = "general"

[build]
entry = "main.tex"
bibliography = "refs.bib"
```

`template = "general"` is embedded in texforge, so the build is offline.
`bibliography` appears only when a `.bib` sits beside the piece. Mermaid,
D2 and Graphviz blocks in the source render inside the document in pure
Rust: no browser, no Node and no external `dot`/`d2` binary.

## Verify: check + pdf info, with pdf check warnings-only

- `texforge check` is the linter: a broken `\ref`, a missing `\cite` or a
  missing input is an error, exits non-zero, and fails the run as
  `runner_failed` naming the check.
- `texforge pdf info` must report a page count above 0.
- `texforge pdf check` is the source-to-PDF fidelity check. It exits zero
  and its warnings are recorded in the verdict (`fidelity_warnings`),
  never gated.

`invalid_input` is facet-side — a bad piece or a schema failure — and
cannot come out of the runner.

## Preview

`preview` runs `texforge preview`, the pure-Rust rasterizer (no poppler,
no new host dependency), into `preview/page-NN.png`, and writes
`<name>.pdf.preview.json` in the core document shape:

```json
{"preview": 1, "kind": "document", "summary": "tesis.pdf · 12 pages", "page_count": 12, "pages": ["preview/page-01.png", "preview/page-02.png"]}
```

The person preview is the `document` viewer: the pages page by page, with the
PDF itself one click away at `/asset/<name>`. A `document` capability uses that
viewer, and no new schema is needed.

## When to use

Long real documents — a thesis, a book chapter, a paper with notes and a
bibliography. Pieces of one visual page — a poster, an infographic, a
slide deck — stay in `deck`.

## Bundled examples

`facet example <capability> --run` copies the capability's example, with
every file it names, into a fresh folder and runs it there:

- `texforge.document` — `examples/hola-mundo.toml`: `facet example texforge.document --run`

Needs a person-installed texforge.
