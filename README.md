# Instagram Media Downloader

Full-stack web app for downloading **public** Instagram posts, reels, and stories.

> **Compliance:** This tool only works with public content, your own content, or content
> you have permission to access. It does **not** bypass private accounts, login walls,
> paywalls, DRM, or Instagram's security protections. Unavailable/private/rate-limited
> content shows a clear error instead of being bypassed.

## Stack

- **Backend:** Python 3.11+, FastAPI, httpx, yt-dlp, zipfile
- **Frontend:** HTML + CSS + JS (served by FastAPI)

## Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| POST | `/api/resolve` | Detect input type and list available media |
| POST | `/api/download` | Start a download job for selected items |
| GET  | `/api/status/{job_id}` | Poll job progress |
| GET  | `/api/download/{job_id}/zip` | Download the generated ZIP |

*(Detailed build instructions and file layout land with the implementation.)*