# The example files in this folder

- `plan.toml` is authored for this example: it asks the package for the
  `explainer-video` plan. The plan names capability ids and handoffs; it
  references no local file.
- `status.toml` inspects `explainer-video.plan.json` and reports which
  steps are done, missing or stale in the folder beside the plan.
- `explainer-video.plan.json` is the plan the status example inspects.
