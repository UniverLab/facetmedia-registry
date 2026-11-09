# rhubarb — mouth cues for a drawn character

`facet run rhubarb.bocas` reads a voice clip and the text it says, runs
[Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync) 1.14.0
(**MIT**) on it, and writes `bocas.json`: the `mouthCues` timeline an avatar
animation plays frame by frame. One capability, `rhubarb.bocas`, in the
**`video`** facet, writing the **`text`** kind. The Rhubarb license is **MIT**
with commercial use allowed and no acceptance step.

Drawn characters only. Photoreal human photo animation was tried at the lab
and rejected: the talking heads landed in the uncanny valley and the Ditto
avatar line was deleted. A hand-drawn character with eight mouths has no
valley to fall into, so `rhubarb` takes the voice-and-mouths route.

## The pinned zip

Rhubarb ships as a zip holding one Linux ELF plus its `res/` data directory,
and the manifest pins that exact archive:

| Field | Value |
|-------|-------|
| `id` | `rhubarb-lip-sync-1.14.0-linux` |
| `url` | `https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/Rhubarb-Lip-Sync-1.14.0-Linux.zip` |
| `sha256` | `a9a9074862cff47b2d59b8bf399a678a3b0b74f9452ad6ad94cb292913dd8667` |
| `bytes` | `87225003` |
| `path` | `rhubarb-lip-sync-1.14.0-linux/Rhubarb-Lip-Sync-1.14.0-Linux.zip` |
| `spdx` | `MIT` |

`facet pull rhubarb` streams the zip into `models/direct/` under that `path`
and verifies the sha256 before it lands. The runner unpacks it once into
`_rhubarb-lip-sync-1.14.0-linux/` beside `runner.py`, writing `zip.sha256` as
its marker, and re-extracts on the next run only when the archive's hash no
longer matches the marker. Rhubarb finds `res/` beside the executable, so the
ELF is passed absolute, and the `-o` path is absolute too: Rhubarb resolves
`-o` against its cwd, so a relative `-o` combined with a changed cwd writes
nowhere and dies with `basic_ios::clear: iostream error` after 100% progress.

## Why a python-env engine and not `[engine.binary]`

facet's `[engine.binary]` packages assume the tool speaks the runner protocol
— `run --input <request> --result <result>`. Rhubarb does not: its argv is
`rhubarb [options] <wav> -o file`, an unrelated command line with its own
flags. So the package is a **python-env** subprocess client: `runner.py` owns
the four verbs, resolves the pinned zip through `req.model_path(...)`,
extracts it, and shells out to the ELF. The manifest declares no
`[engine.binary]`.

## The command

Every run is the same argv, in this order:

```bash
rhubarb -r phonetic -f json --dialogFile <texto> <voz.wav> -o bocas.json
```

- `-r phonetic` selects the phonetic recognizer. **This flag is mandatory.**
  Rhubarb's default is the English-only pocketSphinx recognizer, so without
  `-r phonetic` a Spanish dialog comes out with English mouth shapes that do
  not match the voice. The runner always passes it, and an argv that lost it
  throws a plain `Error` and exits 1, which facet reports as `runner_failed`
  naming the trap.
- `-f json` is the JSON output the animation reads.
- `--dialogFile <texto>` is the piece's `dialogo`: what the voice says, which
  the recognizer aligns the audio against.
- `<voz.wav>` comes before `-o`, which is where Rhubarb writes the cues.

`invalid_input` is facet-side — a bad piece or a schema failure — and cannot
come out of the runner.

## The piece

```toml
[inputs]
voz = "personaje/voz.wav"
dialogo = "personaje/dialogo.txt"
```

Both are paths resolved relative to the piece file. `voz` is the WAV the
mouths follow; `dialogo` is the plain text of what it says.

## The mouths

Rhubarb emits one letter per cue, from the eight-shape Preston Blair set plus
its rest shape:

| Letter | Mouth |
|--------|-------|
| `X` | rest |
| `A` | closed |
| `B` | teeth |
| `C` | open |
| `D` | wide |
| `E` | round |
| `F` | pursed |
| `G` | teeth on lip |
| `H` | tongue |

`bocas.json` carries `metadata.duration` and `mouthCues`, each cue a
`{start, end, value}` span in seconds. The approved lab pattern is
`/home/jheisonmblivecom/Academic/Deriverables/Grafics/projects/prueba-personaje/bocas.json`
— 65 cues over 10.32 s from a Spanish voice clip, using `X A B C E F G H`.

## Judging the result

`verify` reads `bocas.json` and passes when it parses to at least one cue, its
mouths are all in `XABCDEFGH`, and its cues are in time order. The metrics are
`duration_s`, `cues`, `mouths` (how many distinct letters) and `ordered`,
under `verifier = "rhubarb-lip-sync-1.14.0"`.

`facet preview bocas.json` writes `bocas.json.preview.json` for the `generic`
viewer — the same viewer whisper uses for its kind `text` — with a summary such
as `10.3 s · 65 mouth cues · 8 mouths (XABCEFGH)` and the same fields plus
`recognizer = "phonetic"` and `mouths_used`.

`facet doctor rhubarb` runs two quick checks:

- `zip` — the pinned archive is present with the manifest's byte size; when it
  is not, the fix is `facet pull rhubarb`.
- `binary` — the extracted ELF is executable and starts on this machine. A
  verified archive whose binary cannot start — the wrong platform — reports
  with no pull fix, so facet classifies it `machine_cannot`: pulling again
  cannot fix it.

## Example

The approved lab project is
`/home/jheisonmblivecom/Academic/Deriverables/Grafics/projects/prueba-personaje`:
a fox SVG with eight mouths and a 10.32 s Spanish voice clip. Its `build.mjs`
runs exactly the command above and inlines the resulting `mouthCues` into the
HyperFrames composition; the character assembly itself is the `hyperframes`
package's job, out of scope here.

A piece for that clip is only its two paths:

```toml
[inputs]
voz = "assets/voz.wav"
dialogo = "dialogo.txt"
```

Rhubarb takes about a second for a 10 s clip, and `facet doctor rhubarb`
reports `healthy: true` once the pull has landed the zip.
