# Instagram Media Downloader

Full-stack web app for downloading **public** Instagram posts, reels, and stories.

> **Compliance:** This tool only works with public content, your own content, or content
> you have permission to access. It does **not** bypass private accounts, login walls,
> paywalls, DRM, or Instagram's security protections. Unavailable/private/rate-limited
> content shows a clear error instead of being bypassed. See [SECURITY & COMPLIANCE](#security--compliance).

## Stack

- **Backend:** Python 3.11+, FastAPI, httpx, instaloader, zipfile (stdlib)
- **Frontend:** Plain HTML + CSS + JS served by FastAPI (no build step)

## Resolver: how public content is fetched

Resolution tries, in order (all **public / anonymous** — nothing logs in or
bypasses a login wall):

1. **instaloader** (the spec's preferred public-instagram library) — fetches
   posts, reels, carousel children, captions, and timestamps anonymously from
   ordinary residential IPs. Verified working for profiles and single posts.
2. Official **oEmbed** API (`api.instagram.com/oembed`) — thumbnail/caption.
3. Public **embed page** (`/p/<code>/embed/`) — parses the
   `window.__additionalDataLoaded` payload for real `display_url`/`video_url`.
4. Main page `og:` metas as a last resort.

If Instagram serves a logged-out "log in" shell (common from datacenter/VPN/
cloud IPs), the app raises a clear `requires login` error instead of bypassing
it.

## File layout

```
app/
  __init__.py
  config.py        # env-driven settings (download dir, CORS, timeouts)
  errors.py        # typed, user-facing error classes
  models.py        # Pydantic request/response models (the API contract)
  resolver.py      # input classification + public media resolution
  downloader.py    # per-item download, folder tree, manifest, zip
  jobs.py          # background job manager + progress state
  main.py          # FastAPI app, routes, static mounting
front/
  index.html       # landing page
  styles.css       # UI styling (light + dark mode)
  app.js           # fetch, grid, filters, selection, polling
run.py             # dev entrypoint: uvicorn
requirements.txt
.env.example
downloads/         # created at runtime (gitignored)
```

## Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| POST | `/api/resolve` | Detect input type, list available public media |
| POST | `/api/download` | Start a download job for selected items |
| GET  | `/api/status/{job_id}` | Poll job progress + completion |
| GET  | `/api/download/{job_id}/zip` | Download the generated ZIP |

### `POST /api/resolve`
```json
{ "input": "post link / reel link / profile link / username" }
```
```json
{
  "input_type": "post | reel | profile | username",
  "username": "username if known",
  "items": [ { "id", "type", "thumbnail_url", "media_url", "caption", "timestamp", "source_url" } ]
}
```

### `POST /api/download`
```json
{ "items": [ { "id", "type", "media_url", "source_url" } ], "username": "optional" }
```
→ `{ "job_id": "...", "status": "started" }`

### `GET /api/status/{job_id}`
→ `{ "job_id", "status", "progress", "completed", "failed", "total", "zip_url" }`

### `GET /api/download/{job_id}/zip`
Returns the finished ZIP file.

## Download folder structure

```
downloads/
  job_<id>/
    <username>/
      posts/    <post_id>_<date>.jpg/mp4
      reels/    <reel_id>_<date>.mp4
      stories/  <story_id>_<date>.jpg/mp4
      metadata/
        manifest.json        # per-item success/failure + error messages
```

## Getting started

1. **Install dependencies**
   ```bash
   python -m pip install -r requirements.txt
   ```

2. **(Optional) configure** — copy `.env.example` to `.env` and adjust:
   ```bash
   cp .env.example .env
   ```

3. **Run**
   ```bash
   python run.py
   ```
   or:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

4. **Open** <http://127.0.0.1:8000>

## Sample inputs

- Post: `https://www.instagram.com/p/ABC123/`
- Reel: `https://www.instagram.com/reel/ABC123/`
- Profile: `https://www.instagram.com/someuser/`
- Username: `someuser` (leading `@` and extra spaces are cleaned)

## Notes on media URLs

Resolving *downloadable* `media_url` for arbitrary public content depends on what
Instagram's anonymous pages expose at fetch time. The app is honest about this:
anything that requires login, or that the public page does not surface, is reported
as a clear error or a failed item — never bypassed.

## Security & compliance

- Public, authenticated-free content only.
- No password storage, no private-account access, no login-wall bypass.
- Respects rate limits, copyright, and user privacy.
- A single failed item never aborts the whole job.

## Sample test inputs

Use small, public test accounts (or your own public posts). Anonymous access to
posts may require the content to be publicly shareable. If a fetch returns
"Instagram requires login", that is working as intended for this privacy-respecting app.