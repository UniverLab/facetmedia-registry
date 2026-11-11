# @page snippets

## Slides: fixed size and one break per slide

The slide size lives in one `@page` rule; each slide is a block that breaks
after itself. Leave the last slide without a break so the PDF does not gain a
trailing blank page.

```css
@page {
  size: 1280px 720px;
  margin: 0;
}

.slide {
  width: 1280px;
  height: 720px;
  page-break-after: always;
  break-after: page;
}

.slide:last-child {
  page-break-after: auto;
  break-after: auto;
}
```

```html
<section class="slide">…</section>
<section class="slide">…</section>
<section class="slide">…</section>
```

- The PDF page count equals the number of `.slide` elements. A missing break
  merges two slides onto one page.
- `size` must match the slide's own `width`/`height`, or the content is scaled
  or clipped by Chrome.
- `margin: 0` because the slide owns its own padding.

## One-page pieces: no @page

A poster or infographic sets **no** `@page` and no page breaks. `deck.page`
renders it in screen media and measures the content's height, then exports
exactly one page at that height.

```css
html,
body {
  margin: 0;
}

.piece {
  width: 1060px; /* the render's --width */
  padding: 48px;
}
```

- A width that differs from `--width` (default `1060`) changes the measured
  layout; keep the two in step.
- The content decides the height: no fixed `height`, no `@page`.
- A sources footer and captioned images are required by the runner's checks
  (`footer-sources`, `captioned-images`).
