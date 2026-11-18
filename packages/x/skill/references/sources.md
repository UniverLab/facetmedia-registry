# x sources

One row per source the skill text relies on, with the URL, maintainer and
licence as the research report states them, and what was taken from it.

| Source | Maintainer | Licence | Taken |
| --- | --- | --- | --- |
| https://docs.x.com/x-api/getting-started/pricing | X Corp | none stated (docs.x.com, facts only, no wording taken) | The facts that a post costs $0.015, a post carrying a URL costs $0.200, a post read costs $0.005 per resource, a user read costs $0.010 per resource, credits are bought upfront in the Developer Console, and a refused run with no other change means the credits ran out. |
| https://docs.x.com/fundamentals/counting-characters | X Corp | none stated (docs.x.com, facts only, no wording taken) | The facts that posts hold 280 weighted characters, most characters count once, emoji and CJK count twice, one emoji sequence counts once, text is normalized to NFC, every URL wrapped by t.co counts as 23 whatever its length, and media counts as zero. |
| https://docs.x.com/x-api/posts/create-post | X Corp | none stated (docs.x.com, facts only, no wording taken) | The facts that a post is created with POST /2/tweets carrying text, media ids and a reply reference, a post may carry up to four photos, one animated GIF or one video, and the answer carries the post id. |
| https://docs.x.com/x-api/posts/get-posts-by-ids | X Corp | none stated (docs.x.com, facts only, no wording taken) | The facts that posts are read back with GET /2/tweets by ids with text and attachments fields, which is how the read-back checks text and media count, and that the returned text carries t.co links and may append a media link, which is why URLs are left out before comparing. |
| https://docs.x.com/x-api/media/quickstart/media-upload-chunked | X Corp | none stated (docs.x.com, facts only, no wording taken) | The facts that a chunked upload runs INIT, APPEND, FINALIZE and then STATUS when processing is reported, that APPEND takes indexed chunks, and that the v2 status read waits until a video or GIF is ready. The package drives the equivalent v1.1 commands on upload.x.com because that host is the one that takes the app's OAuth 1.0a keys; alt text rides a separate metadata call. |
| https://docs.x.com/fundamentals/authentication/oauth-1-0a/api-key-and-secret | X Corp | none stated (docs.x.com, facts only, no wording taken) | The facts that the API key and secret identify the developer app, are shown once when it is created, and ride with the user access token and secret on requests needing user context. |
