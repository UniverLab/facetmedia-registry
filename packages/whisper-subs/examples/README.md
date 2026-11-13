# The example files in this folder

- `lab-segments.json` is authored for this example: a whisper sidecar with
  three timed segments, in the exact shape `whisper.transcribe` writes as
  `<name>.json`.
- `subtitles.toml` is the piece; it exports the sidecar as VTT, the format
  whisper does not write.
