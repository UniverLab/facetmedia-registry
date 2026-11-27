# video-ops sources

| Source | Maintainer | Licence | Taken |
| --- | --- | --- | --- |
| https://ffmpeg.org/ffmpeg.html | FFmpeg project | GPL-3.0-or-later | Standard CLI flags (`-ss`, `-to`, `-c:v libx264`, `-pix_fmt yuv420p`, `-movflags +faststart`, `-c:v copy`, `-shortest`, `-frames:v 1`). |
| https://github.com/imageio/imageio-ffmpeg | imageio contributors | BSD-2-Clause | Bundled static FFmpeg binary discovery via `imageio_ffmpeg.get_ffmpeg_exe()`. |
| https://python-pillow.org/ | Jeffrey A. Clark and contributors | MIT-CMU | Image validation and dimension reading via Pillow (`PIL.Image`). |
