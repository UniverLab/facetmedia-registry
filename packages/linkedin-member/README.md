# linkedin-member

Posts text with images or an MP4 video to the owner's personal LinkedIn
profile through the Posts API, then reads the created post back when
permitted. Images upload first as assets through the Images API — one
upload per image, then the returned `urn:li:image:{id}` values ride the
post: one image makes a single-image post (the alt text rides as the
media title), two to twenty make a MultiImage post. A local `.mp4`
video uploads through the Videos API instead: initialize upload, PUT
each chunk, finalize with the chunk ETags, and poll until `AVAILABLE`
before creating the post. A piece without images or video is a
text-only post; more than twenty images is refused before anything
leaves. `images` and `video` are mutually exclusive. Every accepted
post is public at once — LinkedIn keeps no drafts — with visibility
PUBLIC on the owner's personal profile under their name. The whole
package is stdlib — a thin vendored client, no SDK — so it runs
anywhere the facet lock runs.

Use `linkedin` instead when posting to a Company Page / organization
account (`urn:li:organization:{id}`); the two sign in separately.

## Capability and pieces

`linkedin-member.post` — post kind, outward:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `text` | string | yes | — | The post's commentary, at most 3000 characters |
| `images` | array | no | — | The post's images, each entry a local `path` plus required `alt` text; 1 image is a single-image post, 2 to 20 a MultiImage post |
| `video` | path | no | — | Optional local `.mp4` video file (<= 500 MiB), resolved relative to the piece; refused together with `images` |
| `video-title` | string | no | video filename stem | Optional video attachment title |

The author is always the signed-in member (`urn:li:person:{member-id}`),
derived from the stored `member-id` secret.

The receipt's post carries state `published` (or `unknown` with a
warning when LinkedIn refuses the read-back as forbidden), one
`{id, url}` entry with the `x-restli-id` Post ID and its feed URL, and
the member's display name as the account.

The bundled `examples/post.toml` is the single-image shape with its
still beside it; dry-run it with `facet run post.toml --dry-run`.

## What v1 leaves out

v1 posts to the signed-in member's personal profile with text, images,
or one MP4 video: no organization posting (use `linkedin`), no
documents, carousels, polls or articles, no scheduling, no DMs, no
analytics. Drafts are not a LinkedIn concept — whatever is accepted is
public.
