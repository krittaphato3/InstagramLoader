"""Unit tests for the public embed/`oEmbed` resolver paths.

Instagram blocks anonymous access from restricted/datacenter IPs (serving a
"log in" shell), so we cannot rely on a live network test here. Instead we
feed the resolver a realistic snippet of the public embed page payload
(`window.__additionalDataLoaded('extra', …)`) and assert the parser yields
real, downloadable media URLs exactly like Instagram's own public page.
"""
from __future__ import annotations

import json

from app.errors import LoginRequiredError
from app.models import InputType, MediaType
from app.resolver import Resolver

IMAGE_PAYLOAD = {
    "shortcode_media": {
        "shortcode": "AbC123",
        "display_url": "https://cdn/single.jpg",
        "is_video": False,
        "taken_at_timestamp": 1700000000,
        "owner": {"username": "natgeo"},
        "edge_media_to_caption": {"edges": [{"node": {"text": "Hello world"}}]},
    }
}

VIDEO_PAYLOAD = {
    "shortcode_media": {
        "shortcode": "Re9Ab",
        "display_url": "https://cdn/reel_thumb.jpg",
        "video_url": "https://cdn/reel.mp4",
        "is_video": True,
        "taken_at_timestamp": 1700000100,
        "owner": {"username": "someuser"},
        "edge_media_to_caption": {"edges": [{"node": {"text": "A reel"}}]},
    }
}

CAROUSEL_PAYLOAD = {
    "shortcode_media": {
        "shortcode": "CaXyZ",
        "display_url": "https://cdn/c1.jpg",
        "is_video": False,
        "owner": {"username": "car"},
        "edge_media_to_caption": {"edges": []},
        "edge_sidecar_to_children": {
            "edges": [
                {"node": {"shortcode": "child1", "display_url": "https://cdn/a.jpg", "is_video": False}},
                {"node": {"shortcode": "child2", "display_url": "https://cdn/b.jpg", "video_url": "https://cdn/b.mp4", "is_video": True}},
            ]
        },
    }
}


def embed_html(payload: dict) -> str:
    return "<html><body><script>window.__additionalDataLoaded(\"extra\"," + json.dumps(payload) + ");</script></body></html>"


def test_extracts_single_image_post():
    r = Resolver()
    obj = r._extract_payload(embed_html(IMAGE_PAYLOAD))
    assert obj is not None
    items, username = r._payload_items(obj, "AbC123", InputType.post, "https://www.instagram.com/p/AbC123/")
    assert username == "natgeo"
    assert len(items) == 1
    it = items[0]
    assert it.type is MediaType.post
    assert it.media_url == "https://cdn/single.jpg"
    assert it.thumbnail_url == "https://cdn/single.jpg"
    assert it.caption == "Hello world"
    assert it.timestamp and "T" in it.timestamp


def test_video_reel_uses_reel_type():
    r = Resolver()
    obj = r._extract_payload(embed_html(VIDEO_PAYLOAD))
    items, username = r._payload_items(obj, "Re9Ab", InputType.reel, "https://www.instagram.com/reel/Re9Ab/")
    assert username == "someuser"
    it = items[0]
    assert it.type is MediaType.reel
    assert it.media_url == "https://cdn/reel.mp4"


def test_carousel_expands_all_children():
    r = Resolver()
    obj = r._extract_payload(embed_html(CAROUSEL_PAYLOAD))
    items, username = r._payload_items(obj, "CaXyZ", InputType.post, "https://www.instagram.com/p/CaXyZ/")
    assert username == "car"
    assert len(items) == 2
    assert items[0].media_url == "https://cdn/a.jpg"
    assert items[1].media_url == "https://cdn/b.mp4"


def test_no_payload_means_login_required():
    r = Resolver()
    assert r._extract_payload("<html>no payload</html>") is None
    try:
        r._payload_items(
            {"no_media": True},
            "Xyz",
            InputType.post,
            "https://www.instagram.com/p/Xyz/",
        )
        assert False, "expected LoginRequiredError"
    except LoginRequiredError:
        pass