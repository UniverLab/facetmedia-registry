# architecture-beta

`architecture-beta` draws groups, services, port arrows and icons. The
approved body, `arquitectura.mmd`, verbatim:

```mermaid
architecture-beta
  group lab(cloud)[Laboratorio local en WSL]
  group gpu(server)[GPU local] in lab

  service agente(logos:claude-icon)[Agente] in lab
  service toml(disk)[Pieza toml] in lab
  service voz(mdi:microphone)[VoiceStudio] in gpu
  service comfy(mdi:image-filter-hdr)[ComfyUI] in gpu
  service salida(database)[WAV y PNG] in lab
  junction reparto in lab

  agente:R --> L:toml
  toml:R -- L:reparto
  reparto:R --> L:voz
  reparto:B --> L:comfy
  voz:R --> L:salida
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
`arquitectura.mmd`, `reparto` is the junction: `toml:R -- L:reparto` feeds
it, then `reparto:R --> L:voz` and `reparto:B --> L:comfy` fan out.

## The B-port trap

An arrow that leaves from the bottom (`B`) crosses the service's label. Split
the exit through a `junction` instead of drawing the `B` arrow from the
service itself, as `reparto` does above.
