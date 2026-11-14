---
name: demostage
description: Terminal demo gif and animated SVG from a hand-written demo.toml score, recorded by the person-installed demo binary in its own PTY with no caller terminal.
---
# demostage

`demostage.demo` reads a hand-written `demo.toml` score and runs the
person-installed `demo` binary: `demo record` executes the score in its own
PTY and writes a `.rec`, then `demo export` renders that recording to a gif and
an animated svg. The gif is the primary `video` asset; the terminal-only svg
rides beside it as an `image` asset. One capability, two assets.

## When to use

- A terminal session must become a reproducible, version-controlled demo: a
  `demo.toml` score lives in the piece and facet records and exports it.
- The session can be scripted ahead of time — `focus`, `type`, `keypress`,
  `wait`/`wait_for_stdout`, `terminate`.
- Not for a live interactive capture: `demo capture` needs a terminal on
  stdin/stdout, and a facet runner has none. Write the score by hand instead.
  The headless probe proved the split: `demo record` exit 0 and `demo export`
  gif/svg exit 0 with no TTY, while capture still needs an interactive
  terminal and stays out of facet.

## Pieces

```toml
[inputs]
score = "demo/demo.toml"
```

`score` resolves relative to the piece and is the score the runner
executes. A minimal score:

```toml
[demo]
name = "cli-tour"
output_dir = "./dist"

[typing]
base_ms = 80
salt_ms = 15
seed = 42

[layout]
width = 1280
height = 720
fps = 15
font_family = "DejaVu Sans Mono"

[[timeline]]
action = "focus"
pane = "main"

[[timeline]]
action = "type"
text = "facet --help"
human_salt = true

[[timeline]]
action = "keypress"
key = "enter"

[[timeline]]
action = "wait_for_stdout"
match = "Usage"

[[timeline]]
action = "terminate"
```

The score DSL: `focus` (set the active pane), `type` (`text`,
`human_salt`), `keypress` (`key` such as `enter`, `tab`, `ctrl+c`), `wait`
(`duration_ms`), `caption` (`text`), `wait_for_stdout` (`match`, `pane?`),
`scroll` (browser panes), `focus_scene` (`scene`), `terminate`. The run always
does record first, then export: `demo export` plays back a `.rec`, it never
executes the score. The runner's argv is:

```bash
demo record <score> -o <out>/_demostage/demo.rec
demo export gif,svg <out>/_demostage/demo.rec
```

## Authoring the score

- **Settings first, steps after.** `[demo]`, `[typing]` and `[layout]` are read
  once, before the first step runs; a settings table written below the first
  `[[timeline]]` block is ignored and the demo renders with defaults that look
  like a different piece. Public tape formats document the same silent-ignore
  trap, so keep every settings table above the first step.
- **Wait for output, not for time.** `wait_for_stdout` with a `match` returns
  the moment the program prints it and takes exactly as long as the machine
  needs; `wait` with `duration_ms` is for a dramatic pause only, and it drifts
  with machine speed. Never pad a step with a sleep to cover a command that has
  not finished printing.
- **Record first, then transcribe.** The reliable authoring loop is to run the
  session once yourself, keep the transcript, and turn it into `focus`, `type`,
  `keypress` and `wait_for_stdout` steps in that order. Timings invented blind
  are the usual reason a demo scrolls past its own output.
- **Frame it on purpose.** `[layout]` covers size, fps and font, and the gif
  loops from its first frame, so open on the state worth seeing: a title or a
  prompt, never the cursor blinking on an empty screen.

The score DSL is what facet has: there is no key to hide a command's output
while it still runs, no per-step typing-speed override (a step's `human_salt`
only adds jitter on top of `[typing]`'s global speed), no loop-start frame for
the gif poster, and no theme or window-chrome knob. Public tape formats offer
all four and facet deliberately does not, because a demo here is a reproducible
score, not a styled product page; do not write those keys into a score.

## Judging the result

`verify` reads both files back: the gif must start with `GIF87a`/`GIF89a` and
hold at least one frame, the svg must parse as XML and declare a size. Its
metrics are the gif's `width`, `height`, `frames` and `duration_s`, and the
svg's `width` and `height`.

`facet preview` writes the gif's `video` preview (a person plays it, an agent
reads frames, size and fps) and, for the terminal-only svg, the `image`
preview. Read the summary first; open the gif when a step looks wrong.

## Pitfalls

- Fonts and seeds decide reproducibility. Set `[layout].font_family` to one of
  the bundled monospace fonts (`DejaVu Sans Mono` has the widest Unicode
  coverage) and `[typing].seed` whenever output must be byte-stable.
- `demo` is person-installed (`curl -fsSL https://get.univerlab.org/demostage
  | sh`, or `cargo install --path .` from the checkout). `facet pull` never
  installs or bundles it; `doctor` reports `machine_cannot` with that install
  line when it is missing or older than 0.4.0.
- `output_dir` is relative to the export's working directory unless absolute;
  keep the default `./dist` so the runner finds `<name>.gif` and `<name>.svg`.
- Browser panes are captured after the terminal run, so point them at a file
  that still exists then. MP4 is not requested: the gif and svg are enough.
- Never reach for `capture`: it needs an interactive terminal, and the score
  is written by hand in the piece anyway.

Sources: `references/sources.md` lists the public source the authoring section
relies on, with its maintainer, licence and what was taken from it.
