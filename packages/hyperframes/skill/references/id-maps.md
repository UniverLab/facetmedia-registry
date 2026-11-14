# SVG and DOM id maps

Selectors are the classic silent failure: they pass review and fail the render.
These names are verbatim from the approved lab proofs. Build them by string
concatenation, never a `${}` template, because the HyperFrames bundler rejects
template literals in selectors.

## hyperframes.render

The composition's own ids are the map. The timeline is registered under the
`data-composition-id` value, and each clip is addressed by its id:

```html
<div id="root" data-composition-id="main" data-start="0" data-duration="3">
  <h1 id="title" class="clip" data-start="0" data-duration="3" data-track-index="0">HyperFrames</h1>
</div>
```

```js
window.__timelines['main'] = tl;
```

## hyperframes.loop

Identical to `render`: the same `data-composition-id` key and the same clip
ids. A loop adds no ids; it only changes the file the frames are written to.

## hyperframes.diagram

A Mermaid SVG keeps generated ids. Use these helpers from the approved
flowchart proof:

```js
// Mermaid ids: nodes "my-svg-flowchart-<id>-<n>", edges "my-svg-L_<from>_<to>_0", edge labels id "L_<from>_<to>_0".
const node = (id) => document.querySelector('[id^="my-svg-flowchart-' + id + '-"]');
const edge = (from, to) => document.getElementById('my-svg-L_' + from + '_' + to + '_0');
const label = (from, to) => document.querySelectorAll('.edgeLabels [data-id="L_' + from + '_' + to + '_0"]');
```

- **Flow nodes**: `my-svg-flowchart-<id>-<n>`; select them by prefix with
  `[id^="my-svg-flowchart-<id>-"]` (helper `node(id)`).
- **Flow and architecture edges**: `my-svg-L_<from>_<to>_0`; select by
  exact id `#my-svg-L_<from>_<to>_0` (helpers `edge(from, to)` and
  `byId`).
- **Edge labels**: `.edgeLabels [data-id="L_<from>_<to>_0"]` (helper
  `label(from, to)`).
- **Architecture services and groups**: `#my-svg-service-<id>`,
  `#my-svg-group-<id>`, `#my-svg-group-lab`, `#my-svg-group-gpu`;
  **singletons**: `#my-svg-gpu`.
- **Arrowheads**: the `polygon.arrow` right after its edge path, i.e.
  `path.nextElementSibling`. `draw` fades the arrowhead in with the path.

The architecture proof uses the same map through `byId`:

```js
const byId = (id) => document.getElementById(id);
```

## hyperframes.turntable

The two markers the runner writes:

- `/* GLB */""` — replaced by the base64 of `model-glb`.
- `/* TURNTABLE */` — replaced by the eight scalars, inside `const DATA = {`.

The importmap pins the module names the scene imports:

```html
<script type="importmap">
  { "imports": { "three": "./vendor/three.module.js",
                 "three/addons/": "./vendor/three/addons/" } }
</script>
```

The timeline is registered under the composition's `data-composition-id`.

## hyperframes.character

One shape per Rhubarb letter, in the character SVG under `#mouth`:

| id | letter | mouth |
| --- | --- | --- |
| `mouth-X` | X | rest |
| `mouth-A` | A | closed (m, b, p) |
| `mouth-B` | B | teeth (most consonants) |
| `mouth-C` | C | open (e) |
| `mouth-D` | D | wide open (a) |
| `mouth-E` | E | round (o) |
| `mouth-F` | F | pursed (u) |
| `mouth-G` | G | teeth on lip (f, v) |
| `mouth-H` | H | tongue (l) |

The CSS carries the rest state, because a `tl.set` at instant 0 never shows:

```css
.mouth { opacity: 0; } #mouth-X { opacity: 1; }
```

The runner requires that rule in `index.html` or in the SVG's own `<style>`, and
requires `#mouth-<letter>` for every letter `mouths.json` uses.

## hyperframes.narrated

- **Markers**: exactly one `<!-- SUBS -->` and exactly one `<!-- AUDIOS -->`.
- **Cue shape**: `{ start, end, text }`, rounded to 3 decimals.
- **Subtitle divs**: `.sub` styled in CSS, ids `#s0`, `#s1`, …
- **Audio elements**: `#voice-1`, `#voice-2`, … and `#music`.

The runner parses whisper's `HH:MM:SS,mmm --> HH:MM:SS,mmm` timing lines (comma
or dot milliseconds, text joined by spaces) into that cue shape.
