# Captions and piece shapes for `acestep.bed`

One `.toml` is one track. The caption is the whole style control: it is
English, and the runner always sends `lyrics = "[Instrumental]"` with
`task_type = "text2music"`, so there is no separate instrumental switch to
set in a piece.

## Piece shape

```toml
[inputs]
caption = "English style caption, acoustic instruments, ending in the no-drums line"
name = "baroque-allegro"
duration = 30
```

- `caption` — English, required. Ask for acoustic instruments and end with
  `No drums, no percussion, no bass beat, no synthesizers`. A caption naming
  a voice is refused by the runner: this package is instrumental only.
- `name` — required, matches `[a-z0-9][a-z0-9-]*`; the runner renames the
  randomly-named server output to `<name>.wav`.
- `duration` — required, seconds of music, at most 30.

## Caption anatomy

Four units, in this order, 3 to 7 comma-separated tags in total, then the
exclusions:

1. **genre** — one, at most two (`Baroque chamber orchestra`, `solo piano
   and string quartet`);
2. **instruments** — what is playing and how (`harpsichord continuo`,
   `bright strings playing fast staccato runs`);
3. **mood** — one mood, in two or three adjectives (`energetic, festive and
   elegant`);
4. **tempo** — stated in words (`allegro`, `slow tempo`, `95 BPM`) and, when
   the piece sets it, repeated in `bpm`.

The exclusions come last and as negatives: `Acoustic instruments only. No
drums, no percussion, no bass beat, no synthesizers, no electronic sounds.`
A voice word is not an exclusion here: `no vocals` is refused, and the
`[Instrumental]` lyric the runner sends is what keeps the bed instrumental.

- **Never contradict a tag.** `ambient, metal` or `lofi, orchestral` pulls
  the model in two directions and it lands on neither; pick one. A fusion
  is one primary genre plus one secondary influence (`jazz, light bossa
  nova`), never two equals and never a list.
- **Put the tempo in the text, not only in `bpm`.** The caption's tempo
  words steer the beat; the numeric field alone leaves the model free to
  read the mood as faster or slower than intended.
- **Make the words and the numbers agree.** `bpm = 66` under a caption that
  says `fast and driving` fights itself; a table of tags that disagree with
  the fields is worse than a sparse caption.
- **Front-load the control words.** Genre, instruments and mood in the
  first lines; exclusions at the end. A caption that opens with a story and
  names the instruments last buries its own controls.

## Approved: `baroque-allegro`

Major key, joyful and lively; approved by the person as a background bed on
2026-10-13. Ships as `examples/baroque-allegro.toml` and `.wav`.

```toml
[inputs]
caption = "Lively, joyful Baroque chamber orchestra piece in the style of a Vivaldi allegro. Bright strings playing fast staccato and spiccato runs, harpsichord continuo, playful solo violin and flute melodies. Energetic, festive and elegant. Acoustic instruments only. No drums, no percussion, no bass beat, no synthesizers, no electronic sounds."
name = "baroque-allegro"
duration = 30
```

The lab's piece also carried `bpm = 132`, `keyscale = "G major"`,
`timesignature = "4"`, `seed = 22` and `config_path = "acestep-v15-turbo"`.
Those are not `acestep.bed` inputs; the caption is what reproduces the style.

## Approved: `romantic-nocturne`

Minor key, melancholic; approved by the person as a background bed on
2026-10-13. Ships as `examples/romantic-nocturne.toml` and `.wav`.

```toml
[inputs]
caption = "Melancholic classical piece for solo piano and string quartet, Romantic era style. Slow tempo, expressive legato violin melody over gentle piano arpeggios and sustained cello notes. Intimate, sorrowful, reflective. Acoustic instruments only. No drums, no percussion, no bass beat, no synthesizers, no electronic sounds."
name = "romantic-nocturne"
duration = 30
```

The lab's piece also carried `bpm = 66`, `keyscale = "D minor"`,
`timesignature = "3"`, `seed = 21` and `config_path = "acestep-v15-turbo"`.

## The no-drums line

```
No drums, no percussion, no bass beat, no synthesizers
```

Both approved captions add `, no electronic sounds` after it. Without the
line the model loads bass and kick, and about 60 % of the energy falls below
120 Hz; with it the approved acoustic classics came in at 2.5-16 % low
energy. Never ask for sung music: the lab discarded it forever, and the
runner refuses a caption that names a voice.
