Fixtures for the deepfilter piece. No real person's voice is used.
- voice-noisy.wav: synthesized with the standard library only (no voice
  model): gated speech-like harmonic bursts at 48 kHz mono with a
  deterministic noise floor, 2.0 s, peak under 0 dBFS.
- enhance.toml consumes voice-noisy.wav and writes voice-denoised.wav.
