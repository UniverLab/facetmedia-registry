# Timeline rules

Every capability renders the same kind of timeline: one paused
`gsap.timeline()` registered in `window.__timelines`, keyed by the
composition's `data-composition-id`. The render seeks each frame by time, so
nothing may depend on wall-clock callbacks.

The shared base shape:

```js
const tl = gsap.timeline({ paused: true });
tl.to('#contador', { textContent: 42, snap: 'textContent', duration: 2 }, 0.4);
tl.from('#titulo', { opacity: 0, y: 24, duration: 0.6 }, 0);
window.__timelines['main'] = tl;
tl.seek(0);
```

- One paused `gsap.timeline()` on `window.__timelines`, never a running one.
- Counters tween `textContent` with `snap`, never `onUpdate`: the render seeks
  every frame, so callbacks do not fire.
- `window.__timelines` is keyed by the composition's `data-composition-id`.

## hyperframes.render

The composition carries its own paused timeline. Nothing is injected from the
runtime: the author's `index.tmpl` is the timeline, and `audio` clips enter as
`<audio>` elements. `fps` only changes the export frame rate; `data-fps` on the
composition applies when `fps` is omitted.

## hyperframes.loop

`loop` renders the same source and the same paused timeline as `render`; the
`format` input only chooses the export (`gif` or `mov-alpha`). Do not rewrite
the timeline for a loop: a GIF and a MOV with alpha are the same frames.

## hyperframes.diagrama

`animacion` is an ordered list of `{ selector, at, kind, dur }` steps. `kind` is
`show`, `draw` or `fade`, and `dur` defaults to `0.4`. The runner validates
every selector against the ids the SVG carries, then injects this paused
timeline into `index.tmpl` before `check`:

```js
const tl = gsap.timeline({ paused: true });
pasos.forEach(function (paso) {
  var targets = document.querySelectorAll(paso.selector);
  if (paso.kind === 'show') {
    tl.from(targets, { opacity: 0, scale: 0.85, transformOrigin: '50% 50%', duration: paso.dur, ease: 'back.out(2)' }, paso.at);
  } else if (paso.kind === 'fade') {
    tl.from(targets, { opacity: 0, duration: paso.dur, ease: 'power1.out' }, paso.at);
  } else {
    drawEach(targets, paso);
  }
});
window.__timelines['main'] = tl;
tl.seek(0);
```

`draw` sets `strokeDasharray` and `strokeDashoffset` to the path length and
tweens the offset to zero. A `g` edge is resolved to its inner `path` first, and
the `polygon.arrow` right after it fades in with the path. Selectors are built
by string concatenation, never a `${}` template: the HyperFrames bundler rejects
template literals in selectors.

## hyperframes.giro

The scene is a pure function of time. `renderAt(t)` is called from the
`hf-seek` event, and `event.detail.waitUntil(promise)` makes HyperFrames wait
for the model to load:

```js
function renderAt(t) {
  const o = DATA.orbita;
  const angulo = o.desde + (t / DATA.duracion) * o.vuelta * Math.PI * 2;
  const [cx, cy, cz] = DATA.centro;
  camera.position.set(cx + o.radio * Math.cos(angulo), o.altura, cz + o.radio * Math.sin(angulo));
  camera.lookAt(cx, cy, cz);
  renderer.render(scene, camera);
}
window.addEventListener('hf-seek', (event) => {
  event.detail.waitUntil(listo.then(() => renderAt(event.detail.time)));
});
```

`requestAnimationFrame` and `performance.now()` are rejected by `check` and by
the runner. The runner base64-embeds `modelo-glb` at `/* GLB */""` and writes
the eight scalars at `/* GIRO */`, inside `const DATA = {`. Text stays in HTML
over the canvas.

## hyperframes.personaje

The template carries `const AUDIO_START = <number>;` exactly once and the
`/* BOCAS */[]` marker exactly once. The runner replaces the marker with the
`bocas.json` cues and writes `audio-inicio` into `AUDIO_START`. The timeline is
one `tl.set` per mouth change, shifted by the same amount as the voice
`<audio data-start>`:

```js
CUES.forEach(function (cue) {
  tl.set('.boca', { opacity: 0 }, AUDIO_START + cue.start)
    .set('#boca-' + cue.value, { opacity: 1 }, AUDIO_START + cue.start);
});
```

A `tl.set` at instant 0 never shows, so the CSS carries the rest state:
`.boca { opacity: 0; } #boca-X { opacity: 1; }`. Blinks and a gentle head sway
stay at fixed times in the template; they are not piece inputs.

## hyperframes.narrado

`index.tmpl` carries exactly one `<!-- SUBS -->` marker, exactly one
`<!-- AUDIOS -->` marker and a positive `data-duration` on the
`data-composition-id` tag. The runner parses the `.srt` into
`{ start, end, text }` cues, requires every cue end to fit `data-duration`, and
appends the opacity timeline that joins the composition's timeline:

```js
cues.forEach(function (cue, index) {
  tl.set('#s' + index, { opacity: 1 }, cue.start)
    .set('#s' + index, { opacity: 0 }, cue.end);
});
```

Subtitles are burned into the frames as `.sub` divs, never a sidecar copy. The
narration `<audio>` elements carry no `data-start`: the `.srt` times are
absolute on the composition, so the cues are not shifted. If a template gives
the voice a `data-start`, the `.srt` must already start at that offset.
