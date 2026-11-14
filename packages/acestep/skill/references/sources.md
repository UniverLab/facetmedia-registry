# acestep sources

One row per source the skill text relies on, with the URL, maintainer and
licence as the research report states them, and what was taken from it.
Where a licence is not stated, only facts were taken and no wording.

| Source | Maintainer | Licence | Taken |
| --- | --- | --- | --- |
| https://github.com/ace-step/ACE-Step-1.5 | ace-step | MIT (stated on the model card; the repo text carries no licence banner) | The official code and its API/CLI docs, which the parameter ranges and the server behaviour in the skill rest on. |
| https://raw.githubusercontent.com/ace-step/ACE-Step-1.5/main/docs/en/API.md | ace-step | MIT | The facts that `bpm` runs 30-300, `key_scale` reads like `C Major`, `time_signature` takes 2, 3, 4 or 6, `audio_duration` runs 10-600 s, turbo `inference_steps` 1-20 with 8 recommended, base 1-200 with 32-64 recommended, `guidance_scale` is effective for the base model only, `thinking = false` stops the LM writing audio codes but not the CoT caption pass, and a missing metadata field may be filled by the LM from the caption, with explicit values winning. |
| https://huggingface.co/ACE-Step/Ace-Step1.5 | ACE-Step | MIT | The turbo / SFT / base trade-offs behind pinning turbo at 8 steps and leaving 32-64 steps plus guidance to base and SFT. |
| https://raw.githubusercontent.com/ace-step/awesome-ace-step/main/README.md | ace-step community | none stated (facts only, no wording taken) | The model table showing turbo checkpoints want about 8 steps and ignore guidance, while base and SFT checkpoints use 32-64 steps with it. |
| https://www.ambienceai.com/tutorials/ace-step-music-prompting-guide | Ambience AI | none stated (facts only, no wording taken) | The tag order genre to instruments to mood to tempo, 3-7 comma-separated tags beating a vague sentence, naming the tempo in the caption text, and the rule against contradictory tags with one primary genre plus one influence for a fusion. |
| https://raw.githubusercontent.com/prime-skills/runcomfy-agent-skills/main/ace-step/SKILL.md | RunComfy (prime-skills) | MIT | The seed discipline (fix a seed to reproduce, vary it to explore) and the practice of stating the tempo in the caption rather than only in the numeric field. |
| https://raw.githubusercontent.com/schwepps/skills/main/suno-music-creator/references/metatags.md | schwepps | MIT | Front-loading the control tokens, keeping a style prompt to one or two genres plus one mood, and writing exclusions as negatives. |
