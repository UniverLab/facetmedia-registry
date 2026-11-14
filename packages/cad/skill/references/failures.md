# Kernel failure catalogue

The OpenCASCADE kernel fails with short, cryptic errors. Each row below is
one signature the lab has seen (or that public guides document with a
working fix): match the row first, apply the one-line repair, and only
restructure the script when no row matches.

| Signature | What it means | Fix |
|---|---|---|
| `StdFail_NotDone` on a `fillet` after a boolean | A broad selector caught small edges the boolean created | Move the fillet onto the primitives before the boolean; after a boolean, round only by explicit point (`NearestToPointSelector`) |
| `StdFail_NotDone` on a `chamfer` | Same family: the selector spans edges of different character | Narrow the selector to the intended edges only |
| Null shape / null topology after an operation | An operation consumed geometry that was not there (empty selector, fully consumed cutter) | Check the selector matched exactly the intended faces or edges before the operation |
| Unclosed wire rejected by `extrude` | The profile never closed | Call `.close()` on the profile before extruding |
| Wrong region kept after cutting on touching faces | A boolean on coincident or near-tangent boundaries succeeded with the wrong side while `isValid()` still passes | Offset the cutter by about 0.01 mm (or 0.001 mm for fine work) so the overlap is unambiguous, then re-check volume and bbox |
| Bounding box suddenly huge (×25.4 or ×1000) | A unit mix-up: inches read as millimetres, or metres read as millimetres | Divide the offending dimensions by 25.4 (inches) or 1000 (metres) |
| Feature floats apart from the body on an XZ-based part | An `XZ` workplane extrudes toward −Y | Flip the sign of the extrusion distance |
| Exported `.stp` file is empty or missing | The short extension silently exports nothing | Save as `.step` (or pass the format explicitly) |
| Script hangs with no output | A viewer call (`show()`) waits for a display that does not exist | Gate viewer imports behind an environment flag so headless runs skip them |
| Selector silently builds the wrong shape | A selector matched nothing or too much and the script carried on | Prefer `.tag()` / workplanes from tags for feature-relative placement; keep holes in absolute coordinates |

Two habits make the catalogue pay off. First, treat every warning as
blocking: a `disconnected_bodies` notice means a stray second solid is in
the part, so delete it rather than reasoning about whether it matters.
Second, after any boolean on touching geometry, confirm the result with
numbers — the bbox should sit inside the operands and the volume should sit
near its expected value — before building further features on top of it.
