"""Pydantic schemas shared by the HTTP API.

These mirror the documented request/response contract in the README so the
frontend and backend stay in sync without drifting.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class InputType(str, Enum):
    """What the user pasted: a specific item or a whole profile."""

    post = "post"
    reel = "reel"
    profile = "profile"
    username = "username"


class MediaType(str, Enum):
    """Category of a media item, used for folder placement and badges."""

    post = "post"
    reel = "reel"
    story = "story"


class ResolveRequest(BaseModel):
    """POST /api/resolve body: the raw post/reel/profile link or username."""

    input: str = Field(..., min_length=1, description="Post link, reel link, profile link, or username")


class ItemOut(BaseModel):
    """A single media item returned by /api/resolve."""

    id: str
    type: MediaType
    thumbnail_url: Optional[str] = None
    media_url: Optional[str] = None
    caption: Optional[str] = None
    timestamp: Optional[str] = None
    source_url: Optional[str] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    is_video: Optional[bool] = None


class ProfileInfo(BaseModel):
    """Instagram-style profile header data (avatar, stats, bio)."""

    username: str
    full_name: Optional[str] = None
    bio: Optional[str] = None
    followers: Optional[int] = None
    following: Optional[int] = None
    post_count: Optional[int] = None
    profile_pic_url: Optional[str] = None
    is_private: bool = False


class ResolveResponse(BaseModel):
    """POST /api/resolve response."""

    input_type: InputType
    username: Optional[str] = None
    profile: Optional[ProfileInfo] = None
    items: List[ItemOut] = Field(default_factory=list)
    stories: List[ItemOut] = Field(default_factory=list)
    stories_status: Optional[str] = None  # "ok" | "login_required" | "none" | "unavailable"


class DownloadItem(BaseModel):
    """One selected item sent to /api/download."""

    id: str
    type: MediaType
    media_url: Optional[str] = None
    source_url: Optional[str] = None
    caption: Optional[str] = None
    timestamp: Optional[str] = None


class DownloadRequest(BaseModel):
    """POST /api/download body."""

    items: List[DownloadItem] = Field(..., min_length=1)
    username: Optional[str] = None


class DownloadResponse(BaseModel):
    """POST /api/download response: job started."""

    job_id: str
    status: str = "started"


class SingleDownloadRequest(BaseModel):
    """POST /api/download/single body: download one item as a file."""

    id: str
    type: MediaType
    media_url: Optional[str] = None
    timestamp: Optional[str] = None
    is_video: Optional[bool] = None


class StatusResponse(BaseModel):
    """GET /api/status/{job_id} response (also returned by /api/status)."""

    job_id: str
    status: str
    progress: int = 0
    completed: int = 0
    failed: int = 0
    total: int = 0
    zip_url: Optional[str] = None
    error: Optional[str] = None