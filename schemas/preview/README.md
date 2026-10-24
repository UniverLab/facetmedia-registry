# Preview schemas

One **JSON Schema per asset kind**, describing the `<asset>.preview.json`
file a package's `preview` verb writes beside its asset. The file is named
after the kind: `schemas/preview/<kind>.schema.json`, where `<kind>` is the
kind (`audio`, `text`, `cad`, ...), and it validates one preview file of that
kind — the same kind facet uses to pick the schema and the
[viewer](../viewers/README.md).

The preview file is a small JSON object: `kind` (the asset's kind),
`preview` (the schema version), plus kind-specific fields — for example a
`text` preview carries a `summary` and a `chars` count, an `audio` preview
the duration and a waveform. The image paths a preview lists are only ever
files beside the asset.

**This directory is filled by the next spec.** A package whose capability
writes a kind that has no schema here must add `schemas/preview/<kind>.schema.json`
and `viewers/<kind>/` in the same change as the package itself
(entry criterion 7 in the root [README](../../README.md)).
