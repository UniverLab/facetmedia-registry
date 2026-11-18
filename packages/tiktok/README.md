# tiktok

Sends one video or a photo set to the lab's TikTok account inbox as a
draft through the Content Posting API, then reads its publish status
back. Videos upload from a local file in chunks; photos are only taken
from URLs on a domain the TikTok app has verified. Drafts wait in the
app's inbox for the user to finish them with one tap — the package never
posts to public, which would need an audit the lab does not have. The
whole package is stdlib — a thin vendored client, no SDK — so it runs
anywhere the facet lock runs.

## Capability and pieces

`tiktok.post` — post kind, outward:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `caption` | string | yes | — | The caption the user should paste in the TikTok app; the inbox flow takes no caption |
| `video` | path | no | — | One local video file (MP4, WebM, MOV, at most 4 GiB), refused together with photos |
| `photos` | array | no | — | The photo set, each entry a `url` on a verified domain over https, refused together with a video |

Exactly one of `video` and `photos` must be set. The receipt's post
carries state `draft`, one `{id, url}` entry with TikTok's `publish_id`,
and the account's profile URL — a draft has no URL of its own until the
user posts it.

The bundled `examples/inbox.toml` is the same shape with its clip beside
it; dry-run it with `facet run inbox.toml --dry-run`.
