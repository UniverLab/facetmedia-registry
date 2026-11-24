---
name: x
description: Post text, images, video and threads to the lab's X brand account through the X API v2, with the cost shown before the send and a read-back.
---
# x

`x.post` sends one post or a thread to the lab's X brand account and
reads it back. It is the lab's second publish package (user decision,
2026-11-17): X is pay per use, so every dry run shows the cost of each
post before it goes out — a post costs $0.015, a post carrying a URL
costs $0.200, reading the thread back costs $0.005 per post and the
account read at send time costs $0.010 (rates read 2026-11-17, bundled in
`rates.json`). Text alone goes unnoticed, so a post carries the media
facet makes, and a thread can tell a longer story. X keeps no drafts
through the API: every post it accepts is public.

## When to use

- When the lab publishes from its brand account: a post with the media
  facet made, or a thread when one post cannot hold the story — with the
  dry run's cost read first, because a link costs about thirteen times a
  text-only post.
- When the piece must carry images (up to four per post, each with alt
  text), one video, or one GIF — never more than one of those on the
  same post, because a post carries a single media slot.
- When a dry run must come first: `facet run <piece> --dry-run` renders
  every post, counts its weighted length the way X does (every URL counts
  as 23 characters, emoji and CJK count twice), prices every post, the
  read-back and the account read item by item with the date the rates
  were read, and warns when a URL raises a post's price.
- When another network is asked for, leave this package alone: it only
  speaks X. It never schedules, deletes or reads timelines, and never
  touches DMs.

## Pieces

```toml
capability = "x.post"

[[inputs.posts]]
text = "La escuadra del laboratorio, recién salida del banco. #taller"

[[inputs.posts]]
text = "El plano queda en el catálogo https://univerlab.org/catalogo/escuadra"

[[inputs.images]]
post = 1
path = "banco.png"
alt = "La escuadra de aluminio sobre la mesa, con sus dos agujeros a la vista."
```

`posts` holds the thread in order, at least one; every post after the
first is sent as a reply to the previous one, so the app shows one
thread. `text` is required and holds at most 280 weighted characters:
most characters count once, emoji and CJK count twice, and every URL
counts as 23 whatever its length. X detects the language itself.

`images` names the posts each image attaches to by 1-based position.
`path` is resolved relative to the piece, `alt` is required — an image
without alt text is refused. `video` on a post replaces images: one
video per post, never images and a video together; `gif` is the same
slot: one GIF per post, never images and a GIF together, never video and
a GIF together.

The bundled `examples/thread.toml` is the same shape with its still
beside it; dry-run it with `facet run thread.toml --dry-run`.

## Authentication

The agent never handles a secret: it never asks the user to paste one
into the conversation, and it never runs `facet secret set` with a
value. The guided way to connect is `facet auth login x`: it walks
the user through every secret below. In a non-interactive shell, connecting
the account is the user's own work in their own terminal instead, one
`facet secret set` fallback command per secret, in this order:

1. The user creates the lab's own developer app in the Developer
   Console (developer.x.com), one app for the brand account, and loads
   credits in the same Console: X is pay per use, and a run with no
   credits is refused. The API key and secret are shown once when the
   app is created — they are saved then.
2. The user opens the app's Settings and sets its permission to **Read
   and write** before generating the access token. A token generated
   earlier stays read-only: posting with it is refused, so a new one is
   generated after the switch.
3. The user generates the brand account's access token and secret inside
   the app's **Keys and tokens** tab and stores the four secret names
   the manifest declares, one command each, typed in their own
   terminal — each command reads the value from a hidden prompt, so it
   never rides a command line: `facet secret set x consumer-key` (the
   app's API key), then `facet secret set x consumer-secret` (the app's
   API secret), then `facet secret set x access-token` (the brand
   account's access token) and then
   `facet secret set x access-token-secret` (the token's secret).
4. The user confirms with `facet doctor post --full`: it reads the own
   account with the stored keys, reports which account they open, and
   probes write access with a request the network rejects before creating
   a post. The read costs $0.010; the probe creates nothing.

Usual failures: `consumer-key is not stored` (or any of the four names)
means step 3 was skipped for that name; a sign-in that fails with all
four stored means a pasted value carries a stray space or belongs to
another app — regenerate it in the same tab and store it again. The
doctor's `write` check failing means the token is read-only: set the app
to **Read and write**, generate a new access token and store it again. A
403 on the first post with a fresh token means the same thing. A refused
run with no other change means the credits ran out: load more in the
Console. An access token works only for the account that created the
app: tokens made on a personal account never open the brand account.

## Judging the result

The dry run answers one entry per post — rendered `text`, `account`,
`media` paths, `warnings`, `cost` (`{"amount", "currency"}` per post) —
plus the group's own `warnings`, which itemize the run: every post's
price, the read-back's price per post, the account read at send time, the
total, and the date the rates were read. The `account` is `@not-read`
because a dry run sends nothing and spends nothing; a real run reads the
handle. Read the warnings before confirming: an over-long post, an image
over the byte limit, or a URL raising a post's price is a warning here
and a refused or costlier send later.

A real run answers the receipt's `post` object — network `x`, the
account, state `published`, one `{id, url}` per post, `cost` with the
computed total — and facet writes the receipt. `verify` reads every
receipt post back by id with the account's own credentials and checks it
exists, its text matches the piece and its media count matches. X rewrites
URLs to `t.co` and may append a media link, so URLs are left out of the
text comparison; any other difference fails inside the runner with the
post named.

`preview` writes the post schema's preview beside the receipt: `images`
holds every media file's name (empty for a text-only thread) and each
post carries its `text`, `url` and `media` with alt text. The text lives
only there — the receipt keeps just `{id, url}` per post.

`facet doctor post --full` states the cost of its own check: the account
read it runs is billed at the bundled user-read rate, $0.010.

## Pitfalls

- **A URL raises the price.** A post carrying a link costs about
  thirteen times a text-only post: check the dry run's itemized cost
  lines before confirming, especially on threads where several posts
  carry links.
- **One media slot per post.** Images, a video and a GIF are three
  shapes of the same slot: the runner refuses a post that combines
  them rather than silently dropping one.
- **Alt text is not optional.** An image without it is refused before
  anything leaves; write what the image shows, not what the post says.
- **280 weighted characters, not 280 characters.** Every URL counts as
  23, emoji and CJK count twice, and an emoji sequence counts once; the
  dry run counts the same way the limit is held.
- **The thread order is the reply chain.** The second post replies to
  the first, the third to the second: reorder the tables and the story
  re-threads. A post may carry no media — a text reply is normal.
- **Every accepted post is public.** X keeps no drafts through the
  API: there is no quiet send. Never re-send a receipt; when a later
  step fails the receipt is kept as `unknown` and the receipt-exists
  rule refuses a second send over it. Removing the receipt to force one
  risks a duplicate thread.

Sources for these rules, with their licences, are in
`skill/references/sources.md`.
