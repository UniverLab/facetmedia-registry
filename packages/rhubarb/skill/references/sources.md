# Sources

The recognizer rule, the dialogue guidance and the cue-list facts come from
Rhubarb Lip Sync's own project pages, read on 2026-11-14. No public agent skill
for Rhubarb exists in any searched collection, so these two are the sources.
Both are MIT, so a short line could have been quoted; nothing is: every rule
below is stated in facet's own words.

| URL | Maintainer | Licence | Taken |
|-----|------------|---------|-------|
| https://github.com/DanielSWolf/rhubarb-lip-sync | Daniel Wolf | MIT | Usage and flags; the recognizer split (the default suits English and is the more precise of the two, phonetic suits non-English and is usually less precise); dialogue text biases recognition and is ignored where the audio differs; WAVE and Ogg Vorbis as the only accepted inputs; mouth shapes and the drawings the animation rules assume; dropping the extended shapes; the Preston Blair export mapping; TSV/JSON/XML cue-list invariants (first cue at 0.00 and closed, last cue stamps the recording end, contiguous boundaries); batch and logging flags owned by the runner. |
| https://github.com/DanielSWolf/rhubarb-lip-sync/releases | Daniel Wolf | MIT | Release history: phonetic recognition was added after the original English-default recognizer, which is why it is the newer and less precise path. |
