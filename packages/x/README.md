# x

Posts text, images, video and threads to the lab's X brand account:
`facet run x.post` sends one post or a thread through the X API v2 with
OAuth 1.0a user context, shows the cost before the send, then reads it
back. The whole package is stdlib — a thin vendored client, no SDK — so
it runs anywhere the facet lock runs.

## Capability and pieces

`x.post` — post kind, outward:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `posts` | array | yes | — | One table per post, min 1, sent in order; every post after the first replies to the previous one |
| `images` | array | no | — | One table per image, naming its post by 1-based position |

Each `posts` item carries `text` (required, at most 280 weighted
characters — every URL counts as 23, emoji and CJK count twice), `video`
(optional path, refused together with images or a GIF on the same post)
and `gif` (optional path, refused together with images or a video on the
same post).

Each `images` item carries `post` (integer >= 1, required, the post it
attaches to), `path` (required) and `alt` (required — an image without alt
text is refused). At most four images ride one post; one video or one GIF
rides alone instead.

The per-request prices live in `rates.json` beside the runner (read
2026-11-17): a post costs $0.015, a post with a URL $0.200, reading a post
back costs $0.005, and the one account read a real run makes costs $0.010.
A rate change ships as a package version bump.

Credentials come from the secrets store, never the piece: `consumer-key`,
`consumer-secret`, `access-token` and `access-token-secret` (all
required). The four `facet secret set x <name>` commands, run by a person
in their own terminal, store them; the runner reads them through the SDK.

## Verification and preview

`dry-run` sends nothing, writes nothing and spends nothing: one entry per
post with its rendered `text`, an `account` of `@not-read` (a real run
reads the handle), `media` paths, `warnings` and `cost` (`{"amount",
"currency"}`) plus the group's own `warnings`, which itemize every post's
price, the read-back's price, the account read, the total and the date the
rates were read. It warns when a URL raises a post's price, about
over-long text and about media over its byte limit.

`run` uploads the media, sends the thread and answers the receipt's `post`
object — network `x`, the account, state `published`, one `{id, url}` per
post, `cost` with the computed total — and facet writes the receipt.
`verify` reads every receipt post back by id with the account's own
credentials and checks it exists, its text matches the piece and its media
count matches; URLs are left out of the comparison because X rewrites them
to `t.co` and may append a media link. `preview` writes the post schema's
preview file beside the receipt: `images` holds every media file's name
(empty for a text-only thread) and each post carries its `text`, `url` and
`media` with alt text.

`facet doctor post` checks the client, the rates and all four secrets at
the quick depth; `--full` reads the own account with the stored keys,
names the account they open, probes write access with a request the
network rejects before creating a post, and states the cost of the read.

## Licences

X's API is a hosted service under X's Developer Agreement, not an
open-source licence; the manifest records that. The package itself is MIT
like the recipe tooling.

## Bundled examples

`facet example <capability> --run` copies the capability's example, with
every file it names, into a fresh folder and runs it there:

- `x.post` — `examples/thread.toml`: `facet example x.post --run`
