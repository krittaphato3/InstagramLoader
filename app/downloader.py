"""Download selected media into a categorized folder tree, plus ZIP + manifest.

Folder layout (per spec):

    downloads/<job_id>/<username>/posts/...
    downloads/<job_id>/<username>/reels/...
    downloads/<job_id>/<username>/stories/...
    downloads/<job_id>/<username>/metadata/manifest.json

Each item is handled independently; one failed download never aborts the job.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from .config import DOWNLOAD_DIR, REQUEST_TIMEOUT, USER_AGENT
from .errors import DownloadError
from .models import DownloadItem, MediaType

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(value: str, fallback: str = "item") -> str:
    """Turn a value into a filesystem-safe path segment."""
    cleaned = _SAFE_RE.sub("-", (value or "").strip())
    cleaned = cleaned.strip("._-")
    cleaned = cleaned[:80]
    return cleaned or fallback


def _extension(item: DownloadItem, content_type: Optional[str]) -> str:
    """Pick a sensible file extension from media type + response content type."""
    ct = (content_type or "").lower()
    if item.type is MediaType.reel:
        return "mp4"
    if "png" in ct:
        return "png"
    if "jpeg" in ct or "image/jpg" in ct:
        return "jpg"
    if "webp" in ct:
        return "webp"
    if "video" in ct or "audio" in ct:
        return "mp4"
    if "image" in ct:
        return "jpg"
    return "jpg"


def download_item(item: DownloadItem, target_dir: Path) -> Dict[str, str]:
    """Download one item into target_dir. Raises DownloadError on failure."""
    media_url = item.media_url
    if not media_url:
        raise DownloadError("No direct media URL was available for this item.")

    try:
        with httpx.stream(
            "GET",
            media_url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            ext = _extension(item, content_type)
            stamp = ""
            if item.timestamp:
                # ISO timestamp -> "2026-03-06_11-01-34" (no colons, no tz).
                stamp = (item.timestamp[:19] or "").replace("T", "_").replace(":", "-")
            filename = f"{safe_filename(item.id, 'item')}_{safe_filename(stamp, 'date')}.{ext}"
            filepath = target_dir / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
    except (httpx.HTTPError, OSError) as exc:
        raise DownloadError(f"Could not fetch media: {exc}") from exc

    return {"id": item.id, "filename": filename, "filepath": str(filepath)}


def ensure_job_dir(job_id: str) -> Path:
    job_dir = DOWNLOAD_DIR / f"job_{job_id}"
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def user_root(job_dir: Path, username: Optional[str]) -> Path:
    user = safe_filename(username, "unknown_user")
    root = job_dir / user
    for folder in ("posts", "reels", "stories", "metadata"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    return root


def folder_for(root: Path, item_type: MediaType) -> Path:
    return root / f"{item_type.value}s"


def write_manifest(root: Path, meta: dict, entries: List[dict]) -> Path:
    manifest = {
        "meta": meta,
        "items": entries,
        "status": {
            "total": len(entries),
            "success": sum(1 for e in entries if e["status"] == "success"),
            "failed": sum(1 for e in entries if e["status"] == "failed"),
        },
    }
    path = root / "metadata" / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def create_zip(job_dir: Path, zip_path: Path) -> Path:
    """Zip the downloaded folder tree, skipping the zip output itself."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(job_dir.rglob("*")):
            if file == zip_path or not file.is_file():
                continue
            zf.write(file, file.relative_to(job_dir))
    return zip_path