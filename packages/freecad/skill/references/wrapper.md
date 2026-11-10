# The wrapper: running a guion inside freecadcmd

Ported from the lab's `tools/freecad_run.py` and `tools/freecad.sh`. `freecadcmd`
exits 0 and prints nothing when a script raises, so the package drives every
script through its own wrapper, which reports the failure as a non-zero exit.

## The invocation

The wrapper is called with the host binary first, the wrapper second, `--pass`
before the target script, and the script's own arguments after it:

```text
<freecadcmd> freecad_run.py --pass <script.py> [args...]
```

The runner builds the launch line the same way, so the guion and the runner are
both run through the wrapper:

```text
[binary, wrapper, --pass, runner, --, <verb>, --input <request>, --result <result>]
```

The `--` matters: freecadcmd parses every dashed argument after `--pass` as
one of its own options and stops at `unrecognised option '--result'`; after
`--` it passes them through, and the runner drops everything up to it.

## Inside the script

The wrapper sets `sys.argv = [script.py, args...]` and executes the target with
`runpy.run_path(..., run_name="__main__")`. freecadcmd would otherwise supply
the file's stem as `__name__`, so the wrapper calls `main` unconditionally: a
guion's `if __name__ == "__main__":` block is true here.

## Failures

- A raising script would make freecadcmd exit 0 and print nothing. The wrapper
  catches `BaseException`, prints the `traceback`, flushes both streams and
  returns 1 — so a failed drawing never looks like a pass.
- An integer `SystemExit` passes through unchanged; `None` becomes 0.
- With no `--pass` and no script after it, the wrapper prints its usage line and
  exits 2.
- Inside FreeCAD the runner re-raises a failure as `guion failed: ...` with the
  traceback, so the asset is never recorded.

## The guion contract

The guion's argv is `<guion> <out_dir>/<name> <pieza>`: the script itself, the
output prefix, and the part file. `<name>` is the sanitized stem of the guion,
so `plano-escuadra.py` names the output `plano-escuadra`. The script writes
one SVG sheet per page at that prefix — `<name>-01.svg`, `<name>-02.svg`, …
with consecutive two-digit numbers from 01, each sheet carrying `width` and
`height` in millimetres on its `<svg>` tag — and the runner renders them into
`<name>.pdf` and `preview/page-NN.png` with FreeCAD's bundled Qt. A script
that writes no first sheet fails with `guion wrote no <name>-01.svg`; a gap
fails with `sheet <name>-NN.svg is missing`; a sheet without millimetre sizes
fails with `<file>: the sheet needs width and height in mm`. Paths arrive
runner-side and are resolved there: the guion and the part are resolved
relative to the piece before launch.

## Host lookup and paths

The host binary is found in this order: the `freecad.path` config value, then
the `FREECAD_EXE` environment variable, then the `freecadcmd` names on `PATH`.
When the binary is a Windows `.exe`, every slash-bearing argument is converted
with `wslpath -w` before launch, so a Windows FreeCAD can open a WSL path; a
native Linux build receives the paths unchanged.
