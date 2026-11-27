# youtube sources

One row per source the skill and runner rely on, with the URL, maintainer and
licence as stated, and what was taken from it.

| Source | Maintainer | Licence | Taken |
| --- | --- | --- | --- |
| https://developers.google.com/youtube/v3/docs/videos/insert | Google LLC | none stated (developers.google.com, facts only, no wording taken) | The facts that `videos.insert` uploads a video with `snippet` and `status` parts, accepts `notifySubscribers`, returns the video resource with its id, supports resumable uploads for large files, and that uploads have their own quota of 100 per day (with projects no longer locked to private by verification). |
| https://developers.google.com/youtube/v3/docs/videos/list | Google LLC | none stated (developers.google.com, facts only, no wording taken) | The facts that `videos.list` reads a video by id with `status` and `processingDetails` parts, returning `privacyStatus`, `uploadStatus` and `processingStatus` used to verify the upload. |
| https://developers.google.com/youtube/v3/docs/thumbnails/set | Google LLC | none stated (developers.google.com, facts only, no wording taken) | The fact that `thumbnails.set` uploads a custom thumbnail for a video and can be refused when the channel is not verified, which is why a failed thumbnail keeps the video and receipt with a warning. |
| https://developers.google.com/youtube/v3/guides/auth/installed-apps | Google LLC | none stated (developers.google.com, facts only, no wording taken) | The facts that an installed (desktop) application uses an OAuth client of type Desktop app, obtains consent through a loopback redirect, and exchanges the authorization for tokens including a refresh token when requested with offline access and consent. |
| https://developers.google.com/identity/protocols/oauth2#expiration | Google LLC | none stated (developers.google.com, facts only, no wording taken) | The fact that a refresh token issued while the OAuth consent screen is in Testing expires after a short period, so the consent screen must be moved out of Testing for a durable connection. |

## Craft references

Hook and repurposing guidance in this skill was informed by the
[marketingskills social skill](https://github.com/coreyhaines31/marketingskills/tree/main/skills/social)
(MIT licence, no wording copied), adapted in facetMedia's own voice.
