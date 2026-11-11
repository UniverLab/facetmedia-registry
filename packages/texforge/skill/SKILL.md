---
name: texforge
description: Long LaTeX documents built to a verified PDF with real pagination, footnotes, indexes, bibliography and math through the person-installed texforge binary.
---
# texforge

Build a long, real document — a report, an article or a thesis — from
LaTeX with the person-installed `texforge` binary. One capability,
`texforge.document`, writing the `document` kind as `<name>.pdf` plus
one PNG per page.

## When to use

- `texforge.document` for a document that needs real pagination: many
  pages, footnotes, an index, a bibliography, cross-references and
  mathematics. Chrome pagination cannot give those.
- Pieces of one visual page — a poster, an infographic, a slide — stay in
  `deck`; texforge is for documents that run to pages.
- The machine must have `texforge` 0.10.0 or newer on `PATH`. facet never
  installs or bundles it; `doctor` fails with the install line when it is
  missing or older.

## Pieces

One document per piece: the main `.tex` file in `main`, resolved
relative to the piece, with its sibling sources beside it; a `name`
matching `[a-z0-9][a-z0-9-]*`; and `author` for the document author.

```toml
[inputs]
main = "tesis/main.tex"
name = "tesis"
author = "Ada Lovelace"
```

The runner copies the main file and its sibling sources into a scratch
build directory and writes the `project.toml` itself (`[document] title =
name, author = author, template = "general"`, `[build] entry` = the main
file's name, plus `bibliography` when a `.bib` sits beside the piece). It
never runs the interactive `texforge init`. The real keys and the exact
invocations are in [references/build.md](references/build.md). A runnable
piece is `examples/hola-mundo.toml`, with `hola-mundo.tex` beside it. Mermaid,
D2 and Graphviz blocks in the source render inside the document, in pure Rust,
with no browser or external diagram binary.

## Judging the result

`verify` runs the linter `texforge check` — a broken `\ref`, a missing
`\cite` or a missing input is an error and fails the run — then
`texforge pdf info` and passes only when the page count is above 0. The
source-to-PDF fidelity check `texforge pdf check` is recorded as warnings
only and never gates. `preview` rasterizes the PDF with `texforge
preview` into `preview/page-NN.png` and writes the document preview
(`page_count`, `pages`), which the person reads as the PDF in a browser
and an agent reads page by page.

## Pitfalls

- `texforge` is person-installed: a pull only creates the environment.
  Never expect facet to install, upgrade or bundle the binary.
- A failed build is a runner failure carrying texforge's log tail; read
  the first error, not the last line.
- Do not stage a `project.toml` of your own and do not run `texforge
  init`: the runner writes the real `[document]` and `[build]` keys.
