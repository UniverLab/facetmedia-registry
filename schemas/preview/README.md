# Preview schemas

One **JSON Schema per asset kind** (draft 2020-12, `additionalProperties: false`
everywhere, no `$ref`), describing the `<asset>.preview.json` file a package's
`preview` verb writes beside its asset. The file is named after the kind:
`schemas/preview/<kind>.schema.json`, where `<kind>` is the kind a capability
declares (`audio`, `cad`, ...) — the same kind names the
[viewer](../../viewers/README.md). Each schema describes one preview file of
that kind; a package whose preview does not match it is a review blocker.
`generic.schema.json` is the fallback for kinds without their own schema,
including `text`.

A field is added only when a viewer or an agent uses it.

`scripts/check-previews.py` validates every example in `examples/` against its
schema (each `*.invalid.json` must fail, and an example with no schema of its
own fails the check); package specs reuse it on the preview files their
runners write.

## Common fields

- `preview`: format version, always `1`.
- `kind`: asset kind (`audio` / `cad` const; generic matches `^[a-z][a-z0-9-]*$`).
- `summary`: one line for an agent, at most 160 chars.

## Generic fields

- `fields`: object of scalar values (string, number, boolean or null).

## Audio fields

- `duration_s`: audio duration in seconds, > 0.
- `sample_rate_hz`: sample rate in hertz, integer > 0.
- `channels`: channel count, integer > 0.
- `waveform.bins`: peak bin count, always 1200.
- `waveform.min`: per-bin minimum peak, 1200 floats in [-1, 1].
- `waveform.max`: per-bin maximum peak, 1200 floats in [-1, 1].
- `loudness.integrated_lufs`: integrated loudness in LUFS.
- `loudness.peak_dbfs`: true peak in dBFS.
- `loudness.target_lufs`: normalisation target in LUFS, null when not normalised.
- `loudness.momentary.step_s`: momentary step in seconds, always 0.1.
- `loudness.momentary.window_s`: momentary window in seconds, always 0.4.
- `loudness.momentary.lufs`: momentary loudness in LUFS, null for silent windows below -70 LUFS.
- `silences`: stretches longer than 1 s below -50 dBFS.
- `silences[].start_s`: silence start in seconds, >= 0.
- `silences[].end_s`: silence end in seconds, >= 0.
- `clipped_samples`: samples at or above -0.1 dBFS, integer >= 0.
- `speech`: narration speech data, optional, for narration assets.
- `speech.text`: reference narration text.
- `speech.transcript`: recognised transcript of the narration.
- `speech.wer`: word error rate of the transcript, 0 to 1.
- `speech.alignment`: word alignment from the WER computation.
- `speech.alignment[].ref`: reference word, null for insertions.
- `speech.alignment[].hyp`: hypothesis word, null for deletions.
- `speech.alignment[].op`: alignment operation, one of `ok`, `sub`, `del`, `ins`.

## CAD fields

- `solid`: solid data, optional, when the asset has a solid.
- `solid.valid`: whether the solid is valid.
- `solid.volume_mm3`: solid volume in cubic millimetres, >= 0.
- `solid.bbox_mm`: bounding box [x, y, z] in millimetres.
- `solid.faces`: face count, integer >= 0.
- `solid.solids`: solid count, integer >= 0.
- `solid.holes`: cylindrical faces, deduplicated by axis and centre.
- `solid.holes[].center_mm`: hole centre [x, y, z] in millimetres.
- `solid.holes[].diameter_mm`: hole diameter in millimetres, > 0.
- `solid.holes[].axis`: hole axis vector.
- `drawing`: drawing data, optional, when the asset has a drawing.
- `drawing.units`: drawing units.
- `drawing.entities`: entity count, integer >= 0.
- `drawing.layers`: per-layer entity counts.
- `drawing.layers[].name`: layer name.
- `drawing.layers[].entities`: entity count on this layer, integer >= 0.
- `drawing.audit`: drawing audit result.
- `drawing.audit.errors`: audit error count, integer >= 0.
- `drawing.audit.fixes`: audit fix count, integer >= 0.
- `views`: rendered views beside the asset, at least one.
- `views[].file`: view file beside the asset (PNG/SVG).
- `views[].label`: view label.
