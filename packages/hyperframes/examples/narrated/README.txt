Fixtures for the hyperframes narrated piece. No real person's voice is used.
- voice-a.wav: spoken with facet's kokoro.speak (voice af_heart, en-us).
  Text: "This piece layers a voice over a music bed."
- voice-b.wav: spoken with facet's kokoro.speak (voice af_heart, en-us).
  Text: "The subtitles follow every word."
- music.wav: instrumental four-second synthesized chord made with
  facet's FFmpeg. No language.
  Command: ffmpeg -f lavfi -i "sine=frequency=220:duration=4:sample_rate=44100" -f lavfi -i "sine=frequency=277:duration=4:sample_rate=44100" -f lavfi -i "sine=frequency=330:duration=4:sample_rate=44100" -filter_complex "amix=inputs=3,volume=-12dB" -c:a pcm_s16le music.wav
- subtitles.srt: cues timed to voice-a.wav and voice-b.wav.
