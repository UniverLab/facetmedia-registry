# The minimal TechDraw script shape

Build a document-based drawing script from the same skeleton so drawings
come out reproducible instead of improvised. The wrapper contract
(invocation, arguments, exit behaviour) stays in references/wrapper.md;
this file is the drawing half. The bundled `examples/bracket-plan.py` is
the lighter route — `TechDraw.project`/`projectToSVG` straight onto a
hand-laid sheet, no document — for sheets that carry views only; reach for
the skeleton below when a sheet carries dimensions or standard furniture.

## Page plus template plus projection group

Each sheet is a drawing page backed by a pinned SVG template file, with a
projection group carrying the standard views: front, top, side and an
isometric, in third-angle projection. Set the scale explicitly — automatic
fit when the sheet must fill, a fixed scale (for example 0.5) when the
drawing must stay comparable across revisions — and say which, so the next
reader knows whether the views may drift. Toggle hidden lines deliberately:
silhouette edges that are both visible and hidden stay on the visible
style, and tangent transitions that show no real edge (fillet runouts,
cylinder seams) are left undrawn rather than faked.

## Open, check, recompute, then draw

A document-based script either opens a supplied STEP part or, less often,
builds geometry in a PartDesign body. Either way the order is fixed:

1. Open (or build) the part.
2. Sanity-check it before projecting: the units should read as millimetres
   (compare the bounding box against the part's real size — an import that
   arrives in metres draws a room where a bracket should be), the solid
   must be non-empty and valid, and a STEP round trip should preserve its
   mass on parts that matter.
3. Recompute the document so every downstream feature sees the current
   shape.
4. Only then create pages, views and dimensions.

A script that builds PartDesign geometry (rather than opening a part) keeps
its sketches fully constrained, names constraints instead of counting
them, refers to model faces through stable named references, and drives
sizes from a parameter table — the same parameters-block discipline as the
`cad` skill, so one edit in one place reshapes the part.

## Deterministic output

Write no timestamp into the drawing so identical inputs rebuild byte-
identical files; a diff between two runs should mean the model changed,
not the clock. Keep the template path pinned (a fixed file beside the
script, not a version-dependent default) so the sheet furniture cannot
shift under a drawing that did not change.
