# architecture-beta

`architecture-beta` draws groups, services, port arrows and icons. The
approved body, `architecture.mmd`, verbatim:

```mermaid
architecture-beta
  group lab(cloud)[Local lab]
  group gpu(server)[Local GPU] in lab

  service agent(logos:claude-icon)[Agent] in lab
  service toml(disk)[Piece toml] in lab
  service voice(mdi:microphone)[VoiceStudio] in gpu
  service comfy(mdi:image-filter-hdr)[ComfyUI] in gpu
  service output(database)[WAV and PNG] in lab
  junction dispatch in lab

  agent:R --> L:toml
  toml:R -- L:dispatch
  dispatch:R --> L:voice
  dispatch:B --> L:comfy
  voice:R --> L:output
```

## Ports

Every arrow leaves and enters through a port: `L`, `R`, `T`, `B` (left,
right, top, bottom). Write the source as `service:PORT` and the destination
as `PORT:service`, separated by `-->` for a directed arrow or `--` for a
plain line.

## Icons

Built-in icons: `cloud`, `database`, `disk`, `internet`, `server`.

Every render passes `--iconPacksNamesAndUrls`, so Iconify is loaded too:
`logos:<marca>` (for example `logos:docker-icon`) and `mdi:<icono>`
(Material, for example `mdi:microphone`).

## Junctions

A `junction` splits one exit into several arrows without an extra box. In
`architecture.mmd`, `dispatch` is the junction: `toml:R -- L:dispatch` feeds
it, then `dispatch:R --> L:voice` and `dispatch:B --> L:comfy` fan out.

## The B-port trap

An arrow that leaves from the bottom (`B`) crosses the service's label. Split
the exit through a `junction` instead of drawing the `B` arrow from the
service itself, as `dispatch` does above.

## Lining services up with `align`

To place services in a shared row or column, declare it instead of chaining
invisible links:

```mermaid
architecture-beta
  align row agent toml
  align column voice comfy
```

Each `align` names the members along one axis in order, and that order sets
their order on the axis. The declared order must agree with the arrow
directions between the members — lining up two services whose arrow runs the
other way fights the layout. Facet's older invisible-link chain (`a ~~~ b`)
still applies to flowcharts, which have no `align` directive; in
`architecture-beta` prefer `align`. An agent that has read older facet
examples may reach for `~~~` here; the directive is the current form.
