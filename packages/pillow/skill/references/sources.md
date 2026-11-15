# Sources

The rules in `SKILL.md` rest on these public sources. Where a licence allows
it, at most one short line is quoted; everything else is a paraphrased fact or
practice.

| Source | URL | Maintainer | Licence | Taken |
|---|---|---|---|---|
| pillow-consistency SKILL.md | https://raw.githubusercontent.com/guidogl/pillow-consistency/HEAD/SKILL.md | guidogl | licence file present (`LICENSE.txt`), SPDX not stated | Pillow 10 names (`Image.Resampling.LANCZOS`, the `getbbox`/`textbbox` family); EXIF orientation is not applied on open; re-encoding degrades, so write once; `thumbnail()` mutates while `resize()` returns a new image; `save` infers the format from the suffix. Paraphrased. |
| image-processing SKILL.md | https://eliteai.tools/agent-skills/image-processing | jezweb / claude-skills, via the eliteai.tools directory | none stated | JPEG has no alpha, so flatten onto white; trim with `getbbox()` on an RGBA conversion before tiling. Facts only. |
