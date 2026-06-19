"""YouTube'da kategoriye gore viral video kesfi."""

from __future__ import annotations

import random

from categories import CATEGORIES, get_category
from youtube_dl import build_ytdlp_options


def _normalize_entry(entry: dict) -> dict | None:
    video_id = entry.get("id") or entry.get("url", "").split("v=")[-1][:11]
    if not video_id or len(video_id) != 11:
        return None

    channel = entry.get("channel") or entry.get("uploader") or entry.get("channel_id") or "unknown"
    return {
        "id": video_id,
        "title": entry.get("title") or "Basliksiz",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "channel": channel,
        "view_count": entry.get("view_count"),
        "duration": entry.get("duration"),
        "thumbnail": entry.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    }


def search_youtube(query: str, limit: int = 8) -> list[dict]:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("yt-dlp gerekli: python -m pip install yt-dlp") from exc

    options = build_ytdlp_options(quiet=True, extract_flat=True)

    with YoutubeDL(options) as ydl:
        result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

    entries = result.get("entries") or []
    videos: list[dict] = []
    seen: set[str] = set()

    for entry in entries:
        if not entry:
            continue
        normalized = _normalize_entry(entry)
        if normalized and normalized["id"] not in seen:
            seen.add(normalized["id"])
            videos.append(normalized)

    return videos


def discover_for_category(category_id: str, limit: int = 8) -> list[dict]:
    category = get_category(category_id)
    queries = category["search_queries"]
    query = random.choice(queries)
    videos = search_youtube(query, limit=limit * 2)

    for video in videos:
        video["category"] = category_id
        video["category_name"] = category["name"]
        video["search_query"] = query

    return videos[:limit]


def discover_all_categories(limit_per_category: int = 5) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    for cat_id in CATEGORIES:
        try:
            results[cat_id] = discover_for_category(cat_id, limit=limit_per_category)
        except Exception as exc:
            results[cat_id] = []
            print(f"Kesif hatasi ({cat_id}): {exc}")
    return results
