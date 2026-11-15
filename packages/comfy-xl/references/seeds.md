# Seeds

Every flow's `params` carries `"seed": 0`; every piece entry carries its own
required integer `seed`. The fill order is params first, then the entry, so
the entry's seed always wins — a piece that omits `seed` cannot exist, the
field is `required = true` on every capability.

The seed lands on the sampler's noise input (`KSampler.seed`,
`KSamplerAdvanced.noise_seed` or `RandomNoise.noise_seed`, whichever the flow
uses), so the same
seed, prompt and inputs give the same output: same seed and prompt give the
same image; same seed, prompt and reference give the same edit; same seed,
prompt and first frame give the same clip.

Seeds are part of the result: change only the prompt to explore variations,
then keep the seed of the output you approved.
