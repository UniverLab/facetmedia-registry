---
name: linkedin
description: Post text with images to the lab's LinkedIn organization account, then read it back.
---
# linkedin

`linkedin.post` posts text with images to the lab's LinkedIn
organization account through the Posts API and reads the created post
back. Images ride the Images API asset upload first (one upload per
image, then the returned `urn:li:image:{id}` values ride the post):
exactly one image makes a single-image post, two to twenty images make
a MultiImage post. Every accepted post is public at once — LinkedIn
keeps no drafts, so the dry run comes first and a receipt is never
re-sent.

## When to use

- When the lab publishes from its organization account
  (`urn:li:organization:{id}`, the brand page the lab holds a Company
  Page role for) — with the dry run first:
  `facet run <piece> --dry-run` checks the author URN, the text against
  LinkedIn's 3 000-character limit and every image against the
  MultiImage rules, and shows what will land on the organization's
  feed. It sends nothing and touches no network.
- When the piece carries `author` (the organization URN), `text`
  (required) and `images` (0 to 20 entries, each a local `path` plus
  required `alt` text). A piece without images is a text-only post; a
  piece with more than 20 images is refused before anything leaves.
- When another network or another LinkedIn action is asked for, leave
  this package alone: v1 posts to organization feeds with images only.
  It never posts as a person, never schedules, never touches DMs or
  analytics.

## Pieces

```toml
capability = "linkedin.post"

[inputs]
author = "urn:li:organization:1234567"
text = "La escuadra del laboratorio, recién salida del banco. #taller"

[[inputs.images]]
path = "banco.png"
alt = "La escuadra del laboratorio sobre el banco de trabajo."
```

`author` is the organization URN the post publishes as. `text` is the
commentary, at most 3 000 characters; URLs are unfurled into link
previews. Each image is a JPG, GIF or PNG file under 36 152 320 pixels,
resolved relative to the piece; one image makes a single-image post
(the alt text rides as the media title), two to twenty make a
MultiImage post (each alt text rides its image). The bundled
`examples/post.toml` is the single-image shape with its picture beside
it; dry-run it with `facet run post.toml --dry-run`.

## Authentication

The agent never handles a secret: it never asks the user to paste one
into the conversation, and it never runs `facet secret set` or
`facet auth` with a value. Connecting the account is the user's own work
in their own terminal, in this order:

1. The user creates the lab's own app in the LinkedIn Developer Portal
   and adds the **Share on LinkedIn** and **Sign In with LinkedIn using
   OpenID Connect** products to it.
2. The user requests the **`w_organization_social`** and
   **`r_organization_social`** scopes for the app. Both are granted
   only to apps tied to a Company Page the member administers, and the
   member must hold one of the **ADMINISTRATOR**,
   **DIRECT_SPONSORED_CONTENT_POSTER** or **CONTENT_ADMIN** roles —
   without the role the upload and the read-back fail.
3. The user registers the redirect URI in the app's auth settings:
   `http://localhost:8080/callback` (a loopback address, so the
   sign-in returns to the user's own machine).
4. The user stores the app values and the organization id, each from a
   hidden prompt, never pasted in chat: `facet secret set linkedin
   client-id`, `facet secret set linkedin client-secret`, and
   `facet secret set linkedin org-id` with the numeric id (the digits
   of `urn:li:organization:{id}`).
5. The user runs `facet auth linkedin` in their own terminal. It opens
   the sign-in address, the user authorizes the app for the member who
   holds the Company Page role, and the token pair is stored through
   facet's secrets store.
6. The user confirms with `facet doctor linkedin --full`: it reports
   which member the token opens and whether both organization scopes
   were granted with a Company Page role for the stored organization,
   so a post never lands on an unexpected account.

Usual failures: `client-id is not stored` (or any of the five names)
means a step was skipped — store the app values and run
`facet auth linkedin` again. A sign-in that opens the wrong member
means the user authorized a personal account instead of the role
holder: run `facet auth linkedin` again and pick the member who holds
the Company Page role. The doctor reporting no Company Page role means
the member holds none for the stored organization: grant
ADMINISTRATOR, DIRECT_SPONSORED_CONTENT_POSTER or CONTENT_ADMIN on
the page and sign in again. A run refused with `Not enough
permissions` means a scope was not granted at sign-in: approve both
scopes and sign in again. A run refused after a long idle means the
refresh failed: sign in again. An image refused means the file breaks
the format or 36 152 320-pixel cap: convert or shrink it and send
again.

## Judging the result

The dry run answers one entry with `text`, the `account` as
`@not-read` (it sends nothing), the image paths, `warnings` (an
over-long text, images over size or count, an unreadable image) and
`cost` (null), plus group lines naming that the piece publishes as the
organization on its feed as PUBLIC, that accepted posts are public at
once, and that a receipt is never re-sent. Read the warnings before
confirming: a text over 3 000 characters or an image over the pixel cap
is refused by the run.

A real run answers the receipt's `post` object — network `linkedin`,
the organization's display name, state `published`, one `{id, url}`
entry with the `x-restli-id` Post ID and its feed URL, and `cost`
null — and facet writes the receipt. An image the upload refuses fails
the run with LinkedIn's reason before anything is posted.

`verify` reads the created post back and passes only when LinkedIn
returns it with the same text and the same media count.

`preview` writes the post schema's preview beside the receipt: the
text in `posts[0].text`, the feed URL, state `published`, network
`linkedin` and the organization, with a summary saying the post is
public on the organization's feed.

## Pitfalls

- **Organization posts only, never personal.** The author is always a
  `urn:li:organization:{id}` URN; personal posting is out of scope.
- **Images only, at most twenty.** Videos, documents, carousels, polls
  and articles are follow-ups, not v1.
- **Public at once, no drafts.** Whatever LinkedIn accepts is visible
  immediately; there is no inbox to review it in.
- **Never re-send a receipt.** A real upload is not retried over an
  existing receipt; removing a receipt to force one posts a duplicate.
- **Pick the role-holding member.** At sign-in choose the member who
  holds the Company Page role; confirm it with
  `facet doctor linkedin --full` so a post never lands on a personal
  account.

Sources for these rules, with their licences, are in
`references/sources.md`.
