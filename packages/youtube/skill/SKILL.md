---
name: youtube
description: Upload one video to the lab's YouTube brand channel through the YouTube Data API, private by default, with a read-back check.
---
# youtube

`youtube.upload` uploads one video to the lab's YouTube brand channel and
reads it back. Videos reach YouTube through the Data API, with no browser
automation. Uploads land private by default so the user can publish them with
one click. The capability sets the synthetic-media disclosure from facet's
provenance of the source video: a piece can force it on, but a generated
source cannot turn it off. Unverified API projects can upload public or
unlisted videos; uploads have their own quota.

## When to use

- When the lab publishes a video or a Short to its brand channel from facet,
  with the metadata, privacy, category, tags and a made-for-kids answer set in
  the piece.
- When a dry run must come first: `facet run <piece> --dry-run` shows the
  metadata as it will be sent, the privacy and the synthetic flag, warns when
  a title or description exceeds the limits, and warns when a vertical video
  no longer than 180 s will become a Short. It sends nothing.
- When an optional thumbnail should be attached after the upload.
- When another network or another YouTube action is asked for, leave this
  package alone: it only uploads one video and reads it back. It never manages
  playlists, captions, scheduled publish times, live streams, comments or
  analytics.

## Pieces

```toml
capability = "youtube.upload"

[inputs]
video = "banco.mp4"
title = "La escuadra del laboratorio"
description = "La escuadra de aluminio recién salida del banco de trabajo."
tags = [{ tag = "taller" }, { tag = "escuadra" }]
category = "28"
privacy = "private"
made-for-kids = false
thumbnail = "portada.jpg"
notify-subscribers = true
```

`video` is the file to upload. `title` holds at most 100 characters and
`description` at most 5000. `tags` is an optional list of tag objects, each with a `tag` string. `category`
is the numeric `categoryId` string from YouTube's fixed category table.
`privacy` is `private`, `unlisted` or `public` and defaults to `private`.
`made-for-kids` is required with no default. `thumbnail` is optional and is
uploaded after the video. `notify-subscribers` defaults to `true`. `synthetic`
defaults to `false`; facet's provenance of the source video always discloses a
generated source even when this is `false`.

The bundled `examples/upload.toml` is the same shape with its clip beside it;
dry-run it with `facet run upload.toml --dry-run`.

## Authentication

The agent never handles a secret: it never asks the user to paste one into the
conversation, and it never runs `facet secret set` or `facet auth` with a
value. Connecting the account is the user's own work in their own terminal, in
this order:

1. The user creates the lab's own Google Cloud project (or chooses an existing
   one) in the Google Cloud Console and enables the **YouTube Data API v3** for
   it.
2. The user configures the **OAuth consent screen** for the project as a
   desktop application flow and creates an **OAuth client ID** of type
   **Desktop app**. The consent screen must be moved out of **Testing** status:
   refresh tokens issued to an app left in Testing stop working after a few
   days. If the app is not verified for production, publish it so the brand
   account can authorize it without the testing expiry.
3. The user stores the two client values the manifest declares, one command
   each, typed in their own terminal — each command reads the value from a
   hidden prompt, so it never rides a command line:
   `facet secret set youtube client-id` and
   `facet secret set youtube client-secret`.
4. The user runs `facet auth youtube` in their own terminal. It opens the
   installed-app sign-in on a loopback port and stores the refresh token and
   client details through facet's secrets store. At sign-in the user must pick
   the **brand channel** that will receive the uploads, not a personal channel.
5. The user confirms with `facet doctor post --full`: it reports which channel
   the token belongs to (title and handle) and whether the refresh token still
   works, so an upload never lands on an unexpected channel.

Usual failures: `client-id is not stored`, `client-secret is not stored` or
`refresh-token is not stored` means a step was skipped — store the client
values and run `facet auth youtube` again. A refresh token that stops working
after a few days means the OAuth consent screen was left in **Testing**; move
it out of Testing and run `facet auth youtube` again. If the doctor or the
upload shows the wrong channel, sign in again and pick the brand channel at the
account chooser. A thumbnail upload that fails on an unverified channel keeps
the video and the receipt and adds a warning; verify the channel in YouTube
Studio to enable custom thumbnails. Quota errors mean the daily upload quota is
exhausted.

## Judging the result

The dry run answers one entry with the rendered text (title and description),
the `account` as `@not-read` (it sends nothing), the media paths, `warnings`
and `cost` (null), plus group lines with the privacy, synthetic flag,
made-for-kids answer, category, tags and notify-subscribers choice. Read the
warnings before confirming: an over-long title or description, or a vertical
video no longer than 180 s that will become a Short, is reported here.

A real run answers the receipt's `post` object — network `youtube`, the
channel account, state `private` or `published` (public or unlisted), one
`{id, url}` entry and `cost` null — and facet writes the receipt. If a
thumbnail upload fails the video and receipt are kept and a warning is added.

`verify` reads the video back and checks that it exists, that its privacy
matches the receipt, and that processing did not fail or reject it.

`preview` writes the post schema's preview beside the receipt: the title and
description in `posts[0].text`, the state from the receipt, network `youtube`
and the channel account.

## Pitfalls

- **Private by default.** Uploads land private unless the piece sets
  `privacy` to `unlisted` or `public`; publish from YouTube when ready.
- **Made for kids is required.** The piece must answer `made-for-kids`
  explicitly; there is no default.
- **Synthetic media follows provenance.** A generated source always discloses
  synthetic media; `synthetic = true` can force disclosure on, but cannot turn
  it off for a generated source.
- **Pick the brand channel.** At sign-in choose the brand channel; confirm it
  with `facet doctor post --full` so an upload never lands on an unexpected
  channel.
- **Testing consent screens expire.** A refresh token from an app left in
  Testing stops working after a few days; move the consent screen out of
  Testing.
- **Thumbnails need a verified channel.** A failed thumbnail upload keeps the
  video and receipt and adds a warning instead of failing the send.
- **Never re-send a receipt.** A real upload is not retried over an existing
  receipt; removing a receipt to force one risks a duplicate upload.

Sources for these rules, with their licences, are in
`skill/references/sources.md`.
