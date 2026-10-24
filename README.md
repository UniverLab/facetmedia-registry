# facetmedia-registry

This repository holds facetMedia's **packages** and **viewers** apart from the
core ([UniverLab/facetmedia](https://github.com/UniverLab/facetmedia)), so a new
tool can arrive without a facet release. A **package** is one directory under
`packages/` with its `package.toml` manifest; a **facet** is the domain it
belongs to (`voice`, `audio`, `image`, `video`, `cad`, `text`,
`presentation`) — Kokoro (speech) and Whisper (transcription) are both
`voice` — and the **kind** is the kind of asset a capability writes
(`audio`, `text`, `cad`, ...), which picks the preview schema
([`schemas/preview/`](schemas/preview/README.md)) and the viewer
(`viewers/<kind>/`).
facet downloads this registry at a **pinned commit** (`facet update`) and
reads `index.toml`, `packages/<name>/` and `viewers/<name>/` from that
snapshot, offline; the formats are defined by the core:
[registry](https://github.com/UniverLab/facetmedia/blob/main/docs/registry.md),
[skill](https://github.com/UniverLab/facetmedia/blob/main/docs/skill.md),
[preview](https://github.com/UniverLab/facetmedia/blob/main/docs/preview.md).

## Packages

| Facet | Package | What it does |
|-------|---------|--------------|
| text | ascii | ASCII art from images and figlet banners in the lab's font |
| voice | kokoro | Narration from text on CPU (Spanish and English), checked by transcription |
| voice | whisper | Transcripts and subtitles from audio on CPU, checked by confidence or reference text |

## How facet uses this repository

`facet update` downloads this repository, resolves the ref to one exact commit
and keeps that commit as an immutable snapshot under `FACET_HOME`; every later
command (`facet pull`, `facet run`, `facet preview`, `facet skill`,
`facet doctor`) reads that snapshot, offline. `index.toml` lists the package
directories facet knows about. (`facet registry validate` is the exception: it
validates the registry directory you give it, which is how CI reads a
checkout.) Because the commit is pinned, an unpublished package reaches
machines only once a pull request merges to `main`.

## Entry criteria

A package is merged when all of the following hold:

1. Its **facet**, declared in the manifest.
2. A declared **licence** for the tool and for every model
   (`spdx`, `commercial_use`, `requires_acceptance`).
3. An **output that `verify` can measure**.
4. Its own **`doctor` verb**: at `quick` depth (about 2 s, writes nothing) it
   checks imports, files and versions; at `full` depth (up to 30 s) it makes
   one throwaway output. Every failing check names its fix. `facet registry
   validate` rejects a runner without it.
5. Its **skill**, `skill/SKILL.md` in the core's format. An agent learns the
   package from `facet skill <package>`; skills are never installed into agent
   directories. `facet registry validate` rejects a package without a valid
   skill.
6. It **fits the reference machine** (8 GB VRAM, 19 GB RAM, one heavy job at a
   time) and says so in `requirements`.
7. A **`preview`** that writes the preview file of its kind; a kind without a
   preview schema and a viewer adds both in the same change.
8. **No text or data inside generated images.**
9. **Heavy local tests run alone** on the lab machine.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the step-by-step, and
[packages/README.md](packages/README.md),
[viewers/README.md](viewers/README.md) and
[schemas/preview/README.md](schemas/preview/README.md) for the directory
layouts and the preview fields of each kind.
