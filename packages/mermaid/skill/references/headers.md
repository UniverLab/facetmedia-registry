# Header snippets

The style lives in the YAML header of the `.mmd` file, between `---` lines,
before the diagram type. Copy these verbatim.

## `ciclo.mmd` — flowchart header

```yaml
---
config:
  theme: base
  themeVariables:
    primaryColor: "#eef3fb"
    primaryBorderColor: "#2a78d6"
    lineColor: "#555"
    fontFamily: "Ubuntu"
    fontSize: "22px"
---
```

Use this one for a flowchart or any diagram destined for video: `fontSize`
is raised to `"22px"` because the default is small at 1080p.

## `arquitectura.mmd` — architecture header

```yaml
---
config:
  theme: base
  themeVariables:
    fontFamily: "Ubuntu"
    fontSize: "18px"
---
```

## Hand-drawn style

Add `look: handDrawn` under `config` for the Excalidraw-style drawing,
approved as `examples/ciclo-mano.png`:

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
