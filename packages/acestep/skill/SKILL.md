---
name: acestep
description: Instrumental background beds from an English caption with ACE-Step 1.5, at most 30 s, checked by duration and peak.
---
# ACE-Step 1.5

Compose an instrumental bed from one English caption with ACE-Step 1.5 (**MIT**,
commercial use allowed). The bed sits under narration, so it is always
instrumental: a caption that asks for voice is refused, and the lab discarded
sung music forever.

## When to use

- `acestep.bed` for a background bed under narration: one acoustic style
  named in English, at most 30 s per piece. About 50 s to render a 30 s
  track on the reference GPU.
- Ask for acoustic instruments and end the caption with `No drums, no
  percussion, no bass beat, no synthesizers`: without that guidance the
  model loads bass and kick, and about 60 % of the energy lands below
  120 Hz.
- Never for sung music. The lab discarded sung music forever: only ambience
  and emotional filler. The runner refuses a caption naming a voice, vocal,
  vocalist, sing, singer, singing, sung, choir, lyrics, rap, chant or speech.

## Pieces

One bed per piece: a `caption`, a `name` and a `duration` in seconds, with
optional `seed`, `steps`, `guidance`, `bpm`, `key` and `time-signature`.

```toml
[inputs]
caption = "Lively, joyful Baroque chamber orchestra piece in the style of a Vivaldi allegro. Bright strings playing fast staccato and spiccato runs, harpsichord continuo, playful solo violin and flute melodies. Energetic, festive and elegant. Acoustic instruments only. No drums, no percussion, no bass beat, no synthesizers, no electronic sounds."
name = "baroque-allegro"
duration = 30
```

`name` matches `[a-z0-9][a-z0-9-]*` and writes `<name>.wav` beside the piece.
`duration` is at most 30.

A bed is reproducible from its `seed`: the same seed regenerates the same
bed. `seed` defaults to 0 and is always sent with `use_random_seed = false`;
`steps` defaults to 8 and `guidance` to 7.0. `bpm` (30 to 300), `key` (sent
as `key_scale`, for example `C major`) and `time-signature` (one of `2/4`,
`3/4`, `4/4`, `6/8`; sent as `time_signature` as its beats-per-bar number) are
unset by default, and an unset one sends nothing: the server decides, keeping
its own default or reading a value out of the caption.

Both approved pieces ship as examples, each with its WAV:
`examples/baroque-allegro.toml` (major, Vivaldi-style allegro) and
`examples/romantic-nocturne.toml` (minor, solo piano and string quartet).
Their captions, and the piece shape above, are in
[references/captions.md](references/captions.md).

## Writing the caption

The caption is a tag list, not a sentence: lead with the genre, then the
instruments, then the mood, then the tempo, 3 to 7 comma-separated units in
that order. Front-load the words that carry the control, keep to one or two
genres plus one mood, and turn exclusions into negatives at the end where
the no-drums line already sits (`no guitars`, `no harsh distortion`). Never
write a `no vocals` tag: `vocal` and `voice` are refused words, and the
`[Instrumental]` lyric the runner always sends is what keeps the bed
instrumental. The approved captions below read longer than seven tags, but
their units are still genre, instruments, mood and exclusions; adding
adjectives inside a unit is fine, inventing a second genre is not.

Name the tempo in the caption text as well as in `bpm` (`slow tempo`,
`95 BPM`): the caption's tempo words and the numeric field both steer the
beat, and a bed that states its tempo twice lands closer to the intent.
Never pair tags that contradict each other — `ambient, metal`, `lofi,
orchestral` — because the model splits the difference and lands on
neither. For a fusion, name one primary genre and one secondary influence
(`jazz, light bossa nova`) and stop there; more words never repair a
caption that fights itself.

The runner sends `thinking = false`, which stops the 5 Hz language model
writing the audio codes; it does not switch the caption pass off. The
server's CoT caption step runs by default and may rewrite or enhance the
caption, and a missing `bpm`, `key` or `time-signature` is a gap that same
model can fill from the caption. Write the caption as the final text you
want, and set `bpm` and `key` whenever the piece has a known tempo or key: a
value the piece sets always wins, and an omitted one may not stay omitted.

The pinned checkpoint is the turbo one, so `steps` is 8 by default and 8 is
the recommended count. `guidance` has no effect on the turbo checkpoint and
is kept only for the other checkpoints: raising it on this package changes
nothing. The 32-64 step range and a guidance value that matters belong to
the base and SFT checkpoints, which `acestep.bed` does not pin.

Seeds are how a caption is iterated: keep one approved `seed` fixed while
the caption changes, so each edit is the only moving part; pin the seed of
the take you approve, so the bed can be regenerated; and step the seed only
to explore alternatives. The two approved pieces in `references/` record the
seeds the lab rendered them at.

Divergence: public ACE-Step guides tune songs of up to ten minutes on the
base checkpoint; facet caps a piece at 30 s and pins the turbo checkpoint,
because a bed only has to sit under a narration line.

## Judging the result

`verify` opens the WAV and passes when its duration is within 1 s of
`duration` and its peak sits above -40 dBFS, reporting both. The run
normalises the bed to -16 LUFS and records `duration_s`, `sample_rate_hz`,
`lufs` and `peak_dbfs`; the preview serves the waveform and loudness in the
audio viewer.

The lab's verdict on the audio decides what to accept:

- **Rejected:** lo-fi and Latin pop, both ~60 % of the energy below 120 Hz,
  with the "instrumental" one sounding like synthetic lo-fi hip-hop.
- **Approved:** acoustic classical, no percussion, 2.5-16 % low energy. The
  approved tracks are `baroque-allegro.wav` and `romantic-nocturne.wav`,
  which ship beside their pieces in `examples/`.
- **Discarded forever:** sung music.

Under narration the bed is the landed `narrado` contract: the bed lands at
-16 LUFS, the voice goes through ffmpeg `normalize` with `target-lufs =
-16.0` and `true-peak-db = -1.5`, then ffmpeg `mix` lays the voice over the
bed with `ducking = true`, `duck-db = -12.0` and `target-lufs = -16.0`, as in
`packages/ffmpeg/examples/normalize.toml` and `mix.toml`.

## Pitfalls

- One heavy job at a time: the package needs the GPU exclusively, 16 GB of
  RAM and 24 GB of disk.
- The first `facet pull acestep` builds the server from ACE-Step's own
  uv.lock: torch and its CUDA wheels, several GB over several minutes.
  It does not build flash-attn.
- The checkpoints come from the server on first start (about 11 GB; the
  first run needs network): absent folders are pending, not missing. A
  missing checkout names `facet pull acestep` as its fix.
- A caption without the no-drums guidance comes back with a bass and kick
  under 120 Hz and ~60 % of the energy there; the caption decides the style.
- Measure loudness and peak, but judge timbre by ear: a bed can sit at the
  right level and still be the wrong instrument.

The guidance above draws on public sources listed in
[references/sources.md](references/sources.md).
