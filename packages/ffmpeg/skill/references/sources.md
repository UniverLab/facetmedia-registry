# ffmpeg sources

One row per source the skill text relies on, with the URL, maintainer and
licence as the research report states them, and what was taken from it.
Where a licence is not stated, only facts were taken and no wording.

| Source | Maintainer | Licence | Taken |
| --- | --- | --- | --- |
| https://ffmpeg.org/ffmpeg-filters.html | FFmpeg project | none stated (facts only, no wording taken) | The `loudnorm` facts behind the two-pass design: single-pass and double-pass modes, the integrated-loudness, loudness-range and true-peak parameters, and that linear mode needs the values a first pass measured. |
| https://raw.githubusercontent.com/kajisho5/ffmpeg-skill/main/skills/ffmpeg-skill/SKILL.md | kajisho5 | none stated (facts only, no wording taken) | The workflow discipline: plan and probe before running, keep loudness last in the chain, normalise before a lossy encode, and judge the result from measurements rather than from the command. |
| https://raw.githubusercontent.com/kajisho5/ffmpeg-skill/main/scripts/loudness.py | kajisho5 | none stated (facts only, no wording taken) | The destination targets (-14 streaming, -23 EBU, -24 Japanese broadcast) and the 1.0 LU on-target tolerance. |
| https://raw.githubusercontent.com/kajisho5/ffmpeg-skill/main/references/gotchas.md | kajisho5 | none stated (facts only, no wording taken) | The two rules that normalised audio can still clip so the true peak is read after the gain change, and that deep ambience must never be raised to a speech target. |
| https://en.wikipedia.org/wiki/EBU_R_128 | Wikipedia contributors | CC BY-SA | The -23 LUFS/LK broadcast target, its ITU-R BS.1770 basis, and the LU and LRA units the targets are stated in. |
| https://www.skills.sh/sonilo-ai/skills/audio-ducking | sonilo.ai | none stated (facts only, no wording taken) | The fact that ducking a bed under a voice is standard practice, which the -12 dB house value is defended against; no parameter values were taken. |
