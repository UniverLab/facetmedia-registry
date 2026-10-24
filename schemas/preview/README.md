# Preview schemas

One **JSON Schema per asset kind**, describing the `<asset>.preview.json` file
a package's `preview` verb writes beside its asset. The file is named after the
kind: `schemas/preview/<kind>.schema.json`, where `<kind>` is the kind a
capability declares (`audio`, `text`, `cad`, ...) — the same kind names the
[viewer](../../viewers/README.md). Each schema describes one preview file of
that kind; a package whose preview does not match it is a review blocker.

The preview file is a small JSON object: `kind` (the asset's kind), `preview`
(the format version, `1`), plus kind-specific fields — for example a `text`
preview carries a `summary` and a `chars` count. The image paths a preview
lists are only ever files beside the asset.

**This directory is filled by the next spec.** A package whose capability
writes a kind that has no schema here must add `schemas/preview/<kind>.schema.json`
and `viewers/<kind>/` in the same change as the package itself
(entry criterion 7 in the root [README](../../README.md)).
