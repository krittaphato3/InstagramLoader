"""Pydantic schemas shared by the HTTP API.

Posts are grouped: one PostOut = one Instagram post, containing one or more
media items (a carousel's children become items inside a single post). The
resolve response is paginated so a profile with hundreds of posts loads its
first page quickly and streams the rest on demand.
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
    """A single media file inside a post (one row of a carousel)."""

    id: str
    media_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    is_video: Optional[bool] = None
    type: Optional[MediaType] = None  # populated by fallback helpers; grouped posts carry it on PostOut instead
    # The fallback (embed/oEmbed) path still attaches post-level metadata here;
    # `_items_to_posts` copies these onto the grouped PostOut.
    caption: Optional[str] = None
    timestamp: Optional[str] = None
    source_url: Optional[str] = None
    likes: Optional[int] = None
    comments: Optional[int] = None


class PostOut(BaseModel):
    """One Instagram post (image, video/reel, or multi-item carousel)."""

    id: str  # shortcode
    type: MediaType  # post | reel | story
    caption: Optional[str] = None
    timestamp: Optional[str] = None
    source_url: Optional[str] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    is_video: Optional[bool] = None  # True for a standalone reel
    media_count: int = 1
    thumbnail_url: Optional[str] = None  # first item's thumbnail (grid tile)
    items: List[ItemOut] = Field(default_factory=list)


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
    """POST /api/resolve response (first page) + GET .../more (next page)."""

    session_id: Optional[str] = None
    input_type: InputType
    username: Optional[str] = None
    profile: Optional[ProfileInfo] = None
    posts: List[PostOut] = Field(default_factory=list)
    stories: List[PostOut] = Field(default_factory=list)
    stories_status: Optional[str] = None
    has_more: bool = False
    page: int = 0


class DownloadItem(BaseModel):
    """One selected media file sent to /api/download (a flattened item)."""

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
    """GET /api/status/{job_id} response."""

    job_id: str
    status: str
    progress: int = 0
    completed: int = 0
    failed: int = 0
    total: int = 0
    zip_url: Optional[str] = None
    error: Optional[str] = None
