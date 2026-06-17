"""Sosyal medya otomatik paylaşım modülü — TikTok, Instagram Reels, YouTube Shorts."""

import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
PUBLISH_LOG = PROJECT_DIR / "publish_log.json"
PUBLISH_CONFIG = PROJECT_DIR / "publish_config.json"


def _default_publish_config() -> dict:
    return {
        "youtube": {
            "enabled": False,
            "channel_id": "",
            "default_tags": ["shorts", "viral", "trending"],
            "default_visibility": "public",
            "description_template": "{title}\n\n#shorts #viral #trending",
        },
        "tiktok": {
            "enabled": False,
            "description_template": "{title} #fyp #viral #trending",
        },
        "instagram": {
            "enabled": False,
            "caption_template": "{title}\n.\n.\n#reels #viral #trending #explore",
        },
        "schedule": {
            "enabled": False,
            "posts_per_day": 3,
            "post_hours": [9, 14, 19],
            "platforms": ["youtube", "tiktok", "instagram"],
        },
    }


def load_publish_config() -> dict:
    if PUBLISH_CONFIG.exists():
        try:
            cfg = json.loads(PUBLISH_CONFIG.read_text(encoding="utf-8"))
            merged = _default_publish_config()
            for k in merged:
                if k in cfg:
                    if isinstance(merged[k], dict):
                        merged[k].update(cfg[k])
                    else:
                        merged[k] = cfg[k]
            return merged
        except Exception:
            pass
    return _default_publish_config()


def save_publish_config(config: dict) -> None:
    PUBLISH_CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_publish_log() -> list[dict]:
    if PUBLISH_LOG.exists():
        try:
            return json.loads(PUBLISH_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _append_publish_log(entry: dict) -> None:
    log = _load_publish_log()
    log.append(entry)
    log = log[-500:]
    PUBLISH_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ── YouTube Shorts Upload (via YouTube Data API v3 + OAuth2) ─────────


def upload_to_youtube(
    video_path: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    visibility: str = "public",
    access_token: str = "",
) -> dict:
    """YouTube Shorts'a video yükle. OAuth2 access_token gerekli."""

    if not access_token:
        access_token = os.getenv("YOUTUBE_ACCESS_TOKEN", "")
    if not access_token:
        return {"status": "error", "error": "YouTube OAuth2 access_token gerekli."}

    if not Path(video_path).exists():
        return {"status": "error", "error": f"Video bulunamadi: {video_path}"}

    tags = tags or ["shorts", "viral"]
    title = title[:100]

    metadata = {
        "snippet": {
            "title": title,
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": visibility,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
        },
    }

    # Step 1: Initiate resumable upload
    init_url = (
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status"
    )

    meta_bytes = json.dumps(metadata).encode("utf-8")
    req = urllib.request.Request(init_url, data=meta_bytes, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json; charset=UTF-8")
    req.add_header("X-Upload-Content-Type", "video/mp4")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            upload_url = resp.headers.get("Location")
            if not upload_url:
                return {"status": "error", "error": "Upload URL alinamadi."}
    except Exception as e:
        return {"status": "error", "error": f"YouTube init hatasi: {e}"}

    # Step 2: Upload the video file
    file_size = Path(video_path).stat().st_size
    with open(video_path, "rb") as f:
        upload_req = urllib.request.Request(upload_url, data=f.read(), method="PUT")
        upload_req.add_header("Content-Type", "video/mp4")
        upload_req.add_header("Content-Length", str(file_size))

        try:
            with urllib.request.urlopen(upload_req, timeout=300) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                video_id = result.get("id", "")
                log_entry = {
                    "time": _now_str(),
                    "platform": "youtube",
                    "status": "done",
                    "video_id": video_id,
                    "title": title,
                    "url": f"https://youtube.com/shorts/{video_id}",
                }
                _append_publish_log(log_entry)
                return log_entry
        except Exception as e:
            error_entry = {"time": _now_str(), "platform": "youtube", "status": "error", "error": str(e), "title": title}
            _append_publish_log(error_entry)
            return error_entry


# ── TikTok Upload (via TikTok Content Posting API) ──────────────────


def upload_to_tiktok(
    video_path: str,
    description: str = "",
    access_token: str = "",
) -> dict:
    """TikTok'a video yükle. OAuth2 access_token gerekli (Content Posting API)."""

    if not access_token:
        access_token = os.getenv("TIKTOK_ACCESS_TOKEN", "")
    if not access_token:
        return {"status": "error", "error": "TikTok access_token gerekli. Developer Portal'dan alinir."}

    if not Path(video_path).exists():
        return {"status": "error", "error": f"Video bulunamadi: {video_path}"}

    description = description[:2200]

    # Step 1: Initialize upload
    init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    init_body = json.dumps({
        "post_info": {
            "title": description[:150],
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_stitch": False,
            "disable_comment": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": Path(video_path).stat().st_size,
        },
    }).encode("utf-8")

    req = urllib.request.Request(init_url, data=init_body, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json; charset=UTF-8")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        if result.get("error", {}).get("code") != "ok":
            err_msg = result.get("error", {}).get("message", "Bilinmeyen hata")
            return {"status": "error", "error": f"TikTok init hatasi: {err_msg}"}

        upload_url = result.get("data", {}).get("upload_url", "")
        publish_id = result.get("data", {}).get("publish_id", "")

        if not upload_url:
            return {"status": "error", "error": "TikTok upload URL alinamadi."}

    except Exception as e:
        return {"status": "error", "error": f"TikTok init hatasi: {e}"}

    # Step 2: Upload video
    file_size = Path(video_path).stat().st_size
    with open(video_path, "rb") as f:
        upload_req = urllib.request.Request(upload_url, data=f.read(), method="PUT")
        upload_req.add_header("Content-Range", f"bytes 0-{file_size - 1}/{file_size}")
        upload_req.add_header("Content-Type", "video/mp4")

        try:
            with urllib.request.urlopen(upload_req, timeout=300) as resp:
                log_entry = {
                    "time": _now_str(),
                    "platform": "tiktok",
                    "status": "done",
                    "publish_id": publish_id,
                    "description": description[:100],
                }
                _append_publish_log(log_entry)
                return log_entry
        except Exception as e:
            error_entry = {"time": _now_str(), "platform": "tiktok", "status": "error", "error": str(e)}
            _append_publish_log(error_entry)
            return error_entry


# ── Instagram Reels Upload (via Instagram Graph API) ─────────────────


def upload_to_instagram(
    video_path: str,
    caption: str = "",
    access_token: str = "",
    ig_user_id: str = "",
) -> dict:
    """Instagram Reels'a video yükle. Facebook Graph API access_token + IG user ID gerekli."""

    if not access_token:
        access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    if not ig_user_id:
        ig_user_id = os.getenv("INSTAGRAM_USER_ID", "")
    if not access_token or not ig_user_id:
        return {"status": "error", "error": "Instagram access_token ve user_id gerekli."}

    if not Path(video_path).exists():
        return {"status": "error", "error": f"Video bulunamadi: {video_path}"}

    caption = caption[:2200]

    # Instagram Reels requires a publicly accessible URL for the video.
    # For self-hosted setups, the video must be served via a public URL.
    # Here we provide a placeholder — in production, use a CDN or public server URL.
    video_url = os.getenv("PUBLIC_VIDEO_URL_BASE", "")
    if not video_url:
        return {
            "status": "error",
            "error": "Instagram icin PUBLIC_VIDEO_URL_BASE env var gerekli. "
                     "Video dosyalari herkese acik bir URL'den erisilebilir olmali.",
        }

    filename = Path(video_path).name
    public_url = f"{video_url.rstrip('/')}/{filename}"

    # Step 1: Create media container
    container_url = f"https://graph.facebook.com/v21.0/{ig_user_id}/media"
    container_params = urllib.parse.urlencode({
        "media_type": "REELS",
        "video_url": public_url,
        "caption": caption,
        "access_token": access_token,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(container_url, data=container_params, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            container_id = result.get("id")
            if not container_id:
                return {"status": "error", "error": "Instagram container olusturulamadi."}
    except Exception as e:
        return {"status": "error", "error": f"Instagram container hatasi: {e}"}

    # Step 2: Wait for processing and publish
    time.sleep(10)

    publish_url = f"https://graph.facebook.com/v21.0/{ig_user_id}/media_publish"
    publish_params = urllib.parse.urlencode({
        "creation_id": container_id,
        "access_token": access_token,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(publish_url, data=publish_params, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            media_id = result.get("id", "")
            log_entry = {
                "time": _now_str(),
                "platform": "instagram",
                "status": "done",
                "media_id": media_id,
                "caption": caption[:100],
            }
            _append_publish_log(log_entry)
            return log_entry
    except Exception as e:
        error_entry = {"time": _now_str(), "platform": "instagram", "status": "error", "error": str(e)}
        _append_publish_log(error_entry)
        return error_entry


# ── Multi-platform publish ───────────────────────────────────────────


def publish_video(
    video_path: str,
    title: str,
    platforms: list[str] | None = None,
    config: dict | None = None,
) -> list[dict]:
    """Video'yu belirtilen platformlara yükle."""
    config = config or load_publish_config()
    platforms = platforms or config.get("schedule", {}).get("platforms", [])

    results = []

    for platform in platforms:
        pcfg = config.get(platform, {})
        if not pcfg.get("enabled"):
            results.append({"platform": platform, "status": "skipped", "reason": "disabled"})
            continue

        if platform == "youtube":
            desc_template = pcfg.get("description_template", "{title}")
            description = desc_template.replace("{title}", title)
            tags = pcfg.get("default_tags", [])
            visibility = pcfg.get("default_visibility", "public")
            result = upload_to_youtube(video_path, title, description, tags, visibility)

        elif platform == "tiktok":
            desc_template = pcfg.get("description_template", "{title}")
            description = desc_template.replace("{title}", title)
            result = upload_to_tiktok(video_path, description)

        elif platform == "instagram":
            cap_template = pcfg.get("caption_template", "{title}")
            caption = cap_template.replace("{title}", title)
            result = upload_to_instagram(video_path, caption)

        else:
            result = {"platform": platform, "status": "error", "error": "Bilinmeyen platform"}

        result["platform"] = platform
        results.append(result)

    return results


def get_publish_log(limit: int = 50) -> list[dict]:
    return _load_publish_log()[-limit:]
