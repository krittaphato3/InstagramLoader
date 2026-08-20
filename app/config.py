"""Application configuration loaded from environment variables (.env supported)."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Directory where downloaded files and ZIPs are stored.
# Relative to the project root unless an absolute path is provided.
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", str(BASE_DIR / "downloads"))).resolve()

# Local web origin(s) the backend will allowfulfill CORS from. Comma-separated.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if o.strip()
]

# Per-request user agent; keeps requests looking like a normal browser to
# reduce the chance of being flagged, without bypassing any protections.
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
)

# Overall time budgets for network operations (seconds).
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "20"))
