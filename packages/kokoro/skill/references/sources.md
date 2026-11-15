# Kokoro sources

One row per source the skill text relies on, with the URL, maintainer and
licence as the research report states them, and what was taken from it.

| Source | Maintainer | Licence | Taken |
| --- | --- | --- | --- |
| https://github.com/hexgrad/kokoro | hexgrad | Apache-2.0 (weights) | The fact that inline phoneme markup corrects names the G2P reads wrong. |
| https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md | hexgrad | Apache-2.0 (model card) | The facts behind the 100-200 token target, bundling shorts, splitting longs, reaching for speed on rushed utterances, and the top voice grades. |
| https://github.com/thewh1teagle/kokoro-onnx | thewh1teagle | MIT (code), Apache-2.0 (model) | The fact that this runtime with its espeak/misaki path is what facet wraps. |
| https://github.com/suqingliu/long-form-video-creation-skills/blob/HEAD/video-narration/SKILL.md | SuqingLiu | none stated (facts only, no wording taken) | The fact that symbol/unit normalisation belongs before synthesis rather than after verification. |
| https://github.com/mrlawrune/ai-plugins/blob/HEAD/plugins/kokoro-tts/skills/kokoro-tts/SKILL.md | MrLawrune | none stated (facts only, no wording taken) | The fact that smart quotes, dashes, emoji, arrows, identifiers and URLs need stripping or rewriting before synthesis. |
