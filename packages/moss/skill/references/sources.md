# moss sources

One row per source the skill text relies on, with the URL, maintainer and
licence as the research report states them, and what was taken from it.
Where a licence is not stated, only facts were taken and no wording.

| Source | Maintainer | Licence | Taken |
| --- | --- | --- | --- |
| https://github.com/OpenMOSS/MOSS-TTS | OpenMOSS | Apache-2.0 (per `package.toml`; no SPDX line in the fetched repo text) | The official family repo: v2.0 replaced discrete-token autoregression with a DiT plus flow matching, the roughly 40 s per effect cost curve, and the isolated Python 3.12 environment the package pins. |
| https://huggingface.co/OpenMOSS-Team/MOSS-SoundEffect-v2.0 | OpenMOSS Team | none stated (facts only, no wording taken) | The recommended `num_inference_steps = 100`, `cfg_scale = 4.0` and `sigma_shift = 5.0`, `seconds` up to 30, bilingual English/Chinese prompts, the duration tag prepended at training time, and the five sound families with short musical and percussive clips the weakest. |
| https://raw.githubusercontent.com/OpenMOSS/MOSS-TTS/main/moss_soundeffect_v2/README.md | OpenMOSS | Apache-2.0 (per `package.toml`; no SPDX line in the fetched text) | The `torch.compile` plus Triton CUDA-graph wrap, the minutes-long first call after a deploy, and `TORCHDYNAMO_DISABLE=1` as the fix for a compile error rather than a model failure. |
| https://raw.githubusercontent.com/OpenMOSS/MOSS-TTS/main/docs/moss_sound_effect_model_card.md | OpenMOSS | Apache-2.0 (per `package.toml`; not stated in the fetched card) | The natural / urban / animals and creatures / human actions / short musical taxonomy the descriptions are organised by, and the practice of naming the material together with the action in one scene. |
