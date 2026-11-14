# Sources

Every habit the skill's authoring section teaches comes from one of these
public pages, read on 2026-11-14. Each row names the page, who maintains it, the
licence the research recorded, and what facet took from it. Nothing is quoted:
where the licence is not stated, only facts were taken, and everywhere else the
practice is written in facet's own words for this package.

| URL | Maintainer | Licence | Taken |
|-----|------------|---------|-------|
| https://hyperframes.heygen.com/guides/gsap-animation.md | HeyGen (HyperFrames docs) | none stated — facts only | Font loading before measuring text; building tweens after the load resolves and registering the timeline last; `fromTo` with an explicit position; transforms and opacity only; media timed by attributes with a wrapper element for movement; the three-point snapshot habit. |
| https://hyperframes.heygen.com/concepts/determinism.md | HeyGen (HyperFrames docs) | none stated — facts only | The determinism checklist: no wall clock, no unseeded randomness, no mid-render fetch, frame size and rate locked before frame 0, finite length. |
| https://hyperframes.heygen.com/concepts/frame-adapters.md | HeyGen (HyperFrames docs) | none stated — facts only | Seeks may arrive in any order and repeats must return identical state; the note that the seek contract is shared with other runtimes, which is why facet states its GSAP-only scope. |
| https://hyperframes.heygen.com/reference/lint-rules.md | HeyGen (HyperFrames docs) | none stated — facts only | Clip anatomy `check` enforces: a nested clip's `data-start` counts from the composition start, clips end at or before the root `data-duration`, one `data-composition-id` per file, `data-end`/`data-layer` are legacy, asset paths stay inside the project, caption rows on one track with one index. |
| https://hyperframes.heygen.com/prompting/motion.md | HeyGen (HyperFrames docs) | none stated — facts only | Motion craft: landed elements hold still, staggered entrances, one idea per move, overshoot only on physical objects, paced beats, caused transitions at about 0.4 s with three to five kinds per piece, holds counted in frames, seeded randomness. |
| https://hyperframes.heygen.com/prompting/examples.md | HeyGen (HyperFrames docs) | none stated — facts only | Brief structure: a shared preamble of standing motion rules plus exactly one named spectacle beat per piece. |
| https://hyperframes.heygen.com/prompting/media-and-audio.md | HeyGen (HyperFrames docs) | none stated — facts only | The voice as the clock: reveals land on word-level timestamps and the narration never waits for a visual; name the loudness relation with music instead of asking for a bare music bed. |
