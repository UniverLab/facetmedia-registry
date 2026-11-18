---
name: tiktok
description: Send one video or a photo set to the lab's TikTok account inbox as a draft, then read its publish status back.
---
# tiktok

`tiktok.post` sends one video or a photo set to the lab's TikTok account
inbox as a draft and reads its publish status back. Uploads go through
the Content Posting API with no browser automation: a local video file
uploads in chunks, a photo set is pulled by TikTok from URLs the app
owns. Every draft waits in the app's inbox for the user to finish it
with one tap. TikTok keeps no caption on an inbox draft, so the piece's
`caption` is what the user should paste in the app: it rides the dry
run, the receipt's preview and these instructions.

## When to use

- When the lab sends a video or a photo set from facet to its TikTok
  account, as a draft the user finishes in the app — with the dry run
  first: `facet run <piece> --dry-run` checks the video against TikTok's
  format and size limits, shows what will land in the inbox, and warns
  that photo URLs must ride a domain the TikTok app verified. It sends
  nothing and touches no network.
- When the piece carries one local video (`video`, MP4, WebM or MOV, at
  most 4 GiB) or a photo set (`photos`, each a `url` on a verified
  domain over https with no redirect) — exactly one of the two, never
  both, never neither.
- When another network or another TikTok action is asked for, leave this
  package alone: it only sends inbox drafts. It never posts to public
  (which needs an audit the lab does not have), never schedules, never
  touches comments or analytics.

## Pieces

```toml
capability = "tiktok.post"

[inputs]
caption = "La escuadra del laboratorio, recién salida del banco. #taller"
video = "banco.mp4"
```

`caption` is required and holds the text the user pastes in the app.
`video` is the file to upload, resolved relative to the piece. A photo
set replaces the video with one table per URL:

```toml
capability = "tiktok.post"

[inputs]
caption = "La escuadra, paso a paso."

[[inputs.photos]]
url = "https://fotos.univerlab.org/taller/escuadra-1.jpg"

[[inputs.photos]]
url = "https://fotos.univerlab.org/taller/escuadra-2.jpg"
```

The bundled `examples/inbox.toml` is the video shape with its clip
beside it; dry-run it with `facet run inbox.toml --dry-run`.

## Authentication

The agent never handles a secret: it never asks the user to paste one
into the conversation, and it never runs `facet secret set` or
`facet auth` with a value. Connecting the account is the user's own work
in their own terminal, in this order:

1. The user creates the lab's own app in the TikTok for Developers
   website and adds two products to it: **Login Kit** and the
   **Content Posting API**.
2. The user requests the **`video.upload`** scope for the app and waits
   for its approval: without the grant the sign-in cannot open the
   inbox. No Direct Post is needed — posting to public needs an audit
   the lab does not have, so the app stays unaudited and drafts stay
   drafts.
3. The user registers the redirect URI in the app's Login Kit settings:
   `http://127.0.0.1:8080/callback` (a loopback address, so the sign-in
   returns to the user's own machine).
4. For photo sets, the user verifies the domain in the app's URL
   properties (a DNS signature string, per TikTok's domain rules):
   TikTok downloads photos only from a verified domain or URL prefix,
   over https with no redirect.
5. The user runs `facet auth tiktok` in their own terminal. It opens the
   sign-in address, the user authorizes the app for the account that
   will receive the drafts, and the token pair plus the open id are
   stored through facet's secrets store.
6. The user confirms with `facet doctor post --full`: it reports which
   account the token belongs to (display name and handle) and whether
   the `video.upload` scope was granted, so a draft never lands on an
   unexpected account.

Usual failures: `client-key is not stored` (or any of the five names)
means a step was skipped — store the app values and run
`facet auth tiktok` again. A sign-in that opens the wrong account means
the user authorized a personal account instead of the lab's: run
`facet auth tiktok` again and pick the lab's account. The doctor
reporting that `video.upload` was not granted means the scope request in
step 2 is still pending or was refused: wait for approval, authorize the
scope at sign-in, and sign in again. A photo upload refused with
`url_ownership_unverified` means the photo domain is not verified in the
app: verify it per step 4 and send again. A run refused with
`access_token_invalid` after a long idle means the refresh failed:
sign in again. A video refused for its container or size means the file
breaks TikTok's format or 4 GiB limit: convert or trim it and send
again.

## Judging the result

The dry run answers one entry with the caption as `text`, the `account`
as `@not-read` (it sends nothing), the media paths or URLs, `warnings`
and `cost` (null), plus group lines naming that the piece lands in the
inbox as a draft and that the caption must be pasted in the app. Read
the warnings before confirming: a video over the size limit, a photo set
on an unverified domain, or a missing caption is reported here.

A real run answers the receipt's `post` object — network `tiktok`, the
account handle, state `draft`, one `{id, url}` entry with TikTok's
`publish_id` and the account's profile URL (a draft has no URL of its
own), and `cost` null — and facet writes the receipt. A photo URL
TikTok refuses fails the run with TikTok's reason before anything lands.

`verify` fetches the publish status and passes only when TikTok reports
`SEND_TO_USER_INBOX`: the draft reached the inbox. A `FAILED` status
fails verification with TikTok's `fail_reason`.

`preview` writes the post schema's preview beside the receipt: the
caption in `posts[0].text`, the profile URL, state `draft`, network
`tiktok` and the account, with a summary saying the draft waits in the
inbox and the caption must be pasted in the app.

## Pitfalls

- **Inbox only, never public.** Drafts wait in the app's inbox; direct
  posting to public needs an audit the lab does not have.
- **The caption rides nowhere.** The inbox flow takes no caption: the
  user pastes the piece's caption in the app.
- **The receipt URL is the profile.** A draft has no URL of its own, so
  the receipt cites the account's profile URL until the user posts it.
- **Photos need a verified domain.** TikTok downloads photo URLs only
  from a domain or URL prefix the app verified, over https.
- **Pick the lab's account.** At sign-in choose the account that will
  receive the drafts; confirm it with `facet doctor post --full` so a
  draft never lands on a personal account.
- **Never re-send a receipt.** A real upload is not retried over an
  existing receipt; removing a receipt to force one risks a duplicate
  draft.

Sources for these rules, with their licences, are in
`references/sources.md`.
