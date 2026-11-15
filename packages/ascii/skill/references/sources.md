# Sources

The sampling, viewing, and reproducibility habits in the skill come from
the public sources below, read on 2026-11-14. No ASCII-art-specific
agent skill exists in the searched collections, so the tool's own docs
plus two general art skills are the oracles. Every rule above is stated
in facet's own words.

| URL | Maintainer | Licence | Taken |
|-----|------------|---------|-------|
| https://github.com/pwaller/pyfiglet | Peter Waller and contributors | MIT | The habit of rendering every candidate font and comparing before choosing; the discipline that output should match real FIGlet byte for byte, so a mismatch is a bug signal; the fact that system font directories exist (facet does not expose them); the fact that some fonts were removed over unclear redistribution rights, which corroborates the skill's DOS Rebel warning. |
| https://github.com/cmatsuoka/figlet | Claudio Matsuoka | none stated (facts only, no wording taken) | The fact that the reference tree ships a font sampler for exactly this preview step; the fact that FIGlet output assumes a monospaced font. |
| https://raw.githubusercontent.com/anthropics/skills/main/skills/algorithmic-art/SKILL.md | Anthropic | Apache-2.0 (paraphrased, no wording taken) | The practice of pinning the generative inputs so a result reproduces, applied here as pinning `width` and `mode` beside committed art. |
| https://raw.githubusercontent.com/anthropics/skills/main/skills/canvas-design/SKILL.md | Anthropic | Apache-2.0 (paraphrased, no wording taken) | The loop of deciding the intended look first, then rendering, then comparing the render against the intent. |
