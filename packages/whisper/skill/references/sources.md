# Whisper sources

One row per source the skill text relies on, with the URL, maintainer and
licence as the research report states them, and what was taken from it.

| Source | Maintainer | Licence | Taken |
| --- | --- | --- | --- |
| https://github.com/SYSTRAN/faster-whisper | SYSTRAN | none stated in fetched excerpt (facts only, no wording taken) | The facts that beam width 5 is the quality default with speed as the trade-off lever, and that VAD filtering skips silence before decoding. |
| https://github.com/driserq/autoresearch/blob/HEAD/.claude/skills/whisper-transcribe/SKILL.md | Driserq | none stated (facts only, no wording taken) | The facts that CPU inference uses int8 and that decoding needs no system ffmpeg install. |
| https://terminalskills.io/skills/whisper | TerminalSkills | none stated, v1.1.0 (facts only, no wording taken) | The fact that timed words exist for downstream caption needs. |
| https://github.com/anubhavg-icpl/vibe/blob/HEAD/skills/whisper-expert/SKILL.md | anubhavg-icpl | CC-BY-NC-SA-4.0 (facts only, NO wording taken) | The facts that word timestamps cost speed, that large-v3-turbo trades near-equal accuracy for speed, and that lowering beam width is the main speed lever. |
