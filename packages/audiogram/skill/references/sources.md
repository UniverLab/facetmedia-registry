# audiogram sources

| Source | Maintainer | Licence | Taken |
| --- | --- | --- | --- |
| https://ffmpeg.org/ffmpeg.html | FFmpeg project | GPL-3.0-or-later | Standard CLI flags (`-f rawvideo`, `-pix_fmt rgb24`, `-s WxH`, `-r fps`, `-c:v libx264`, `-pix_fmt yuv420p`, `-c:a aac`, `-movflags +faststart`, `-shortest`) and `ffmpeg -i` stderr probing (Duration, Video/Audio stream lines). |
| https://github.com/imageio/imageio-ffmpeg | imageio contributors | BSD-2-Clause | Bundled static FFmpeg binary discovery via `imageio_ffmpeg.get_ffmpeg_exe()` (imageio-ffmpeg 0.6.0). |
| https://numpy.org/ | NumPy developers | BSD-3-Clause | Mono sample analysis: per-frame log FFT magnitudes (`numpy.fft.rfft`) for bars and per-column peak envelopes for the waveform (numpy 2.5.4). |
| https://python-soundfile.readthedocs.io/ | soundfile contributors | BSD-3-Clause | Decoded WAV I/O (`soundfile.read`, `soundfile.write`) for analysis samples and the doctor's synthetic sine (soundfile 0.13.1). |
| https://python-pillow.org/ | Jeffrey A. Clark and contributors | MIT-CMU | Frame rendering (`PIL.Image`, `PIL.ImageDraw`, `PIL.ImageFont`) and cover scaling plus dimension reading (pillow 13.0.0). |
