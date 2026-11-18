# bluesky sources

One row per source the skill text relies on, with the URL, maintainer and
licence as the research report states them, and what was taken from it.

| Source | Maintainer | Licence | Taken |
| --- | --- | --- | --- |
| https://docs.bsky.app/docs/bluesky-api | Bluesky Social PBC | MIT (docs-bsky-app, facts only, no wording taken) | The facts that a first post goes through `com.atproto.server.createSession` with an identifier and an app password, that blobs upload before the record that embeds them, and that a thread links each post to the previous one with `reply.parent` under a shared `reply.root`. |
| https://bsky.network/docs/bluesky-api/creating-a-post | Bluesky Social PBC | MIT (docs-bsky-app, facts only, no wording taken) | The facts that a post record carries text, createdAt, langs and facets, that a thread reply holds root and parent strong references, and that a post embeds images or one external card. |
| https://atproto.com/specs/xrpc | Bluesky Social PBC | MIT (atproto.com, facts only, no wording taken) | The fact that every call is an XRPC namespaced query or procedure over HTTP with JSON bodies, which is why the vendored client speaks plain POST and GET with no SDK. |
| https://atproto.com/specs/record-key | Bluesky Social PBC | MIT (atproto.com, facts only, no wording taken) | The fact that a repository record is addressed by its collection and record key, which is how the read-back fetches each receipt post straight from the account's server. |
| https://bsky.app/settings/app-passwords | Bluesky Social PBC | none stated (in-app settings screen, facts only, no wording taken) | The fact that an app password is created per account under Settings, Privacy and Security, and is the only credential a client stores — the account password is never used. |
