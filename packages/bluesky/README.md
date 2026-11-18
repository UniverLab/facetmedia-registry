# bluesky

Posts text, images, video and threads to the lab's Bluesky brand account:
`facet run bluesky.post` sends one post or a thread through the AT
Protocol, then reads it back. The whole package is stdlib — a thin vendored
XRPC client, no SDK — so it runs anywhere the facet lock runs.

## Capability and pieces

`bluesky.post` — post kind, outward:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `posts` | array | yes | — | One table per post, min 1, sent in order; every post after the first replies to the previous one |
| `images` | array | no | — | One table per image, naming its post by 1-based position |

Each `posts` item carries `text` (required, at most 300 graphemes; links,
mentions and hashtags become clickable facets), `lang` (optional BCP 47
tag), `video` (optional path, refused together with images on the same
post), and an optional link card: `card-url` with `card-title` and
`card-description` (both required with the URL) plus `card-thumb`
(optional path, warned about when missing).

Each `images` item carries `post` (integer >= 1, required, the post it
attaches to), `path` (required) and `alt` (required — an image without alt
text is refused). At most four images ride one post.

Credentials come from the secrets store, never the piece: `handle` and
`app-password` (both required). `facet secret set bluesky handle` and
`facet secret set bluesky app-password`, run by a person in their own
terminal, store them; the runner reads them through the SDK.

## Verification and preview

`dry-run` sends nothing and writes nothing: one entry per post with its
rendered `text`, `account`, `media` paths, `warnings` and `cost` (null —
the network does not charge). It warns about over-long text, images over
the byte limit and a card without a thumbnail.

`run` answers the receipt's `post` object — network `bluesky`, the
account, state `published`, one `{id, url}` per post — and facet writes
the receipt. `verify` reads every receipt post back from the PDS and
checks it exists, its text matches the piece and its media count matches.
`preview` writes the post schema's preview file beside the receipt:
`images` holds every media file's name (empty for a text-only thread) and
each post carries its `text`, `url` and `media` with alt text.

`facet doctor post` checks the client and both secrets at the quick depth;
`--full` signs in with the stored credentials and names the account they
open (handle and display name).

## Licences

The AT Protocol is MIT (Bluesky Social PBC); the manifest records it. The
package itself is MIT like the recipe tooling.

## Bundled examples

`facet example <capability> --run` copies the capability's example, with
every file it names, into a fresh folder and runs it there:

- `bluesky.post` — `examples/thread.toml`: `facet example bluesky.post --run`
