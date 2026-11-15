# Sources

The prompting rules in `SKILL.md` rest on these public sources. Where a
licence allows it, at most one short line is quoted; everything else is a
paraphrased fact or practice.

| Source | URL | Maintainer | Licence | Taken |
|---|---|---|---|---|
| flux-image-best-practices SKILL.md | https://raw.githubusercontent.com/black-forest-labs/skills/HEAD/skills/flux-image-best-practices/SKILL.md | Black Forest Labs | MIT | Subject-first prompt order and the weight of lighting; the typography advice that facet deliberately does not follow. Paraphrased. |
| Flux 2 klein Prompt Guide | https://fal.ai/learn/devs/flux-2-klein-prompt-guide | fal.ai | none stated (site copyright) | Prompt hierarchy for the klein family: subject first, then style and context. Facts only, no wording. |
| Z-Image Turbo prompts and settings | https://stableyogi.com/blog/z-image-turbo-prompts-and-settings | StableYogi (community blog) | none stated | Positive-only phrasing (write "show Y", not "avoid X"), one named light and lens, three seeds, one dial per run. Facts only. |
| qwen-image-edit SKILL.md | https://raw.githubusercontent.com/ethanfel/comfyui-mcp/HEAD/plugin/skills/qwen-image-edit/SKILL.md | ethanfel / comfyui-mcp | none stated | Edit graphs inherit their geometry from the source, so an own-flow edit must derive its latent from the scaled source. Facts only. |
| Qwen Image Edit guide | https://pict.ai/models/qwen-image-edit | Pict.ai | none stated | The target / change / preservation pattern, one operation per run, restart from the original after drift. Facts only; the example was rewritten in facet's own terms. |
| Wan2.2-TI2V-5B-iOS model card | https://huggingface.co/jc-builds/Wan2.2-TI2V-5B-iOS | jc-builds (community) | Apache-2.0 (bundle badge) | 4n+1 frames; stay on trained geometry; motion-first prompting. Paraphrased. |
| Wan 2.2 Prompting Guide | https://www.veed.io/learn/wan-2-2-prompting-guide | VEED | none stated | The four-part image-to-video framework, the negative strategy, and the failure of multi-subject choreography. Facts only. |
| comfyui SKILL.md | https://raw.githubusercontent.com/lorenzotumini/dotfiles/HEAD/dot_pi/agent/skills/comfyui/SKILL.md | lorenzotumini (personal dotfiles) | none stated | Validate node schemas with `/object_info`, match IMAGE and MASK dtypes across links, and keep a save or preview sink on the terminal node. Facts only. |
