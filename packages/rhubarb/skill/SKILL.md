---
name: rhubarb
description: Mouth cues X..H for a drawn character, timed to a voice clip, with the phonetic recognizer of the pinned Rhubarb Lip Sync 1.14.0.
---
# rhubarb

`rhubarb.bocas` reads a voice WAV and the text it says, runs the pinned
Rhubarb Lip Sync 1.14.0 ELF with the phonetic recognizer, and writes
`bocas.json` with the `mouthCues` timeline a drawn character animates against.
One capability, one `text` asset.

## When to use

- A drawn character must speak: eight mouths and a fox, not a photoreal face.
  Photoreal human photo animation is rejected at the lab — the uncanny valley —
  so this is the lab's route to avatars.
- The voice exists and its text is known, in Spanish or English. With the text
  the phonetic recognizer aligns mouths to syllables instead of guessing.
- Not for the character assembly: mouths into an SVG/GSAP composition is
  `hyperframes`, its own package.

## Pieces

```toml
[inputs]
voz = "personaje/voz.wav"
dialogo = "personaje/dialogo.txt"
```

Both resolve relative to the piece. `dialogo` is the plain text of what the
voice says; it is passed to Rhubarb as `--dialogFile`. The run is exactly:

```bash
rhubarb -r phonetic -f json --dialogFile <texto> <voz.wav> -o bocas.json
```

`-r phonetic` is not optional. Rhubarb's default recognizer is English-only
(pocketSphinx), so a **Spanish** dialog without that flag gets English mouth
shapes that do not match the voice; the runner refuses such an argv and facet
reports `runner_failed`. The approved reference is a fox SVG, a 10.32 s
Spanish clip, 65 cues in its `bocas.json`.

### The mouth map

Port of the lab's table, one shape per Rhubarb letter:

| Letter | Mouth |
|--------|-------|
| `X` | rest |
| `A` | closed |
| `B` | teeth |
| `C` | open |
| `D` | wide |
| `E` | round |
| `F` | pursed |
| `G` | teeth on lip |
| `H` | tongue |

## Judging the result

`verify` reads `bocas.json`: it passes when it parses to at least one cue,
every `value` is one of `XABCDEFGH`, and the cues are in time order. Metrics:
`duration_s`, `cues`, `mouths` and `ordered`. `facet preview bocas.json` writes
the generic `bocas.json.preview.json` with a summary such as
`10.3 s · 65 mouth cues · 8 mouths (XABCEFGH)`. Read the cue list itself when
the mouths look wrong: a run of `A` under a vowel, or `X` while sound plays,
means the wrong recognizer or a `dialogo` that does not match the audio.

## Pitfalls

- The default recognizer is English-only: always `-r phonetic`, or the Spanish
  mouths will lie. The runner owns that flag; never build your own argv.
- `dialogo` must be what the voice actually says. A mismatched script makes the
  phonetic recognizer place mouths for words nobody spoke.
- Rhubarb resolves `-o` against its cwd, so the runner passes the job out dir
  absolute: the file lands there whatever cwd the run has. A relative `-o`
  combined with a changed cwd writes nowhere and dies with
  `basic_ios::clear: iostream error` after 100% progress.
- `facet pull rhubarb` downloads 87 MB (the zip) and the environment; pulls and
  runs are exclusive, so a queued run starts only when the previous finishes.
