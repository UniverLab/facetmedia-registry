# youtube

Uploads one video to the lab's YouTube brand channel through the YouTube
Data API v3: `facet run youtube.upload` sends the video with its metadata,
private by default, discloses synthetic media from facet's provenance of the
source, then reads it back. It uses Google's maintained Python API and auth
libraries.

## Capability and piece

`youtube.upload` — post kind, outward:

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `video` | path | yes | — | The video file to upload |
| `title` | string | yes | — | At most 100 characters |
| `description` | string | yes | — | At most 5000 characters |
| `tags` | array | no | — | Tags, each as `{tag = "..."}` |
| `category` | string | yes | — | Numeric `categoryId` from YouTube's fixed table |
| `privacy` | enum | no | `private` | `private`, `unlisted` or `public` |
| `made-for-kids` | boolean | yes | — | Required with no default |
| `thumbnail` | path | no | — | Optional custom thumbnail, uploaded after the video |
| `notify-subscribers` | boolean | no | `true` | Whether to notify subscribers |
| `synthetic` | boolean | no | `false` | Forces the synthetic-media disclosure on; a generated source always discloses |

Credentials come from the secrets store, never the piece: `client-id`,
`client-secret` and `refresh-token` (all required). `facet auth youtube`
runs the installed-app OAuth sign-in in the user's own terminal and stores
the refresh token and client details.

## Verification and preview

`dry-run` sends nothing and writes nothing: it shows the metadata as it will
be sent (title and description), the privacy and the synthetic flag, warns
about a title or description over the limits, and warns when a vertical
video no longer than 180 s will become a Short.

`run` uploads the video resumably, sets the synthetic-media disclosure and
the made-for-kids answer, and optionally uploads a thumbnail. If the
thumbnail upload fails (for example on an unverified channel) the video and
receipt are kept and a warning is added. The receipt carries the video id,
its URL, and state `private` or `published` (public or unlisted).

`verify` reads the video back and checks that it exists, that its privacy
matches the receipt, and that processing did not fail or reject it.

`preview` writes the post schema's preview file beside the receipt with the
title and description in `posts[0].text`, the network, the account and the
state.

`facet doctor post` checks the client and the stored secrets at quick depth;
`--full` confirms the refresh token still works and reports which channel it
belongs to (title and handle).

## Licences

The YouTube Data API is a hosted service under Google's API terms, not an
open-source licence; the manifest records that. The package itself is MIT.

## Bundled examples

`facet example <capability> --run` copies the capability's example, with
every file it names, into a fresh folder and runs it there:

- `youtube.upload` — `examples/upload.toml`: `facet example youtube.upload --run`
