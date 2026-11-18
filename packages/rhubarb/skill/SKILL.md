---
name: rhubarb
description: Mouth cues X..H for a drawn character, timed to a voice clip, with the phonetic recognizer of the pinned Rhubarb Lip Sync 1.14.0.
---
# rhubarb

`rhubarb.mouths` reads a voice WAV and the text it says, runs the pinned
Rhubarb Lip Sync 1.14.0 ELF with the phonetic recognizer, and writes
`mouths.json` with the `mouthCues` timeline a drawn character animates against.
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
voice = "character/voice.wav"
dialogue = "character/dialogue.txt"
```

Both resolve relative to the piece. `dialogue` is the plain text of what the
voice says; it is passed to Rhubarb as `--dialogFile`. The file biases
recognition toward the words it contains, and Rhubarb ignores it where the audio
audibly says something else, so a transcript that is close but not
word-perfect still helps: write what is spoken as well as you can rather than
leaving the file out. The run is exactly:

```bash
rhubarb -r phonetic -f json --dialogFile <dialogue> <voice.wav> -o mouths.json
```

`-r phonetic` is not optional, and there is no input that chooses another
recognizer: the runner owns every flag and refuses any other argv, and facet
reports `runner_failed` when one is asked for. Rhubarb's default recognizer is
English-only (pocketSphinx) and the more precise of the two on English dialogue;
phonetic is the newer path, built for non-English audio and described upstream
as usually less precise. facet keeps phonetic for every run because the lab's
reference is Spanish-first, where English-tuned mouths would lie on the audio.
A **Spanish** dialog run through the default recognizer is exactly the failure
that rule prevents. The approved reference is a fox SVG, a 1.5 s English clip,
10 cues in its `mouths.json`.

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

## Reading the output

`mouths.json` is a cue list, and its shape carries facts worth checking before
a character animates against it:

- The first cue starts at 0.00 on a closed mouth; a lead-in silence is not
  something Rhubarb produces.
- The last cue's end timestamp is the recording's end, so the cue span matches
  the voice's duration.
- Cue boundaries are contiguous: each cue ends exactly where the next starts,
  with no gap and no overlap.
- The letters are the eight shapes above. Upstream can leave out the extended
  ones (G, H, X) for simpler art, but facet does not: the character needs one
  `.mouth` shape per letter, `mouth-X` … `mouth-H`. The Preston Blair names
  Rhubarb can export are a display mapping, never a change to which shapes the
  recognition picks.
- Keep rest and closed visibly different in the art (X relaxed, A pressed): the
  animation rules assume the documented drawings, including the in-between
  shapes Rhubarb inserts between distant poses.

## Judging the result

`verify` reads `mouths.json`: it passes when it parses to at least one cue,
every `value` is one of `XABCDEFGH`, the first cue starts at 0, cue starts
are strictly increasing, and the last cue ends at the input voice's measured
duration within 0.01 s, so a cue file made from another clip fails. Metrics:
`duration_s`, `cues`, `mouths`, `ordered` and `voice_s`. `facet preview mouths.json` writes
the generic `mouths.json.preview.json` with a summary such as
`1.5 s · 10 mouth cues · 6 mouths (BCDEGX)`. Read the cue list itself when
the mouths look wrong: a run of `A` under a vowel, or `X` while sound plays,
means the wrong recognizer or a `dialogue` that does not match the audio.

## Pitfalls

- The default recognizer is English-only, and facet has no input that selects
  it: every run is `-r phonetic`, which is right for the lab's Spanish-first
  reference and usually less precise on English. The runner owns that
  flag; never build your own argv.
- `dialogue` should be what the voice actually says. A script about other words
  makes the phonetic recognizer place mouths for words nobody spoke, though a
  near match still helps more than no file at all.
- Input is WAVE or Ogg Vorbis only. An mp3, m4a or flac voice fails after the
  run starts, so convert it to WAV first with the ffmpeg package and hand that
  file to `voice`.
- Rhubarb resolves `-o` against its cwd, so the runner passes the job out dir
  absolute: the file lands there whatever cwd the run has. A relative `-o`
  combined with a changed cwd writes nowhere and dies with
  `basic_ios::clear: iostream error` after 100% progress.
- `facet pull rhubarb` downloads 87 MB (the zip) and the environment; pulls and
  runs are exclusive, so a queued run starts only when the previous finishes.

Sources: `references/sources.md` lists the public sources the skill relies on,
with their maintainer, licence and what was taken from them.
