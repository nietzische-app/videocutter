"""Çoklu kanal/hesap yönetimi — kategori bazlı otomatik paylaşım."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
CHANNELS_FILE = PROJECT_DIR / "channels_config.json"


def _default_channels() -> dict:
    return {"channels": [], "queue": []}


def load_channels() -> dict:
    if CHANNELS_FILE.exists():
        try:
            data = json.loads(CHANNELS_FILE.read_text(encoding="utf-8"))
            data.setdefault("channels", [])
            data.setdefault("queue", [])
            return data
        except Exception:
            pass
    return _default_channels()


def save_channels(data: dict) -> None:
    CHANNELS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_channel(
    name: str,
    category: str,
    platform: str,
    credentials: dict,
    post_hours: list[int] | None = None,
    posts_per_day: int = 3,
    tags: list[str] | None = None,
    description_template: str = "{title}",
) -> dict:
    data = load_channels()
    channel = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "category": category,
        "platform": platform,
        "credentials": credentials,
        "enabled": True,
        "posts_per_day": posts_per_day,
        "post_hours": post_hours or [9, 13, 17, 20],
        "tags": tags or ["shorts", "viral", "trending"],
        "description_template": description_template,
        "stats": {"total_posted": 0, "last_posted": None},
    }
    data["channels"].append(channel)
    save_channels(data)
    return channel


def update_channel(channel_id: str, updates: dict) -> dict | None:
    data = load_channels()
    for ch in data["channels"]:
        if ch["id"] == channel_id:
            safe_keys = {
                "name", "category", "platform", "enabled", "posts_per_day",
                "post_hours", "tags", "description_template", "credentials",
            }
            for k, v in updates.items():
                if k in safe_keys:
                    ch[k] = v
            save_channels(data)
            return ch
    return None


def remove_channel(channel_id: str) -> bool:
    data = load_channels()
    before = len(data["channels"])
    data["channels"] = [ch for ch in data["channels"] if ch["id"] != channel_id]
    if len(data["channels"]) < before:
        save_channels(data)
        return True
    return False


def get_channels_by_category(category: str) -> list[dict]:
    data = load_channels()
    return [ch for ch in data["channels"] if ch["category"] == category and ch.get("enabled")]


def get_all_channels() -> list[dict]:
    data = load_channels()
    return data["channels"]


def add_to_queue(video_path: str, title: str, category: str, channel_ids: list[str] | None = None) -> dict:
    data = load_channels()

    if channel_ids:
        targets = channel_ids
    else:
        targets = [ch["id"] for ch in data["channels"] if ch["category"] == category and ch.get("enabled")]

    item = {
        "id": uuid.uuid4().hex[:8],
        "video_path": video_path,
        "title": title,
        "category": category,
        "target_channels": targets,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "results": {},
    }
    data["queue"].append(item)
    data["queue"] = data["queue"][-200:]
    save_channels(data)
    return item


def get_queue(limit: int = 50) -> list[dict]:
    data = load_channels()
    return data["queue"][-limit:]


def update_queue_item(item_id: str, channel_id: str, status: str, result: dict | None = None) -> None:
    data = load_channels()
    for item in data["queue"]:
        if item["id"] == item_id:
            item["results"][channel_id] = {
                "status": status,
                "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                **(result or {}),
            }
            all_done = all(
                ch_id in item["results"]
                for ch_id in item.get("target_channels", [])
            )
            if all_done:
                item["status"] = "done"
            break
    save_channels(data)


def increment_channel_stats(channel_id: str) -> None:
    data = load_channels()
    for ch in data["channels"]:
        if ch["id"] == channel_id:
            ch["stats"]["total_posted"] = ch["stats"].get("total_posted", 0) + 1
            ch["stats"]["last_posted"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            break
    save_channels(data)


CATEGORY_PRESETS = {
    "gaming": {
        "tags": ["gaming", "shorts", "gameplay", "viral", "oyun"],
        "description": "{title}\n\n#gaming #shorts #viral #gameplay",
    },
    "komedi": {
        "tags": ["komedi", "shorts", "funny", "viral", "eglence"],
        "description": "{title}\n\n#komedi #shorts #viral #funny",
    },
    "spor": {
        "tags": ["spor", "shorts", "highlights", "viral", "futbol"],
        "description": "{title}\n\n#spor #shorts #viral #highlights",
    },
    "muzik": {
        "tags": ["muzik", "shorts", "music", "viral", "live"],
        "description": "{title}\n\n#muzik #shorts #viral #music",
    },
    "teknoloji": {
        "tags": ["tech", "shorts", "teknoloji", "viral", "review"],
        "description": "{title}\n\n#tech #shorts #viral #teknoloji",
    },
    "film": {
        "tags": ["film", "shorts", "movie", "sahne", "viral"],
        "description": "{title}\n\n#film #shorts #viral #movie",
    },
    "eglence": {
        "tags": ["eglence", "shorts", "viral", "trending", "fyp"],
        "description": "{title}\n\n#eglence #shorts #viral #trending",
    },
}
