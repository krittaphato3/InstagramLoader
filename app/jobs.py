"""In-memory job manager that runs downloads in a background thread.

A job holds progress state readable via /api/status. State is intentionally
in-memory (per spec "local-only storage mode" is default); restarting the
server clears active jobs. The manifest.json persists the record permanently.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .downloader import (
    create_zip,
    download_item,
    ensure_job_dir,
    folder_for,
    user_root,
    write_manifest,
)
from .errors import DownloadError
from .models import DownloadItem, MediaType


class JobManager:
    """Tracks download jobs and owns their lifecycle."""

    def __init__(self) -> None:
        self._jobs: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, items: List[DownloadItem], username: Optional[str]) -> str:
        job_id = uuid.uuid4().hex[:12]
        record = {
            "job_id": job_id,
            "status": "pending",
            "progress": 0,
            "completed": 0,
            "failed": 0,
            "total": len(items),
            "zip_url": None,
            "error": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._jobs[job_id] = record
        # Worker thread; one failed item never stops the loop.
        threading.Thread(target=self._run, args=(job_id, list(items), username), daemon=True).start()
        return job_id

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            return dict(self._jobs.get(job_id, {}))

    # ------------------------------------------------------------------ #
    def _run(self, job_id: str, items: List[DownloadItem], username: Optional[str]) -> None:
        record = self._jobs[job_id]
        record["status"] = "downloading"

        try:
            job_dir = ensure_job_dir(job_id)
            root = user_root(job_dir, username)
            entries: List[dict] = []

            for idx, item in enumerate(items, start=1):
                target = folder_for(root, item.type)
                try:
                    outcome = download_item(item, target)
                    entries.append(
                        {
                            "id": item.id,
                            "type": item.type.value,
                            "source_url": item.source_url,
                            "caption": item.caption,
                            "timestamp": item.timestamp,
                            "downloaded": outcome["filename"],
                            "status": "success",
                            "error": None,
                        }
                    )
                    with self._lock:
                        record["completed"] += 1
                except DownloadError as exc:
                    entries.append(
                        {
                            "id": item.id,
                            "type": item.type.value,
                            "source_url": item.source_url,
                            "caption": item.caption,
                            "timestamp": item.timestamp,
                            "downloaded": None,
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
                    with self._lock:
                        record["failed"] += 1

                with self._lock:
                    record["progress"] = round(idx / len(items) * 80)

            # Persist the manifest.
            with self._lock:
                record["status"] = "zipping"
            meta = {
                "input": username or "",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "selected": len(items),
            }
            write_manifest(root, meta, entries)

            if record["completed"] > 0:
                zip_path = job_dir.with_suffix(".zip")
                create_zip(job_dir, zip_path)
                with self._lock:
                    record["zip_url"] = f"/api/download/{job_id}/zip"
                    record["progress"] = 100
                    record["status"] = "completed"
            else:
                with self._lock:
                    record["status"] = "failed"
                    record["error"] = "No items could be downloaded."
        except Exception as exc:  # noqa: BLE001 - keep job marked failed instead of crashing
            with self._lock:
                record["status"] = "failed"
                record["error"] = str(exc)


# Reusable singleton.
jobs = JobManager()