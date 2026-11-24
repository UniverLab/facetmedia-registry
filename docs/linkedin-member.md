# linkedin-member

User-facing notes for the `linkedin-member` package (`linkedin-member.post`), which posts text with images to the owner's personal LinkedIn profile through the Posts API.

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

There is no `author` input: the author is always the signed-in member (`urn:li:person:{member-id}`).

- 0 images: text-only post.
- 1 image: single-image post (the `alt` text rides as the media title).
- 2 to 20 images: `MultiImage` post. More than 20 images is refused before anything leaves.

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

In the LinkedIn Developer Portal, add **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect** in the app's **Products** tab, copy **Client ID** and **Client Secret** from the **Auth** tab, and register the loopback redirect URI `http://localhost:8080/callback`.

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

- `facet run <piece> --dry-run` validates `text` and `images` locally without network calls and reports `account = "@not-read"`.
- A real run uploads each image through the Images API with `urn:li:person:{member-id}` as the owner, creates the post with `PUBLIC` visibility, and reads it back via `GET /rest/posts/{urn}`.
- Accepted posts are public at once (LinkedIn keeps no drafts), and an existing receipt is never re-sent.
- When the read-back succeeds, the receipt state is `published`. When LinkedIn refuses the read-back as forbidden (HTTP 403), the receipt still keeps the post URN and public feed URL (`https://www.linkedin.com/feed/update/{urn}`) with state `unknown` and a warning — do not re-send.

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
