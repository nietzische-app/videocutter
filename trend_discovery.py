"""Trend video keşif modülü — YouTube Data API v3 ile trending/popüler videoları bulur."""

import json
import os
import time
import urllib.request
import urllib.parse
from pathlib import Path

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

YOUTUBE_CATEGORIES = {
    "1": "Film & Animasyon",
    "2": "Otomobil",
    "10": "Muzik",
    "15": "Hayvanlar",
    "17": "Spor",
    "18": "Kisa Film",
    "19": "Seyahat",
    "20": "Oyun",
    "22": "Insanlar & Blog",
    "23": "Komedi",
    "24": "Eglence",
    "25": "Haber & Politika",
    "26": "Nasil Yapilir & Stil",
    "27": "Egitim",
    "28": "Bilim & Teknoloji",
}

NICHE_PRESETS = {
    "gaming": {"category_id": "20", "search_terms": ["gaming", "gameplay", "oyun"]},
    "komedi": {"category_id": "23", "search_terms": ["komedi", "funny", "comedy", "eglence"]},
    "spor": {"category_id": "17", "search_terms": ["spor", "futbol", "basketbol", "highlights"]},
    "muzik": {"category_id": "10", "search_terms": ["müzik", "music", "concert", "live"]},
    "teknoloji": {"category_id": "28", "search_terms": ["tech", "teknoloji", "review", "unboxing"]},
    "film": {"category_id": "1", "search_terms": ["film", "movie", "sahne", "trailer", "dizi"]},
    "eglence": {"category_id": "24", "search_terms": ["entertainment", "eğlence", "viral", "trend"]},
    "hayvanlar": {"category_id": "15", "search_terms": ["animals", "hayvan", "kedi", "köpek", "cute"]},
    "haber": {"category_id": "25", "search_terms": ["haber", "news", "gündem", "son dakika"]},
}

HISTORY_FILE = Path(__file__).resolve().parent / "trend_history.json"


def _api_get(endpoint: str, params: dict, api_key: str) -> dict:
    params["key"] = api_key
    url = f"{YOUTUBE_API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed": [], "last_check": 0}


def _save_history(history: dict) -> None:
    history["processed"] = history["processed"][-500:]
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def get_trending_videos(
    api_key: str,
    region_code: str = "TR",
    category_id: str | None = None,
    max_results: int = 10,
) -> list[dict]:
    params = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": region_code,
        "maxResults": str(max_results),
    }
    if category_id:
        params["videoCategoryId"] = category_id

    data = _api_get("videos", params, api_key)
    return _parse_video_items(data.get("items", []))


def search_videos(
    api_key: str,
    query: str,
    region_code: str = "TR",
    order: str = "viewCount",
    published_after: str | None = None,
    max_results: int = 10,
    duration: str = "medium",
) -> list[dict]:
    params = {
        "part": "snippet",
        "type": "video",
        "q": query,
        "regionCode": region_code,
        "order": order,
        "maxResults": str(max_results),
        "videoDuration": duration,
    }
    if published_after:
        params["publishedAfter"] = published_after

    data = _api_get("search", params, api_key)

    video_ids = [item["id"]["videoId"] for item in data.get("items", []) if item.get("id", {}).get("videoId")]
    if not video_ids:
        return []

    details = _api_get("videos", {
        "part": "snippet,statistics,contentDetails",
        "id": ",".join(video_ids),
    }, api_key)

    return _parse_video_items(details.get("items", []))


def _parse_video_items(items: list[dict]) -> list[dict]:
    results = []
    for item in items:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        video_id = item.get("id", "")
        if isinstance(video_id, dict):
            video_id = video_id.get("videoId", "")

        results.append({
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "published_at": snippet.get("publishedAt", ""),
            "description": snippet.get("description", "")[:300],
            "view_count": int(stats.get("viewCount", 0)),
            "like_count": int(stats.get("likeCount", 0)),
            "comment_count": int(stats.get("commentCount", 0)),
            "category_id": snippet.get("categoryId", ""),
            "duration": item.get("contentDetails", {}).get("duration", ""),
            "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
        })

    return results


def _parse_iso_duration(duration_str: str) -> int:
    """PT1H2M3S -> seconds"""
    import re
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
    if not match:
        return 0
    h, m, s = (int(x) if x else 0 for x in match.groups())
    return h * 3600 + m * 60 + s


def discover_niche_videos(
    api_key: str,
    niche: str,
    region_code: str = "TR",
    max_results: int = 10,
    min_views: int = 10000,
    min_duration_sec: int = 60,
    max_duration_sec: int = 1800,
    skip_processed: bool = True,
) -> list[dict]:
    preset = NICHE_PRESETS.get(niche)
    if not preset:
        raise ValueError(f"Bilinmeyen nis: {niche}. Secenekler: {', '.join(NICHE_PRESETS.keys())}")

    history = _load_history() if skip_processed else {"processed": []}
    processed_ids = set(history.get("processed", []))

    all_videos: dict[str, dict] = {}

    trending = get_trending_videos(
        api_key=api_key,
        region_code=region_code,
        category_id=preset["category_id"],
        max_results=max_results,
    )
    for v in trending:
        if v["video_id"] not in processed_ids:
            all_videos[v["video_id"]] = v

    from datetime import datetime, timedelta, timezone
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for term in preset["search_terms"][:2]:
        try:
            searched = search_videos(
                api_key=api_key,
                query=term,
                region_code=region_code,
                order="viewCount",
                published_after=week_ago,
                max_results=max_results,
            )
            for v in searched:
                if v["video_id"] not in processed_ids:
                    all_videos[v["video_id"]] = v
        except Exception:
            continue

    filtered = []
    for v in all_videos.values():
        dur = _parse_iso_duration(v.get("duration", ""))
        if v["view_count"] < min_views:
            continue
        if dur < min_duration_sec or dur > max_duration_sec:
            continue
        v["duration_seconds"] = dur
        filtered.append(v)

    filtered.sort(key=lambda x: x["view_count"], reverse=True)
    return filtered[:max_results]


def mark_processed(video_ids: list[str]) -> None:
    history = _load_history()
    history["processed"].extend(video_ids)
    history["last_check"] = time.time()
    _save_history(history)


def get_available_niches() -> dict[str, dict]:
    return {k: {"name": k, "category": YOUTUBE_CATEGORIES.get(v["category_id"], "?"), "terms": v["search_terms"]} for k, v in NICHE_PRESETS.items()}
