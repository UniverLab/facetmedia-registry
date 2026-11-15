# demostage — terminal demos from hand-written scores

`facet run demostage.demo` reads a `demo.toml` score, runs the
[demostage](https://github.com/UniverLab/demostage) `demo` binary (**MIT**), and
writes a terminal demo as a gif plus an animated svg. One capability,
`demostage.demo`, in the **`video`** facet: the gif is the primary `video`
asset, and the terminal-only svg rides beside it as an `image` asset.

## The headless path

A facet runner has no terminal on stdin/stdout, so the run never captures a
live session. It performs exactly two steps, in this order:

```bash
demo record <score> -o <out>/_demostage/demo.rec   # allocates its own PTY
demo export gif,svg <out>/_demostage/demo.rec          # plays the .rec back
```

`demo record` executes the score in a PTY it allocates itself, so it needs no
caller terminal; `demo export` renders that recording, never the score. The
gif and svg land under the score's `output_dir` (the default `./dist`, resolved
against the export's working directory) and the runner moves them to the run's
output root as `<name>.gif` and `<name>.svg`.

Proven on this machine: with a hand-authored score and stdin/stdout not a TTY,
`demo record` exited 0 and `demo export svg` and `demo export gif` both exited
0 — a 13.3 KB animated svg. The same probe also established the exclusion
below.

## `capture` is excluded, with the evidence

`demo capture` records an interactive session and normalizes it to a score. It
reads stdin from an interactive terminal, and a facet runner has none, so the
capability deliberately offers no capture path. The capability takes a
hand-written score (`score`) instead; the demo CLI's own contract for that
is "You can skip capture and author `demo.toml` by hand, then `record` +
`export`."

## The person-installed binary

`demo` is installed by the person, never by `facet pull`:

```bash
curl -fsSL https://get.univerlab.org/demostage | sh
# or, from a demostage checkout
cargo install --path .
```

The runner resolves `demo` on `PATH` and requires **0.4.0** or newer, checked
by parsing `demo --version`. It never touches the demo config or the font
cache. When the binary is missing or older, `doctor` reports the check as
`machine_cannot` with the install line above as its fix.

## The piece

```toml
[inputs]
score = "demo/demo.toml"
```

`score` is resolved relative to the piece and is the score the runner
executes. A score declares the demo name, the export directory, the typing
seed, the layout (width, height, fps, font) and a timeline:

```toml
[demo]
name = "cli-tour"
output_dir = "./dist"

[typing]
seed = 42

[layout]
width = 1280
height = 720
fps = 15
font_family = "DejaVu Sans Mono"

[[timeline]]
action = "type"
text = "facet --help"

[[timeline]]
action = "keypress"
key = "enter"

[[timeline]]
action = "wait_for_stdout"
match = "Usage"

[[timeline]]
action = "terminate"
```

The timeline actions are `focus`, `type`, `keypress`, `wait`, `caption`,
`wait_for_stdout`, `scroll`, `focus_scene` and `terminate`. Set
`[typing].seed` and a bundled `font_family` when the output must be
byte-stable.

## Judging the result

`verify` reads both files back: the gif must start with `GIF87a`/`GIF89a` and
hold at least one frame, and the svg must parse as XML and declare a size.
Metrics are the gif's `width`, `height`, `frames` and `duration_s`, and the
svg's `width` and `height`, under `verifier = "demostage"`.

`facet preview` writes the gif's `video` preview — a person plays it, an agent
reads its size, frame count and fps — and the `image` preview for the animated
svg. The capability's viewer is `video`.

## Why a python-env engine and not `[engine.binary]`

facet's `[engine.binary]` packages assume the tool speaks the runner protocol —
`run --input <request> --result <result>`. The demo CLI does not: its verbs are
`capture`, `record`, `export`, `edit` and `doctor`, with their own argument
lines. So the package is a **python-env** subprocess client whose `runner.py`
owns the four verbs; the manifest declares no `[engine.binary]`,
`[[models]]` or server.

## Bundled examples

`facet example <capability> --run` copies the capability's example, with
every file it names, into a fresh folder and runs it there:

- `demostage.demo` — `examples/demo.toml`: `facet example demostage.demo --run`

Needs the person-installed `demo` binary and its licence.
