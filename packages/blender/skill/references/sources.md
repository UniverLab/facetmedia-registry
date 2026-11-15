# Sources

The writing rules in `SKILL.md` rest on these public sources. None of them
states a licence (as observed in November 2026), so only facts were taken from
them: no wording is copied, and no line is quoted.

| Source | URL | Maintainer | Licence | Taken |
|---|---|---|---|---|
| blender SKILL.md (agent-skills) | https://raw.githubusercontent.com/libevm/agent-skills/HEAD/skills/blender/SKILL.md | libevm (community) | none stated | The data-API-over-`bpy.ops` rule, the fragility of operator context headless, and the version-tolerant call habit. Facts only. |
| blender-python SKILL.md (animationstudio) | https://raw.githubusercontent.com/sangal4/animationstudio/HEAD/.agents/skills/blender-python/SKILL.md | Sangal4 / animationstudio | none stated | Validate with `bpy.data.objects.get` and fail loudly on `None`; no modal operators; no reliance on selection or active object; deterministic cleanup and orphan purge; no hardcoded absolute paths. Facts only. |
| blender-headless SKILL.md (digz-skills-arsenal) | https://raw.githubusercontent.com/mojowebs/digz-skills-arsenal/HEAD/blender-headless/SKILL.md | mojowebs (community) | none stated | Pass parameters after `--` and parse only what follows; clean the startup scene deterministically. Facts only. |
| capybala-bpy-skill (README and SKILL.md) | https://github.com/capybala18/capybala-bpy-skill/blob/HEAD/README.md | capybala18 (Capybala) | none stated | Plan → build → self-review; measure render statistics inside the script with numpy; auto-frame from the subject's bounding box and derate light energies to scene scale; presets are a pattern to recalibrate. Facts only. |
| Qwen-MM-Plugins README | https://github.com/qwenlm/qwen-mm-plugins/blob/HEAD/README.md | QwenLM (Alibaba) | none stated | Context only: the upstream collection ships a Blender plugin. No Blender-specific tip was taken. |
