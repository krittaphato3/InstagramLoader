"""Resolve raw Instagram input into publicly available media items.

Primary backend: **instaloader** (the spec's preferred "instaloader or similar
library … where possible"), which is a well-known open-source client and is
able to fetch **public** content anonymously from ordinary residential IPs —
verified working from this machine for both profiles and single posts.

Fallbacks (in order), all official public endpoints that Instagram provides
for server-side/embedded access:

1. The official **oEmbed** API (``api.instagram.com/oembed``) — thumbnail,
   caption/title, and author, no login required for public posts.
2. The public **embed page** (``/p/<code>/embed/`` or ``/reel/<code>/embed/``)
   — what any site uses to embed a public post. It carries a JSON payload
   (``window.__additionalDataLoaded('extra', …)``) with the real media URL
   (``display_url`` / ``video_url``), caption, timestamp, and owner.

Nothing here logs in, bypasses a login wall, or fetches private items. When
Instagram serves an anonymous "log in" shell (e.g. from restricted or
datacenter IPs) instead of public data, we raise a typed error rather than
attempting to bypass it.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

import httpx
import instaloader

from .config import REQUEST_TIMEOUT, USER_AGENT
from .errors import (
    DeletedError,
    InvalidInputError,
    LoginRequiredError,
    NetworkError,
    PrivateAccountError,
    RateLimitError,
    UnsupportedURLError,
)
from .models import (
    InputType,
    ItemOut,
    MediaType,
    PostOut,
    ProfileInfo,
    ResolveResponse,
)

PAGE_SIZE = 12


@dataclass
class _Session:
    """A cached profile fetch used by paginated resolution."""

    username: str
    profile: instaloader.Profile
    posts_iter: object  # iterator over the profile's posts
    page: int = 0

# Match /p/ABC123 or /reel/ABC123 (also /reels/).
_SHORTCODE_RE = re.compile(r"/(?:p|reel|reels)/([A-Za-z0-9_-]{3,})")
# A bare path segment that looks like a username, e.g. /username/.
_PROFILE_PATH_RE = re.compile(r"^/([A-Za-z0-9_.]{2,30})/?$")
_USERNAME_RE = re.compile(r"^@?([A-Za-z0-9_.]{2,30})$")

_OG_IMAGE_RE = re.compile(r'property="og:image"\s+content="([^"]+)"')
_OG_TITLE_RE = re.compile(r'property="og:title"\s+content="([^"]+)"')

# Match the `window.__additionalDataLoaded('extra', <json>);` payload that
# Instagram embeds in the public post/reel embed page.
_ADDITIONAL_DATA = re.compile(r"window\.__additionalDataLoaded\(\s*[\\'\"](extra)[\\'\"],\s*")


@dataclass
class Classification:
    """Parsed, normalized interpretation of the raw user input."""

    kind: InputType
    username: Optional[str] = None
    shortcode: Optional[str] = None
    canonical_url: Optional[str] = None


def classify(raw: str) -> Classification:
    """Return a normalized classification, or raise for invalid/unsupported input."""
    raw = (raw or "").strip()
    if not raw:
        raise InvalidInputError()

    # No scheme/domain present -> treat the whole string as a username.
    if "://" not in raw and "instagram.com" not in raw:
        m = _USERNAME_RE.match(raw)
        if m:
            return Classification(kind=InputType.username, username=m.group(1))
        raise InvalidInputError()

    url = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host not in ("instagram.com", "www.instagram.com", "m.instagram.com"):
        raise UnsupportedURLError()

    path = parsed.path or "/"

    m = _SHORTCODE_RE.search(path)
    if m:
        code = m.group(1)
        kind = InputType.reel if "reel" in path else InputType.post
        return Classification(
            kind=kind,
            shortcode=code,
            canonical_url=f"https://www.instagram.com/{'reel' if kind is InputType.reel else 'p'}/{code}/",
        )

    stripped = path.rstrip("/")
    m = _PROFILE_PATH_RE.match(stripped)
    if m:
        username = m.group(1)
        if username.lower() in {"p", "reel", "reels", "explore", "accounts", "share"}:
            raise UnsupportedURLError()
        return Classification(
            kind=InputType.profile,
            username=username,
            canonical_url=f"https://www.instagram.com/{username}/",
        )

    raise UnsupportedURLError()


class Resolver:
    """Fetches publicly visible media for a classification (best effort)."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        # instaloader keeps a shared session that we must not race.
        self._il_lock = threading.Lock()
        self._il = None
        # Paginated resolve keeps an open post iterator per "session id".
        self._sessions: dict[str, _Session] = {}

    def close(self) -> None:
        self._client.close()

    def resolve(self, raw: str) -> ResolveResponse:
        cls = classify(raw)

        # Primary: instaloader (works anonymously on residential IPs).
        result = self._resolve_instaloader(cls)
        if result is not None:
            return result

        # Fallback: official public embed/oEmbed endpoints (return flat items,
        # which we group into posts here so the API stays consistent).
        if cls.kind in (InputType.post, InputType.reel):
            items, username = self._resolve_single(cls)
            return ResolveResponse(
                input_type=cls.kind,
                username=username or cls.username,
                posts=self._items_to_posts(items),
                stories_status="none",
            )
        items = self._resolve_profile(cls)
        return ResolveResponse(
            input_type=cls.kind,
            username=cls.username,
            posts=self._items_to_posts(items),
        )

    @staticmethod
    def _items_to_posts(items: List[ItemOut]) -> List[PostOut]:
        """Group flat fallback items (which may already be 1-per-post) into posts."""
        # The fallback returns one ItemOut per post; wrap each as a 1-item post.
        posts: List[PostOut] = []
        for it in items:
            posts.append(
                PostOut(
                    id=it.id,
                    type=MediaType.post,
                    caption=it.caption,
                    timestamp=it.timestamp,
                    source_url=it.source_url,
                    likes=it.likes,
                    comments=it.comments,
                    is_video=it.is_video,
                    media_count=1,
                    thumbnail_url=it.thumbnail_url,
                    items=[ItemOut(id=it.id, media_url=it.media_url, thumbnail_url=it.thumbnail_url, is_video=it.is_video)],
                )
            )
        return posts

    def resolve_more(self, session_id: str) -> ResolveResponse:
        """Return the next page of posts for a previously opened profile."""
        with self._il_lock:
            sess = self._sessions.get(session_id)
        if sess is None:
            raise InvalidInputError("Session expired. Please search again.")
        posts: List[PostOut] = []
        try:
            for post in sess.posts_iter:
                grouped = self._post_to_grouped(post, MediaType.post)
                if grouped is not None:
                    posts.append(grouped)
                if len(posts) >= PAGE_SIZE:
                    break
        except instaloader.InstaloaderException:
            pass
        sess.page += 1
        has_more = len(posts) == PAGE_SIZE  # may be more; best-effort flag
        return ResolveResponse(
            session_id=session_id,
            input_type=InputType.profile,
            username=sess.username,
            posts=posts,
            page=sess.page,
            has_more=has_more,
        )

    # ------------------------------------------------------------------ #
    # Primary backend: instaloader
    # ------------------------------------------------------------------ #
    def _loader(self):
        with self._il_lock:
            if self._il is None:
                self._il = instaloader.Instaloader(
                    quiet=True,
                    download_pictures=False,
                    download_videos=False,
                    download_video_thumbnails=False,
                    download_geotags=False,
                    download_comments=False,
                    save_metadata=False,
                    compress_json=False,
                    post_metadata_txt_pattern="",
                    dirname_pattern="{username}",
                )
            return self._il

    def _resolve_instaloader(self, cls: Classification) -> Optional[ResolveResponse]:
        """Return a response via instaloader, or None if it is unavailable."""
        loader = self._loader()
        try:
            if cls.kind in (InputType.post, InputType.reel):
                post = instaloader.Post.from_shortcode(loader.context, cls.shortcode or "")
                if post is None:
                    raise DeletedError()
                ptype = MediaType.reel if cls.kind is InputType.reel else MediaType.post
                grouped = self._post_to_grouped(post, ptype)
                return ResolveResponse(
                    input_type=cls.kind,
                    username=post.owner_username or cls.username,
                    profile=self._profile_info_from_post(post),
                    posts=[grouped] if grouped else [],
                    stories_status="none",
                )

            profile = instaloader.Profile.from_username(loader.context, cls.username or "")
            # Cache the post iterator so the next page is cheap.
            session_id = f"{cls.username}_{uuid.uuid4().hex[:8]}"
            sess = _Session(
                username=cls.username,
                profile=profile,
                posts_iter=profile.get_posts(),
            )
            with self._il_lock:
                self._sessions[session_id] = sess

            # Pull the first page now.
            posts: List[PostOut] = []
            for post in sess.posts_iter:
                grouped = self._post_to_grouped(post, MediaType.post)
                if grouped is not None:
                    posts.append(grouped)
                if len(posts) >= PAGE_SIZE:
                    break
            sess.page = 1
            has_more = len(posts) == PAGE_SIZE

            stories, stories_status = self._resolve_stories(loader, profile)
            return ResolveResponse(
                session_id=session_id,
                input_type=cls.kind,
                username=cls.username,
                profile=self._profile_info(profile),
                posts=posts,
                stories=stories,
                stories_status=stories_status,
                has_more=has_more,
                page=sess.page,
            )
        except instaloader.LoginRequiredException as exc:
            raise LoginRequiredError() from exc
        except instaloader.PrivateProfileNotFollowedException as exc:
            raise PrivateAccountError() from exc
        except instaloader.ProfileNotExistsException as exc:
            raise DeletedError() from exc
        except instaloader.QueryReturnedBadRequestException as exc:
            raise RateLimitError() from exc
        except instaloader.ConnectionException as exc:
            # Network refused this request; fall back to the public endpoints
            # which may still answer with oEmbed/og: data.
            return None
        except instaloader.InstaloaderException:
            # Any other library error (e.g. malformed page) — try public APIs.
            return None

    # ------------------------------------------------------------------ #
    # Stories
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_stories(loader, profile):
        """Return (story_posts, status). Story access usually needs login."""
        try:
            stories = list(loader.get_stories(userids=[profile.userid]))
        except instaloader.LoginRequiredException as exc:
            return [], "login_required"
        except instaloader.InstaloaderException as exc:
            return [], "unavailable"

        posts = []
        for story in stories:
            for it in story.get_items():
                media = it.video_url or it.url
                is_video = bool(getattr(it, "video_url", None)) or it.is_video
                posts.append(
                    PostOut(
                        id=str(it.mediaid),
                        type=MediaType.story,
                        timestamp=it.date_utc.isoformat() if it.date_utc else None,
                        is_video=is_video,
                        thumbnail_url=it.url,
                        media_count=1,
                        items=[ItemOut(id=str(it.mediaid), media_url=media, thumbnail_url=it.url, is_video=is_video)],
                    )
                )
        return posts, ("ok" if posts else "none")

    # ------------------------------------------------------------------ #
    # Profile info
    # ------------------------------------------------------------------ #
    @staticmethod
    def _profile_info(profile) -> ProfileInfo:
        return ProfileInfo(
            username=profile.username,
            full_name=getattr(profile, "full_name", None),
            bio=getattr(profile, "biography", None),
            followers=getattr(profile, "followers", None),
            following=getattr(profile, "followees", None),
            post_count=getattr(profile, "mediacount", None),
            profile_pic_url=getattr(profile, "profile_pic_url", None),
            is_private=getattr(profile, "is_private", False),
        )

    @staticmethod
    def _profile_info_from_post(post) -> Optional[ProfileInfo]:
        try:
            return ProfileInfo(
                username=post.owner_username,
                full_name=post.owner_profile.full_name if post.owner_profile else None,
                profile_pic_url=post.owner_profile.profile_pic_url if post.owner_profile else None,
            )
        except Exception:
            return None

    @staticmethod
    def _post_to_grouped(post, default_type: MediaType) -> Optional[PostOut]:
        """Convert one instaloader Post into a single grouped PostOut.

        A carousel (GraphSidecar) becomes one post with one item per child;
        a single image or video is one post with one item.
        """
        base_id = post.shortcode or str(post.mediaid)
        caption = post.caption
        timestamp = post.date_utc.isoformat() if post.date_utc else None
        source = f"https://www.instagram.com/p/{post.shortcode}/" if post.shortcode else None
        likes = getattr(post, "likes", None)
        comments = getattr(post, "comments", None)

        items: List[ItemOut] = []
        if getattr(post, "typename", "") == "GraphSidecar":
            for idx, node in enumerate(post.get_sidecar_nodes(), start=1):
                media = (node.video_url or node.display_url) if node.is_video else node.display_url
                if not media:
                    continue
                items.append(
                    ItemOut(
                        id=f"{base_id}_{idx}",
                        media_url=media,
                        thumbnail_url=node.display_url,
                        is_video=bool(node.is_video),
                    )
                )
        else:
            is_video = bool(getattr(post, "is_video", False))
            media = post.video_url or post.url
            items.append(
                ItemOut(
                    id=base_id,
                    media_url=media,
                    thumbnail_url=post.url,
                    is_video=is_video,
                )
            )
        if not items:
            return None

        is_post_video = any(it.is_video for it in items)
        # A standalone video post or any video child is surfaced under Reels.
        post_type = MediaType.reel if (is_post_video and default_type is MediaType.post) else default_type
        return PostOut(
            id=base_id,
            type=post_type,
            caption=caption,
            timestamp=timestamp,
            source_url=source,
            likes=likes,
            comments=comments,
            is_video=is_post_video,
            media_count=len(items),
            thumbnail_url=items[0].thumbnail_url,
            items=items,
        )

    # ------------------------------------------------------------------ #
    # Single post / reel
    # ------------------------------------------------------------------ #
    def _resolve_single(self, cls: Classification):
        """Return (items, username) for one post or reel, via public endpoints."""
        kind = cls.kind
        path = "reel" if kind is InputType.reel else "p"
        url = cls.canonical_url or f"https://www.instagram.com/{path}/{cls.shortcode}/"
        code = cls.shortcode or url

        # 1) Official public oEmbed API.
        oembed = self._oembed(url)
        if oembed and oembed.get("thumbnail_url"):
            item = ItemOut(
                id=code,
                type=MediaType.reel if kind is InputType.reel else MediaType.post,
                thumbnail_url=oembed.get("thumbnail_url"),
                caption=oembed.get("title"),
                media_url=oembed.get("thumbnail_url"),
                source_url=url,
            )
            return [item], self._username_from_url(oembed.get("author_url"))

        # 2) Public embed page (what embedding sites use). This is the richest
        #    anonymous source: it yields the real media URL and metadata.
        try:
            embed_resp = self._client.get(f"https://www.instagram.com/{path}/{code}/embed/")
            self._raise_for_blocked(embed_resp)
        except httpx.HTTPError as exc:
            raise self._map_http_error(exc) from exc

        payload = self._extract_payload(embed_resp.text)
        if payload is not None:
            items, username = self._payload_items(payload, code, kind, url)
            return items, username

        # 3) Fallback: main page og: metas (may be visible on some networks).
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            raise self._map_http_error(exc) from exc
        self._raise_for_blocked(resp)
        thumbnail = self._find(_OG_IMAGE_RE, resp.text)
        title = self._find(_OG_TITLE_RE, resp.text)
        if thumbnail or title:
            return (
                [
                    ItemOut(
                        id=code,
                        type=MediaType.reel if kind is InputType.reel else MediaType.post,
                        thumbnail_url=thumbnail,
                        caption=title,
                        media_url=thumbnail,
                        source_url=url,
                    )
                ],
                None,
            )

        # None of the public endpoints exposed media — Instagram served a
        # login/anonymous shell. Be honest instead of bypassing.
        raise LoginRequiredError()

    def _oembed(self, url: str) -> Optional[dict]:
        try:
            resp = self._client.get(
                "https://api.instagram.com/oembed",
                params={"url": url},
            )
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/json"):
                return resp.json()
        except httpx.HTTPError:
            pass
        return None

    # ------------------------------------------------------------------ #
    # Profile / username
    # ------------------------------------------------------------------ #
    def _resolve_profile(self, cls: Classification) -> List[ItemOut]:
        username = cls.username or ""
        url = cls.canonical_url or f"https://www.instagram.com/{username}/"
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            raise self._map_http_error(exc) from exc

        self._raise_for_blocked(resp)

        codes = list(dict.fromkeys(_SHORTCODE_RE.findall(resp.text)))
        if not codes:
            # The anonymous profile view exposes no post shortcodes.
            raise LoginRequiredError()

        return [
            ItemOut(
                id=code,
                type=MediaType.post,
                source_url=f"https://www.instagram.com/p/{code}/",
            )
            for code in codes[:24]
        ]

    # ------------------------------------------------------------------ #
    # Embed payload parsing
    # ------------------------------------------------------------------ #
    def _extract_payload(self, html: str) -> Optional[dict]:
        """Pull the `window.__additionalDataLoaded('extra', …)` JSON object."""
        m = _ADDITIONAL_DATA.search(html)
        if not m:
            return None
        after = html[m.end():]
        try:
            obj, _ = json.JSONDecoder().raw_decode(after)
        except ValueError:
            return None
        return obj if isinstance(obj, dict) else None

    def _payload_items(self, payload: dict, code: str, kind: InputType, url: str):
        """Map the embed JSON into ItemOut list + owner username."""
        sc = payload.get("shortcode_media")
        if sc is None:
            sc = (payload.get("graphql") or {}).get("shortcode_media")
        if not isinstance(sc, dict) or not (sc.get("display_url") or sc.get("video_url") or sc.get("is_video")):
            raise LoginRequiredError()

        owner = sc.get("owner") or {}
        username = owner.get("username") if isinstance(owner, dict) else None
        caption = self._caption_of(sc)
        timestamp = self._timestamp_of(sc)
        default_type = MediaType.reel if kind is InputType.reel else MediaType.post

        children = (sc.get("edge_sidecar_to_children") or {}).get("edges", [])
        if children:
            items = []
            for i, edge in enumerate(children, start=1):
                node = edge.get("node") or {}
                item = self._node_item(
                    node=node,
                    item_id=f"{code}_n{i}",
                    media_type=default_type,
                    caption=caption,
                    timestamp=timestamp,
                    source_url=url,
                )
                if item:
                    items.append(item)
            return items or None, username

        item = self._node_item(
            node=sc,
            item_id=sc.get("shortcode") or code,
            media_type=default_type,
            caption=caption,
            timestamp=timestamp,
            source_url=url,
        )
        return ([item] if item else None), username

    def _node_item(self, node: dict, item_id: str, media_type: MediaType, caption, timestamp, source_url=None) -> Optional[ItemOut]:
        """Build an ItemOut from a media node (single or one sidecar child)."""
        is_video = node.get("is_video")
        media_url = node.get("video_url") or node.get("display_url")
        if not media_url:
            return None
        thumb = node.get("display_url") or media_url
        # A /p/ carousel may contain videos; keep the folder as post and the
        # extension is chosen from content-type at download time.
        return ItemOut(
            id=item_id,
            type=media_type,
            thumbnail_url=thumb,
            media_url=media_url,
            caption=caption if caption and item_id.endswith("_1") else caption,
            timestamp=timestamp,
            source_url=source_url,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _caption_of(sc: dict) -> Optional[str]:
        edges = ((sc.get("edge_media_to_caption") or {}).get("edges") or [])
        if edges and edges[0].get("node", {}).get("text"):
            return edges[0]["node"]["text"]
        return None

    @staticmethod
    def _timestamp_of(sc: dict) -> Optional[str]:
        ts = (sc or {}).get("taken_at_timestamp")
        if isinstance(ts, (int, float)) and ts:
            return datetime.fromtimestamp(ts, timezone.utc).isoformat()
        return None

    @staticmethod
    def _username_from_url(author_url: Optional[str]) -> Optional[str]:
        if not author_url:
            return None
        m = _PROFILE_PATH_RE.match(urlparse(author_url).path.rstrip("/"))
        return m.group(1) if m else None

    @staticmethod
    def _find(pattern: "re.Pattern[str]", text: str) -> Optional[str]:
        m = pattern.search(text)
        return m.group(1) if m else None

    @staticmethod
    def _raise_for_blocked(resp: httpx.Response) -> None:
        if resp.status_code == 429:
            raise RateLimitError()
        if resp.status_code in (404, 410):
            raise DeletedError()
        if resp.status_code == 403:
            raise PrivateAccountError()

    @staticmethod
    def _map_http_error(exc: httpx.HTTPError) -> Exception:
        response = getattr(exc, "response", None)
        code = getattr(response, "status_code", None)
        if code == 404:
            return DeletedError()
        if code == 403:
            return PrivateAccountError()
        if code == 429:
            return RateLimitError()
        return NetworkError()


# Reusable module-level instance; the FastAPI app owns its lifecycle.
resolver = Resolver()