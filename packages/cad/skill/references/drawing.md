# Drawing practice for fabrication-grade DXF

These rules decide whether a DXF survives outside facet: a CAD program, a
print shop, a cutting machine. `verify` now enforces header units and fails
on undefined layer, linetype and text-style references collected before the
audit, in addition to the audit and expected layers. The guidance below
keeps drawings unambiguous and fabrication-ready beyond those checks.

## Layers carry machine intent

Draw one shape on one layer, and name layers for what a machine should do
with them: cutting geometry on a cut layer, fold or bend lines on a layer
whose name says so, human labels on a text layer. Never leave a dimension
or annotation on the cut layer — a machine cannot tell it apart from the
part, and it will cut it into the piece. Architectural plans use their own
layer families (walls, openings, furniture, dimensions, labels); the rule
is the same either way: the layer says what happens to what is on it.

## Machine-read text is outlines, human text is TEXT

Font rendering inside cutting software is unreliable, so anything a
machine reads (engraving, marking) goes down as outline geometry or
polyline strokes on a marking layer, not as a `TEXT` entity. Keep DXF
`TEXT` for human labels only, and always set the alignment point equal to
the insertion point: a missing alignment point is invisible in ezdxf tests
and shows up only when another program lays the text out differently.

## Profiles stay closed, entities stay unique

A cutting profile must be a closed loop — an open contour has no inside,
and it is the most common reason shops reject files. Close every cut
polyline, walk chained entities into loops, and report any gap with its
size and endpoints rather than silently bridging it. Delete duplicated
entities: two identical lines on top of each other cut twice and confuse
nesting.

## Frame the view in the file

Centre the model for whoever opens the DXF next (modelspace viewport set
to the drawing extents), even though facet renders its own PNG: downstream
programs open the file, not the preview.

## Match the entity set to the file version

Facet writes R2018, so lightweight polylines are the correct curve entity
and the older heavyweight form is wasteful. Never downgrade the file
version without changing the entity set to match, and never smuggle an
entity from a newer version into an older file.
