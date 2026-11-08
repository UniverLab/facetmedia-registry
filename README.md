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
reads `index.toml`, `packages/<name>/`, `lib/<name>.py` and
`viewers/<name>/` from that snapshot, offline; the formats are defined by
the core:
[registry](https://github.com/UniverLab/facetmedia/blob/main/docs/registry.md),
[skill](https://github.com/UniverLab/facetmedia/blob/main/docs/skill.md),
[preview](https://github.com/UniverLab/facetmedia/blob/main/docs/preview.md).

## Packages

| Facet | Package | What it does |
|-------|---------|--------------|
| audio | acestep | Instrumental beds from an English caption with ACE-Step 1.5, at most 30 s per piece, checked by duration and peak |
| audio | ffmpeg | Normalise, mix and convert audio clips with FFmpeg, with loudness and duration verified |
| audio | moss | Described sound effects from an English description with MOSS-SoundEffect v2 on a staged CPU/GPU memory path, at most 30 s per effect, normalised to a loudness target (default -23 LUFS) and checked by integrated loudness |
| cad | cad | 3D parts and 2D plans from CadQuery or ezdxf scripts, checked by volume, bounding box and DXF audit |
| image | blender | Daylight architectural photos of CadQuery glTF models and studio product shots of CAD parts through a host Blender's Cycles GPU, and animated camera tours in Eevee, checked by pixel size and an MP4 probe; shared CC0 Poly Haven skies, textures and models fetched once into the models dir and re-checked by their receipt |
| image | comfy | Stills, reference-guided edits, clips and motion drafts with ComfyUI's z-image-turbo, flux2-klein and wan22-i2v flows, checked by pixel size and video probe |
| image | svganim | Self-contained animated SVGs baked from a Node script and its data, with every label drawn as a path by the pinned opentype.js and CSS @keyframes for the motion, plus a 2x PNG of the first frame rendered by sharp; no browser, plays inside an `<img>` on GitHub and embeds in HyperFrames |
| presentation | deck | Paginated PDF slide decks plus one PNG per page from a single HTML file with `@page` sizing and one break per slide, rendered through the host Chromium and rasterized by poppler's `pdftoppm`, a presenter build from the same file with one speaker note per slide, written as a self-contained speaker-view page plus its notes companion without serving or opening, and one-page pieces (infographics and posters) from HTML + CSS + SVG exported to a single-page PDF plus its page-01.png; page count verified against the rendered pages |
| presentation | mermaid | Diagrams to SVG and PNG from `.mmd` files with the pinned mermaid-cli and the system Chrome (`CHROME_PATH`, never a download), style in the YAML header, architecture-beta groups, services, port arrows and bundled plus Iconify icons |
| text | ascii | ASCII art from images and figlet banners in the lab's font |
| text | texforge | Long documents (reports, articles, theses) to verified PDF with real pagination, footnotes, indexes, bibliography and math via the person-installed texforge binary, with per-page PNG previews |
| voice | kokoro | Narration from text on CPU (Spanish and English), checked by transcription |
| voice | whisper | Transcripts and subtitles from audio on CPU, checked by confidence or reference text |
| voice | voicestudio | Narration from text through a user-started VoiceStudio backend with the voxcpm2, omnivoice or cosyvoice engine, checked by transcription and seed regeneration |
| video | hyperframes | MP4 clips, looping GIFs and alpha-channel MOVs from checked HTML+GSAP compositions with the pinned HyperFrames CLI, optionally with Mermaid diagrams animated by GSAP, a Three.js scene that turns an embedded CAD model on a camera orbit, a hand-drawn SVG character that speaks with Rhubarb mouths timed to the voice, or a narrated piece assembled from voice clips, a music bed and whisper subtitles; checked first and verified by an ffprobe probe; the host's Chromium and ffmpeg are required |
| video | rhubarb | Mouth cues X..H for a drawn character, timed to a voice clip from the text it says, with the phonetic recognizer of Rhubarb Lip Sync 1.14.0, writing bocas.json checked by cue count, mouth letters and time order; the pinned Linux ELF zip; about a second for a 10 s clip |

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
   preview schema and a viewer adds both in the same change — except a kind
   the core previews itself, like `document`, which opens the PDF in the
   system browser and needs neither.
8. **No text or data inside generated images.**
9. **Heavy local tests run alone** on the lab machine.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the step-by-step, and
[packages/README.md](packages/README.md),
[viewers/README.md](viewers/README.md) and
[schemas/preview/README.md](schemas/preview/README.md) for the directory
layouts and the preview fields of each kind.
