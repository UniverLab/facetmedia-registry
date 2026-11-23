# linkedin

Posts text with images to the lab's LinkedIn organization account
through the Posts API, then reads the created post back. Images upload
first as assets through the Images API — one upload per image, then the
returned `urn:li:image:{id}` values ride the post: one image makes a
single-image post (the alt text rides as the media title), two to
twenty make a MultiImage post. A piece without images is a text-only
post; more than twenty images is refused before anything leaves. Every
accepted post is public at once — LinkedIn keeps no drafts — with
visibility PUBLIC on the organization's main feed. The whole package is
stdlib — a thin vendored client, no SDK — so it runs anywhere the facet
lock runs.

## Capability and pieces

`linkedin.post` — post kind, outward:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `author` | string | yes | — | The organization URN the post publishes as, `urn:li:organization:{id}` |
| `text` | string | yes | — | The post's commentary, at most 3000 characters |
| `images` | array | no | — | The post's images, each entry a local `path` plus required `alt` text; 1 image is a single-image post, 2 to 20 a MultiImage post |

The receipt's post carries state `published`, one `{id, url}` entry
with the `x-restli-id` Post ID and its feed URL, and the organization's
display name as the account.

The bundled `examples/post.toml` is the single-image shape with its
still beside it; dry-run it with `facet run post.toml --dry-run`.

## What v1 leaves out

v1 posts to organization feeds with images only: no personal posting,
no videos, documents, carousels, polls or articles, no scheduling, no
DMs, no analytics. Drafts are not a LinkedIn concept — whatever is
accepted is public.
