Fixtures for the ffmpeg pieces. No real person's voice is used.
- voice.flac: spoken with facet's kokoro.speak (voice af_heart, en-us),
  10.56 s at 16 kHz mono; then converted to FLAC. Text: "In this laboratory we test a locally generated English voice. We want to measure how clear it sounds, how long it takes, and how it compares with the voices we already use."
- bed.flac: instrumental pink-noise bed made with facet's FFmpeg
  (anoisesrc, low-passed at 800 Hz, laid at -30 dBFS). No language.
  Command: ffmpeg -f lavfi -i "anoisesrc=color=pink:duration=15:sample_rate=12000" -af "lowpass=f=800,volume=-30dB" -c:a flac bed.flac
