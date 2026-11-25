# linkedin-member

User-facing notes for the `linkedin-member` package (`linkedin-member.post`), which posts text with images or an MP4 video to the owner's personal LinkedIn profile through the Posts API.

## Choosing between `linkedin` and `linkedin-member`

- **`linkedin`** posts to a Company Page / organization account (`urn:li:organization:{id}`) and requires LinkedIn's organization permissions.
- **`linkedin-member`** posts to the owner's personal LinkedIn profile (`urn:li:person:{member-id}`) under their own name, using LinkedIn's self-serve **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect** products.

The two packages sign in separately, each with its own entry in `facet auth login`.

## Inputs

`linkedin-member.post` accepts:

| Input | Type | Required | Notes |
| --- | --- | --- | --- |
| `text` | string | yes | Post commentary, at most 3000 characters; URLs are unfurled into link previews |
| `images` | array | no | 0 to 20 entries, each with `path` (JPG, GIF or PNG, up to 36 152 320 pixels, resolved relative to the piece) and required `alt` text |
| `video` | path | no | One local `.mp4` file, resolved relative to the piece, non-empty and at most 500 MiB; refused together with `images` |
| `video-title` | string | no | Video attachment title; defaults to the video filename stem when omitted |

There is no `author` input: the author is always the signed-in member (`urn:li:person:{member-id}`).

- 0 images and no video: text-only post.
- 1 image: single-image post (the `alt` text rides as the media title).
- 2 to 20 images: `MultiImage` post. More than 20 images is refused before anything leaves.
- 1 video: video post (`video-title` rides as the media title, defaulting to the filename stem). `images` and `video` are mutually exclusive.

Example piece:

```toml
capability = "linkedin-member.post"

[inputs]
text = "La escuadra del laboratorio, recién salida del banco. #taller"

[[inputs.images]]
path = "banco.png"
alt = "La escuadra del laboratorio sobre el banco de trabajo."
```

## Authentication and secrets

1. **Create the app** in the LinkedIn Developer Portal using the **Create an app** form:
   - **App name** is required.
   - **LinkedIn Page**: the app must be associated with a LinkedIn Page, and the organization that owns the Page acts as the app's publisher. The Page is required and must be a Company Page you administer (not a member profile page); it cannot be changed once the app is saved, the association is permanent, the app cannot be moved to another Page, and a new Page needs new apps. A Page admin verifies the association — the Page's super admin approves the request within 30 days, and a person who created the Page is its super admin. A person with no Page creates one first with the form's **Create a new LinkedIn Page** link. The posts the package publishes appear on the member's own profile, not on the Page.
   - **App logo** is required (square recommended, at least 100 px in one dimension).
   - **Privacy policy URL** is optional, and the legal agreement must be accepted.
2. **Add products** in the app's **Products** tab: **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect**.
3. **Copy credentials and set the redirect URL** in the app's **Auth** tab (https://www.linkedin.com/developers/apps, auth settings): copy **Client ID** and **Client Secret**, and register the loopback redirect URI `http://localhost:8080/callback`. LinkedIn's help says to add redirect URLs "via HTTPS" and does not say whether `http://localhost` is accepted; when LinkedIn refuses that address, pass an `https` address to the sign-in verb's `redirect-uri` input instead.

Store the app credentials and sign in:

```sh
facet secret set linkedin-member client-id
facet secret set linkedin-member client-secret
facet auth login linkedin-member
```

`auth` opens the LinkedIn authorization URL with scopes `openid profile w_member_social` and listens on `http://localhost:8080/callback` (overridable via an optional `redirect-uri` input). After exchanging the authorization code, it calls `/v2/userinfo` and stores:

- `access-token` (required, `produced_by = "auth"`)
- `member-id` (required, `produced_by = "auth"`, from the `sub` field)
- `refresh-token` (optional, `produced_by = "auth"` — self-serve apps may not receive a refresh token)

## Dry run, posting and read-back

- `facet run <piece> --dry-run` validates `text`, `images`, and `video` locally without network calls and reports `account = "@not-read"`.
- A real run uploads each image through the Images API, or uploads an `.mp4` video through the Videos API (`initializeUpload`, chunk PUTs, `finalizeUpload`, then poll until `AVAILABLE`) with `urn:li:person:{member-id}` as the owner, creates the post with `PUBLIC` visibility, and reads it back via `GET /rest/posts/{urn}`.
- Accepted posts are public at once (LinkedIn keeps no drafts), and an existing receipt is never re-sent.
- When the read-back succeeds, the receipt state is `published`. When LinkedIn refuses the read-back as forbidden (HTTP 403), the receipt still keeps the post URN and public feed URL (`https://www.linkedin.com/feed/update/{urn}`) with state `unknown` and a warning — do not re-send. If the video status read-back is forbidden (403), the runner records a warning and proceeds to create the post.

## Token expiry and `doctor`

Access tokens last 60 days. On an expired token (`401`), the runner refreshes once if `refresh-token` is stored; otherwise it stops and instructs you to run:

```sh
facet auth logout linkedin-member
facet auth login linkedin-member
```

Check your setup with:

```sh
facet doctor linkedin-member
facet doctor linkedin-member --full
```

At `quick` depth, `doctor` checks the stored secrets (treating `refresh-token` as optional). At `--full`, it also calls `/v2/userinfo` and reports the signed-in member's name.
