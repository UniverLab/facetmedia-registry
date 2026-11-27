# Sources

The motion and composition rules in `SKILL.md` rest on these public sources.
Where a licence allows it, at most one short line is quoted; everything else
is a paraphrased fact or practice.

| Source | URL | Maintainer | Licence | Taken |
|---|---|---|---|---|
| svg-animations SKILL.md | https://www.typingmind.com/skills/epicenterhq-svg-animations | EpicenterHQ | none stated | `transform-origin` defaults to the viewBox origin; stroke-draw needs the measured path length in the dash values; a non-frozen end state snaps back; morphs interpolate only between paths with matching command lists. Facts only. |
| svg-illustration SKILL.md | https://codexskills.dev/skills/design/svg-illustration/ | codexskills.dev | MIT | Size with `viewBox`, keep reusable shapes in `<defs>`, avoid generic ids across a page; ~8 % margin and a grounding shadow; `prefers-reduced-motion` fallback and `<title>`/`<desc>` markup. Paraphrased. |
| HyperFrames (facet's own pipeline) | local: `packages/svganim` runner and `SKILL.md` | UniverLab | repository licence | The CSS-`@keyframes`-only rule: `verify` requires a `@keyframes` block and refuses `<script>` and `<text>`, and HyperFrames inlines the SVG, so SMIL is not used. |
| algorithmic-art SKILL.md | https://github.com/anthropics/skills/tree/main/skills/algorithmic-art | Anthropic | Apache-2.0 | Algorithmic philosophy before code, seeded deterministic PRNGs instead of `Math.random()`, and cohesive visual grammar. Paraphrased; No wording copied. |
| diagram-design | https://github.com/cathrynlavery/diagram-design | cathrynlavery | MIT | Flat crisp strokes, restrained single accent colour, and clear focal hierarchy. Paraphrased; No wording copied. |
