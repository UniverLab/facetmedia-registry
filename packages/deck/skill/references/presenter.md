# Presenter file shapes

`deck.presenter` writes two files beside the deck: `<base>.present.html` and
`<base>.notes.md`. The speaker view itself is
`packages/deck/presenter/runner.css` and `runner.js`.

## `<base>.notes.md`

One speaker note per slide, in `pagina` order, separated by a line holding only
`---`. The section count must equal the `notas` count; `verify` enforces count
and order.

```markdown
Bienvenida: qué vamos a ver y por qué importa.

---
El resultado principal; la cifra sale del DATA y el pie lleva su fuente.

---
Cierre y preguntas.
```

- No front matter, no headings required: each section is the raw note text.
- The runner trims each section and turns the list into `window.__PZ_NOTES__`
  in the built file.

## `<base>.present.html`

The deck's own HTML, with every local resource inlined and the presenter
injected before `</body>`:

```html
…deck markup…
<style>/* presenter/runner.css */</style>
<script>window.__PZ_NOTES__=["nota 1","nota 2","nota 3"];</script>
<script>/* presenter/runner.js */</script>
</body>
```

- **Inlined resources.** Every `src="…"` and `url(…)` that names a local
  image (`png`, `jpg`, `jpeg`, `svg`, `gif`, `webp`) is replaced with a
  `data:` URI. Remote URLs, `data:` URIs and non-image refs are left alone.
  A local image ref that cannot be found stops the run with `runner_failed`.
- **Videos are not inlined.** A `<video>`/`<source>` ref that is not a `data:`
  URI prints an `aviso` and the file must travel beside the deck; it never
  fails the run.
- **`window.__PZ_NOTES__`** is the notes array, written before the runner
  script so the runner reads it on load. `<` inside the array is escaped as
  `\u003c` so a note cannot close the script tag.
- **Slides** are `<section class="slide">` elements of the deck's own size; the
  presenter adds the grid, the next-slide preview and the notes pane over them.
- **No serving, no opening.** The build only writes files. There is no
  `--open`; facet's own preview opens the `document` asset.
