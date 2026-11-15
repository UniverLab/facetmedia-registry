# Sources

The lint-first, triage, rerun, and readability habits in the skill come
from the public sources below, read on 2026-11-14. The tool's own repo
and its installed skill are the contract; the rest supply transferable
verification habits. Every rule above is stated in facet's own words,
with one exception: the single short quoted line noted below, from a
MIT-licensed source.

| URL | Maintainer | Licence | Taken |
|-----|------------|---------|-------|
| https://github.com/UniverLab/texforge | UniverLab | MIT | The lint-before-compiling workflow; the fact that scripted runners must not invoke the interactive setup nor hand-write the generated project file. |
| Installed skill at `~/.claude/skills/texforge/SKILL.md` (v1.7) | jheison.martinez | MIT | The full command reference the skill summarizes; the practice of triaging from the first error; the special-character escaping facts; the PDF text/info/check acceptance probes. |
| https://tectonic-typesetting.github.io/en-US/ | Tectonic project | MIT | The fact that the engine re-loops TeX and BibTeX until the document is fully processed — "always produces a fully-processed document." — so agents must not add manual recompile passes. |
| https://github.com/tectonic-typesetting/tectonic | Tectonic project | MIT | The fact that the build needs no intermediate files and reruns as needed, which is why agents never parse them. |
| https://www.overleaf.com/learn/latex/Learn_LaTeX_in_30_minutes | Overleaf | none stated (facts only, no wording taken) | The facts of the preamble/body split and the content-vs-style separation behind the template gallery. |
| https://en.wikibooks.org/wiki/LaTeX/Errors_and_Warnings | Wikibooks contributors | none stated (facts only, no wording taken) | The facts of the `!`-led error format with line numbers and the common failure causes behind the fix-error-#1 rule. |
| https://raw.githubusercontent.com/anthropics/skills/main/skills/pdf/SKILL.md | Anthropic | Apache-2.0 (paraphrased, no wording taken) | The practice of verifying a PDF the way a reader will — extracting text and confirming embedded fonts and metadata — applied here as agent-side acceptance. |
