---
name: linkedin-member
description: Post text with images to the owner's personal LinkedIn profile, then read it back when permitted.
---
# linkedin-member

`linkedin-member.post` posts text with images to the owner's personal
LinkedIn profile under their own name through the Posts API, and reads
the created post back when permitted. Images ride the Images API asset
upload first (one upload per image, then the returned `urn:li:image:{id}`
values ride the post): exactly one image makes a single-image post, two
to twenty images make a MultiImage post. Every accepted post is public at
once — LinkedIn keeps no drafts, so the dry run comes first and a
receipt is never re-sent.

## Choosing between `linkedin` and `linkedin-member`

- **`linkedin`** posts to a **Company Page / organization account**
  (`urn:li:organization:{id}`) and requires LinkedIn's organization
  permissions (`w_organization_social`, `r_organization_social`, plus a
  Company Page role).
- **`linkedin-member`** posts to the **owner's personal LinkedIn
  profile** (`urn:li:person:{member-id}`) under their own name, using
  LinkedIn's self-serve **Share on LinkedIn** product (`w_member_social`).
- The two packages sign in separately, each with its own entry in
  `facet auth login`.

## When to use

- When the owner publishes to their own personal LinkedIn profile — with
  the dry run first: `facet run <piece> --dry-run` checks the text
  against LinkedIn's 3 000-character limit and every image against the
  MultiImage rules, and shows what will land on the personal profile. It
  sends nothing and touches no network.
- When the piece carries `text` (required) and `images` (0 to 20 entries,
  each a local `path` plus required `alt` text). There is no `author`
  input: the author is always the signed-in member. A piece without
  images is a text-only post; a piece with more than 20 images is refused
  before anything leaves.
- When posting to an organization page or using another LinkedIn action,
  leave this package alone: use `linkedin` for organization feeds. v1
  posts to the personal profile with images only; it never schedules,
  never touches DMs or analytics.

## Pieces

```toml
capability = "linkedin-member.post"

[inputs]
text = "La escuadra del laboratorio, recién salida del banco. #taller"

[[inputs.images]]
path = "banco.png"
alt = "La escuadra del laboratorio sobre el banco de trabajo."
```

`text` is the commentary, at most 3 000 characters; URLs are unfurled
into link previews. Each image is a JPG, GIF or PNG file under
36 152 320 pixels, resolved relative to the piece; one image makes a
single-image post (the alt text rides as the media title), two to twenty
make a MultiImage post (each alt text rides its image). The bundled
`examples/post.toml` is the single-image shape with its picture beside
it; dry-run it with `facet run post.toml --dry-run`.

## Authentication

The agent never handles a secret: it never asks the user to paste one
into the conversation, and it never runs `facet secret set` or
`facet auth` with a value. The guided way to connect is
`facet auth login linkedin-member`: it walks the user through every
secret below and opens the browser sign-in. In a non-interactive shell,
connecting the account is the user's own work in their own terminal
instead, one `facet secret set` fallback command per typed secret:

1. The user creates the lab's own app in the LinkedIn Developer Portal
   with the Create an app form: the App name is required; the LinkedIn
   Page is required and must be a Company Page the user administers (not
   a member profile page), it cannot be changed once the app is saved,
   and a Page admin verifies the association — an individual developer
   without a Company Page selects the default Company Page the products
   offer, or creates one first with the form's "Create a new LinkedIn
   Page" link; the App logo is required (square recommended, at least
   100 px in one dimension); the Privacy policy URL is optional; and the
   legal agreement must be accepted. The Client ID and the Client Secret
   are on the app's Auth tab.
2. In the LinkedIn Developer Portal, the user opens the lab's app and
   adds **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect**
   in the **Products tab**.
3. In the **Auth tab**, the user copies the **Client ID** and **Client
   Secret**, and registers the redirect URI
   `http://localhost:8080/callback` in the app's auth settings (a
   loopback address, so the sign-in returns to the user's own machine).
   LinkedIn's help says to add redirect URLs "via HTTPS" and does not
   say whether `http://localhost` is accepted; when LinkedIn refuses
   that address the sign-in verb's `redirect-uri` input takes an
   `https` address instead.
4. The user stores the app credentials, each from a hidden prompt, never
   pasted in chat: `facet secret set linkedin-member client-id` and
   `facet secret set linkedin-member client-secret`.
5. The user runs `facet auth login linkedin-member` (or
   `facet auth linkedin-member`) in their own terminal. It opens the
   sign-in address with scopes `openid profile w_member_social`, exchanges
   the code for an access token (and optional refresh token), reads
   `/v2/userinfo`, and stores `access-token`, `member-id` (the `sub`
   field), and `refresh-token` if issued.
6. The user confirms with `facet doctor linkedin-member --full`: it
   checks the stored secrets (treating `refresh-token` as optional, since
   self-serve apps may not receive one) and calls `/v2/userinfo` to
   report the signed-in member's name.

Usual failures: `client-id is not stored` (or `access-token` /
`member-id`) means a step was skipped — store the app values and run
`facet auth login linkedin-member`. Access tokens last 60 days; when a
token expires and no `refresh-token` is stored, the runner stops and
instructs `facet auth logout linkedin-member` then
`facet auth login linkedin-member`. An image refused means the file
breaks the format or 36 152 320-pixel cap: convert or shrink it and send
again.

## Judging the result

The dry run answers one entry with `text`, `account` as `@not-read` (it
sends nothing), the image paths, `warnings` and `cost` (null), plus
group lines noting that the piece publishes on the owner's personal
LinkedIn profile as PUBLIC, that accepted posts are public at once, and
that a receipt is never re-sent.

A real run answers the receipt's `post` object — network
`linkedin-member`, the member's display name, state `published` (or
`unknown` with a warning if LinkedIn refuses the read-back as
forbidden), one `{id, url}` entry with the `x-restli-id` Post ID and its
feed URL, and `cost` null — and facet writes the receipt.

`verify` reads the created post back and passes when LinkedIn returns it
with matching text and media count, or reports `unknown` with a warning
when LinkedIn refuses the read-back as forbidden.

`preview` writes the post schema's preview beside the receipt: the text
in `posts[0].text`, the feed URL, the receipt's state, network
`linkedin-member` and the member's account name.

## Pitfalls

- **Publishes to the owner's own profile under their name.** Always
  confirm with the user and run `--dry-run` before sending.
- **Organization vs personal.** Use `linkedin` for the organization page
  and `linkedin-member` for the personal profile; they authenticate
  separately.
- **No refresh token on self-serve apps.** Self-serve apps may not
  receive a `refresh-token`; access tokens last 60 days, after which
  re-authentication is required.
- **Forbidden read-back.** If the member scope does not allow reading
  posts back, `run` keeps the URN and feed URL with state `unknown` and
  a warning — do not re-send!
- **Public at once, no drafts.** Whatever LinkedIn accepts is visible
  immediately; there is no inbox to review it in.
- **Never re-send a receipt.** A real upload is not retried over an
  existing receipt; removing a receipt to force one posts a duplicate.

Sources for these rules, with their licences, are in
`references/sources.md`.
