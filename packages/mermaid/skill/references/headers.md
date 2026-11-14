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
