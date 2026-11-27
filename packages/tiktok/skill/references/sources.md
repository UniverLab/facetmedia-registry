# tiktok sources

One row per source the skill and runner rely on, with the URL, maintainer
and licence as stated, and what was taken from it.

| Source | Maintainer | Licence | Taken |
| --- | --- | --- | --- |
| https://developers.tiktok.com/doc/content-posting-api-get-started-upload-content/ | TikTok Pte. Ltd. | none stated (developers.tiktok.com, facts only, no wording taken) | The facts that the upload flow sends videos or photos to the user's inbox as drafts the user reviews and posts, that it needs the `video.upload` scope approved and authorized, that a video uploads from a local file with `FILE_UPLOAD` or from a verified URL with `PULL_FROM_URL`, that photos upload by URL only, and that the user must click the inbox notification to finish the post in the app. |
| https://developers.tiktok.com/doc/content-posting-api-reference-upload-video/ | TikTok Pte. Ltd. | none stated (developers.tiktok.com, facts only, no wording taken) | The facts that the inbox video init is `POST /v2/post/publish/inbox/video/init/` with a `source_info` object and no caption field, that it answers a `publish_id` plus an `upload_url` valid for one hour, that the chunk PUT carries `Content-Range` and answers 206 per chunk and 201 when done, and that `access_token_invalid` means the token expired while `scope_not_authorized` means the grant misses `video.upload`. |
| https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide/ | TikTok Pte. Ltd. | none stated (developers.tiktok.com, facts only, no wording taken) | The facts that each chunk must be 5 MB to 64 MB except a merged final chunk, that files below 5 MB upload whole and above 64 MB upload in chunks with at most 1000 sequential chunks, that videos are MP4, WebM or MOV up to 4 GiB, that photos are WebP or JPEG up to 20 MB each, that pull URLs must use https with no redirect, and that pull URLs must ride a verified domain or URL prefix. |
| https://developers.tiktok.com/doc/content-posting-api-reference-photo-post/ | TikTok Pte. Ltd. | none stated (developers.tiktok.com, facts only, no wording taken) | The facts that photos init with `POST /v2/post/publish/content/init/` carrying `media_type` PHOTO, `post_mode` MEDIA_UPLOAD for the inbox draft, a `post_info` object whose title and description are optional, and a `source_info` with `PULL_FROM_URL`, up to 35 `photo_images` URLs and a zero-based `photo_cover_index`. |
| https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status/ | TikTok Pte. Ltd. | none stated (developers.tiktok.com, facts only, no wording taken) | The facts that the status fetch is `POST /v2/post/publish/status/fetch/` with a `publish_id`, that `SEND_TO_USER_INBOX` means the draft reached the inbox, that `FAILED` carries a `fail_reason`, and that the creator-info query answers the account's username and nickname. |
| https://developers.tiktok.com/doc/content-posting-api-get-started/ | TikTok Pte. Ltd. | none stated (developers.tiktok.com, facts only, no wording taken) | The facts that direct posting to public needs the `video.publish` scope plus an audit the lab does not have, which is why this package stays on the inbox draft flow with `video.upload` only. |

## Craft references

Hook and repurposing guidance in this skill was informed by the
[marketingskills social skill](https://github.com/coreyhaines31/marketingskills/tree/main/skills/social)
(MIT licence, no wording copied), adapted in facetMedia's own voice.
