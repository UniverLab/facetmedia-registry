# Sources

The edge rules in `SKILL.md` rest on these public sources. Where a licence
allows it, at most one short line is quoted; everything else is a paraphrased
fact or practice.

| Source | URL | Maintainer | Licence | Taken |
|---|---|---|---|---|
| danielgatis/rembg README | https://github.com/danielgatis/rembg | Daniel Gatis | MIT (code) / Apache-2.0 (U-2-Net weights) | The three edge modes are alternatives, not layers: naive for hard edges, `-dc` decontamination for coloured halos, `-a` alpha matting for hair and fur. facet runs the naive mode only. Paraphrased. |
| image-remove-background SKILL.md | https://raw.githubusercontent.com/godot-fun/gai/HEAD/.agents/skills/image-remove-background/SKILL.md | godot-fun / gai | none stated | The model ladder by quality (`u2net` → `u2netp` → `isnet-general-use` → `birefnet-general`); the large-input guard past ~4096 px; flat solid backgrounds cut better with a chroma key. Facts only. |
| bg-remove SKILL.md | https://raw.githubusercontent.com/soejun/claude-code-development-kit/HEAD/skills/bg-remove/SKILL.md | soejun | none stated | Verify transparency on a coloured composite, and log corner-alpha values with the transparent-pixel share as the sanity record. Facts only; facet keeps `u2netp`, so its `birefnet-general` default is not taken. |
