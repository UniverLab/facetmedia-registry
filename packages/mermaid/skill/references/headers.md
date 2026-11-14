# Header snippets

The style lives in the YAML header of the `.mmd` file, between `---` lines,
before the diagram type. Copy these verbatim.

## `cycle.mmd` — flowchart header

```yaml
---
config:
  theme: base
  themeVariables:
    primaryColor: "#222928"
    primaryBorderColor: "#d9b878"
    primaryTextColor: "#ecebe4"
    lineColor: "#b9bdb5"
    fontFamily: "Ubuntu"
    fontSize: "22px"
---
```

Use this one for a flowchart or any diagram destined for video: `fontSize`
is raised to `"22px"` because the default is small at 1080p.

## `architecture.mmd` — architecture header

```yaml
---
config:
  theme: base
  themeVariables:
    primaryColor: "#f4f0ea"
    primaryBorderColor: "#8a6a2c"
    primaryTextColor: "#1d1510"
    lineColor: "#6b5a43"
    fontFamily: "Ubuntu"
    fontSize: "18px"
---
```

## Hand-drawn style

Add `look: handDrawn` under `config` for the Excalidraw-style drawing,
approved as `examples/cycle-hand.png`:

```yaml
---
config:
  theme: base
  look: handDrawn
  themeVariables:
    fontFamily: "Ubuntu"
    fontSize: "22px"
---
```

`theme` is `base` in every approved pattern; `fontFamily` is a single
installed family, `"Ubuntu"`.

## The v12 default look (and how to get the old one back)

Since v12, ten diagram types — flowchart, sequence, class, entity-relationship,
state, and others — render with a new color set, a new edge style and a new
automatic layout unless the header says otherwise. Every other diagram type
keeps the older appearance. Facet's renderer is pinned at that generation, so
leaving these keys out produces the new look, not the old one.

To reproduce the earlier appearance on one of those ten types, set the three
keys explicitly under `config`:

```yaml
config:
  theme: default
  look: classic
  layout: dagre
```

Facet deliberately keeps `theme: base` in its approved patterns instead: it is
the one theme whose palette an author can fully restyle, so the lab's own
colors win over either built-in default. An agent that has read the public
docs may expect the new defaults; facet pins `base` on purpose.

## Misspelled keys fail silently

An unknown key under `config` or `themeVariables` is skipped without an
error: a mistyped color name renders with the fallback color and looks wrong
with no diagnostic. When styling looks off, compare the header line by line
against the snippets above rather than trusting that a quiet run means a
correct header.

## Architecture layout knobs

Fine spacing for `architecture-beta` lives under `config.architecture`:

- `nodeSeparation` widens or tightens the gaps between services;
- `idealEdgeLengthMultiplier` stretches or shortens the arrows;
- `edgeElasticity` decides how rigidly arrows hold their length;
- `numIter` sets how many solver passes refine the placement.

Reach for these before redrawing the diagram by hand. `randomize` defaults
to `false`, so nodes start from seeded positions; `randomize: true` re-rolls
them. `seed` defaults to `1`, which replays the same layout every run; set
`seed: 0` to opt out to native randomness, or another number for a different
reproducible variant. Even with `randomize: false` the solver calls the
platform's random number generator, so `seed` is the lock.

## Mindmap depth coloring

Since Mermaid 12.2, a mindmap can color by hierarchy level with:

```yaml
config:
  mindmap:
    colorBy: depth
```

Each depth then takes its color from the `cScale1` … `cScale11` series and
its label color from `cScaleLabel1` … `cScaleLabel11`. The root has its own
variables: `git0` and `gitBranchLabel0`, with `cScaleLabel0` for its label in
the `neo` look. Under `theme: base` also set `useGradient: false`, or every
node is painted with the single `mainBkg` color.
