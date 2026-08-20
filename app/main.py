"""FastAPI application: API endpoints + static frontend host.

Endpoints
    POST /api/resolve                         detect input type and list media
    POST /api/download                        start a download job
    GET  /api/status/{job_id}                 poll job progress
    GET  /api/download/{job_id}/zip           download the generated ZIP

The static frontend lives in ./frontend and is mounted at "/".
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .jobs import jobs
from .config import ALLOWED_ORIGINS, DOWNLOAD_DIR, REQUEST_TIMEOUT, USER_AGENT
from .downloader import download_item
from .errors import AppError, DownloadError
from .models import (
    DownloadItem,
    DownloadRequest,
    DownloadResponse,
    ResolveRequest,
    ResolveResponse,
    SingleDownloadRequest,
    StatusResponse,
)
from .resolver import resolver

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "front"

app = FastAPI(title="Instagram Media Downloader", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(_, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/resolve", response_model=ResolveResponse)
def resolve(body: ResolveRequest) -> ResolveResponse:
    """Classify the input and return publicly available media, if any."""
    return resolver.resolve(body.input)


@app.post("/api/resolve/more", response_model=ResolveResponse)
def resolve_more(body: ResolveRequest) -> ResolveResponse:
    """Return the next page of posts for an open profile session.

    `body.input` carries the session_id returned by the first /api/resolve.
    """
    return resolver.resolve_more(body.input)


@app.post("/api/download", response_model=DownloadResponse)
def start_download(body: DownloadRequest) -> DownloadResponse:
    """Create a download job for the selected items and return its id."""
    job_id = jobs.create(body.items, body.username)
    return DownloadResponse(job_id=job_id, status="started")


@app.post("/api/download/single")
def download_single(body: SingleDownloadRequest):
    """Download ONE media item and return it directly as a file."""
    target_dir = Path(DOWNLOAD_DIR) / "single"
    item = DownloadItem(
        id=body.id,
        type=body.type,
        media_url=body.media_url,
        timestamp=body.timestamp,
    )
    try:
        outcome = download_item(item, target_dir)
    except DownloadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    filename = Path(outcome["filepath"]).name
    return FileResponse(outcome["filepath"], filename=filename, media_type="application/octet-stream")


@app.get("/api/status/{job_id}", response_model=StatusResponse)
def status(job_id: str) -> StatusResponse:
    """Return live progress for a download job (or all-active summary)."""
    record = jobs.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    return StatusResponse(**record)


@app.get("/api/download/{job_id}/zip")
def download_zip(job_id: str):
    """Send the finished ZIP for a completed job."""
    record = jobs.get(job_id)
    if record is None or record["status"] != "completed" or not record.get("zip_url"):
        raise HTTPException(status_code=404, detail="ZIP is not ready yet.")
    zip_path = DOWNLOAD_DIR / f"job_{job_id}.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="ZIP file is missing.")
    return FileResponse(zip_path, filename=f"instagram_download_{job_id}.zip", media_type="application/zip")


@app.get("/api/proxy")
def proxy(url: str):
    """Stream a remote media file with no CORP/CORS block.

    Instagram's CDN serves `Cross-Origin-Resource-Policy: same-origin`, so a
    browser page served from 127.0.0.1 cannot display those images/videos
    directly (ERR_BLOCKED_BY_RESPONSE.NotSameOrigin). We fetch the media
    server-side and relay it as the same origin. Only Instagram CDN hosts are
    allowed, so this is not an open proxy.
    """
    if not url:
        raise HTTPException(status_code=400, detail="Missing url.")
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    allowed = host.endswith(".fbcdn.net") or host.endswith(".cdninstagram.com")
    if not allowed:
        raise HTTPException(status_code=400, detail="Only Instagram CDN media can be proxied.")

    try:
        resp = httpx.get(
            url,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not fetch media.") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Media unavailable.")

    media_type = resp.headers.get("content-type") or "application/octet-stream"
    return Response(
        content=resp.content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# Expose landing page + static assets last so API routes win.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")