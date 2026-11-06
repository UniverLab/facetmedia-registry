# Seeds

Every flow's `params` carries `"seed": 0`; every piece entry carries its own
required integer `seed`. The fill order is params first, then the entry, so
the entry's seed always wins — a piece that omits `seed` cannot exist, the
field is `required = true` on every capability.

The seed lands on the sampler's noise input (`RandomNoise.noise_seed` on the
klein still and edit flows, the sampler's `seed` on z-image-turbo and the
Wan flows), so the same seed,
prompt and inputs give the same output: same seed and prompt give the same
image; same seed, prompt and reference give the same edit; same seed,
prompt and first frame give the same clip.

Seeds are part of the result: change only the prompt to explore variations,
then keep the seed of the output you approved. The lab's approved pieces
seed their entries 11–14 (still comparisons), 242 (the img2img iteration)
and 51–53 (the three clips).
