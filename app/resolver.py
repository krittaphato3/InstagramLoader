"""Resolve raw Instagram input into a list of publicly available media items.

Privacy notes: this module only reads public, unauthenticated endpoints (the
public post page and the public oEmbed endpoint). It never logs in, never
tries to bypass a login wall, and never fetches private items. Any content
that requires authentication surfaces a typed error instead of being worked
around.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

import httpx

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
from .models import InputType, ItemOut, MediaType, ResolveResponse

# Match /p/ABC123 or /reel/ABC123 (also /reels/ and audio reel links removed the code part shown).
_SHORTCODE_RE = re.compile(r"/(?:p|reel|reels)/([A-Za-z0-9_-]{5,})")
# A bare path segment that looks like a username, e.g. the /username/ part.
_PROFILE_PATH_RE = re.compile(r"^/([A-Za-z0-9_.]{2,30})/?$")
_USERNAME_RE = re.compile(r"^@?([A-Za-z0-9_.]{2,30})$")

_OG_IMAGE_RE = re.compile(r'property="og:image"\s+content="([^"]+)"')
_OG_TITLE_RE = re.compile(r'property="og:title"\s+content="([^"]+)"')


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

    # Reel links use "reel" as the kind; post links use "p".
    m = _SHORTCODE_RE.search(path)
    if m:
        code = m.group(1)
        kind = InputType.reel if "reel" in path else InputType.post
        return Classification(
            kind=kind,
            shortcode=code,
            canonical_url=f"https://www.instagram.com/{'reel' if kind is InputType.reel else 'p'}/{code}/",
        )

    # A bare profile path like /username/ with no trailing resource.
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
            },
        )

    def close(self) -> None:
        self._client.close()

    def resolve(self, raw: str) -> ResolveResponse:
        cls = classify(raw)
        if cls.kind in (InputType.post, InputType.reel):
            items = [self._resolve_single(cls)]
            return ResolveResponse(input_type=cls.kind, username=cls.username, items=items)
        items = self._resolve_profile(cls)
        return ResolveResponse(input_type=cls.kind, username=cls.username, items=items)

    # ------------------------------------------------------------------ #
    # Single post/reel
    # ------------------------------------------------------------------ #
    def _resolve_single(self, cls: Classification) -> ItemOut:
        kind = cls.kind
        path = "reel" if kind is InputType.reel else "p"
        url = cls.canonical_url or f"https://www.instagram.com/{path}/{cls.shortcode}/"

        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            raise self._map_http_error(exc) from exc

        self._raise_for_blocked(resp)

        thumbnail = self._find(_OG_IMAGE_RE, resp.text)
        title = self._find(_OG_TITLE_RE, resp.text)

        if not thumbnail and not title:
            # The public page did not expose metadata -> probably a login wall.
            raise LoginRequiredError()

        return ItemOut(
            id=cls.shortcode or cls.canonical_url or "item",
            type=MediaType.reel if kind is InputType.reel else MediaType.post,
            thumbnail_url=thumbnail,
            caption=title,
            source_url=cls.canonical_url,
        )

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

        # Pull shortcodes that appear as post links on the public page.
        codes = list(dict.fromkeys(_SHORTCODE_RE.findall(resp.text)))
        if not codes:
            # No public posts visible anonymously.
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
    # Helpers
    # ------------------------------------------------------------------ #
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