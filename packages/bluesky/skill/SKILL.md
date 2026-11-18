---
name: bluesky
description: Post text, images, video and threads to the lab's Bluesky brand account through the AT Protocol, with a read-back check after the send.
---
# bluesky

`bluesky.post` sends one post or a thread to the lab's Bluesky brand
account and reads it back. It is the lab's first publish package
(user decision, 2026-11-17): Bluesky is open and free, needs no app
review, and one handle plus one app password connects the account.
Text alone goes unnoticed, so a post carries the media facet makes, and
a thread can tell a longer story.

## When to use

- When the lab publishes from its brand account: a post with the media
  facet made, or a thread when one post cannot hold the story.
- When the piece must carry images (up to four per post, each with alt
  text), one video, or an external link card — never more than one of
  those on the same post, because a post carries a single embed.
- When a dry run must come first: `facet run <piece> --dry-run` renders
  every post, counts graphemes and warns, and sends nothing.
- When another network is asked for, leave this package alone: it only
  speaks Bluesky. It never schedules, deletes or edits posts, and never
  reads timelines.

## Pieces

```toml
capability = "bluesky.post"

[[inputs.posts]]
text = "La escuadra del laboratorio, recién salida del banco. #taller"
lang = "es"

[[inputs.posts]]
text = "El plano queda en el catálogo para quien quiera repetirla."
lang = "es"
card-url = "https://univerlab.org/catalogo/escuadra"
card-title = "Escuadra de banco"
card-description = "Plano y cotas de la escuadra del laboratorio."

[[inputs.images]]
post = 1
path = "banco.png"
alt = "La escuadra de aluminio sobre la mesa, con sus dos agujeros a la vista."
```

`posts` holds the thread in order, at least one; every post after the
first is sent as a reply to the previous one, so the app shows one
thread. `text` is required and holds at most 300 graphemes. Links,
mentions (`@handle`) and hashtags in the text become clickable facets;
a mention that does not resolve stays plain text rather than failing
the send. `lang` is the BCP 47 tag of the text, for example `es`.

`images` names the posts each image attaches to by 1-based position.
`path` is resolved relative to the piece, `alt` is required — an image
without alt text is refused. `video` on a post replaces images: one
video per post, never images and a video together, and never media and
a link card together either. `card-url` needs `card-title` and
`card-description` with it; `card-thumb` is optional and warned about
when missing.

The bundled `examples/thread.toml` is the same shape with its still
beside it; dry-run it with `facet run thread.toml --dry-run`.

## Authentication

The agent never handles a secret: it never asks the user to paste one
into the conversation, and it never runs `facet secret set` with a
value. Connecting the account is the user's own work in their own
terminal, in this order:

1. The user signs in to the brand account in a browser, opens
   **Settings → Privacy & Security → App passwords**, and creates one
   app password for facet (any name, for example `facet`). This is the
   only secret they create; the account password is never used and
   never stored.
2. The user stores the two secret names the manifest declares, one
   command each, typed in their own terminal — each command reads the
   value from a hidden prompt, so it never rides a command line:
   `facet secret set bluesky handle` (the brand account's handle, for
   example `lab.univerlab.org`) and then
   `facet secret set bluesky app-password` (the app password from step
   1, not the login password).
3. The user confirms with `facet doctor post --full`: it signs in with
   the stored credentials and reports the account they open — handle
   and display name — or why they fail.

Usual failures: `handle is not stored` or `app-password is not stored`
means step 2 was skipped for that name; a failed sign-in with both
stored means the handle is mistyped (a short handle without its domain
is the classic) or the app password is wrong or revoked — create a new
one in the same settings screen and store it again. An app password
works only for the account that created it: credentials made on a
personal account never open the brand account.

## Judging the result

The dry run answers one entry per post — rendered `text`, `account`,
`media` paths, `warnings`, `cost` (null, the network does not charge) —
plus the group's own `warnings`. Read them before confirming: an
over-long post, an image over the byte limit or a card without a
thumbnail is a warning here and a refused or imageless send later.

A real run answers the receipt's `post` object — network `bluesky`,
the account, state `published`, one `{id, url}` per post — and facet
writes the receipt beside the piece's other outputs. `verify` reads
every receipt post back from the account's own server and checks it
exists, its text matches the piece and its media count matches; facet
judges only the state and the count, so a text the network changed
fails inside the runner with the post named.

`preview` writes the post schema's preview beside the receipt: `images`
holds every media file's name (empty for a text-only thread) and each
post carries its `text`, `url` and `media` with alt text. The text lives
only there — the receipt keeps just `{id, url}` per post.

## Pitfalls

- **One embed per post.** Images, a video and a link card are three
  shapes of the same slot: the runner refuses a post that combines
  them rather than silently dropping one.
- **Alt text is not optional.** An image without it is refused before
  anything leaves; write what the image shows, not what the post says.
- **300 graphemes, not 300 characters.** A flag or a joined emoji
  counts once; the dry run counts the same way the limit is held.
- **The thread order is the reply chain.** The second post replies to
  the first, the third to the second: reorder the tables and the story
  re-threads. A post may carry no media — a text reply is normal.
- **A resolved mention only.** The runner resolves `@handle` through
  the directory; a handle that does not resolve posts as plain text.
  Check the spelling instead of re-sending: the first send already
  left.
- **Never re-send a receipt.** A real run is never retried by facet;
  when a later step fails the receipt is kept as `unknown` and the
  receipt-exists rule refuses a second send over it. Removing the
  receipt to force one risks a duplicate thread.

Sources for these rules, with their licences, are in
`skill/references/sources.md`.
