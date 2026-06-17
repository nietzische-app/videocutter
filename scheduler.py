"""Otomasyon zamanlayıcı — trend videoları keşfet, kliple, kanallarına dağıt."""

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from trend_discovery import discover_niche_videos, mark_processed, get_available_niches
from channels import get_channels_by_category, add_to_queue, update_queue_item, increment_channel_stats, load_channels
from publisher import publish_video, load_publish_config

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", PROJECT_DIR / "outputs")).resolve()
SCHEDULE_FILE = PROJECT_DIR / "schedule_config.json"
SCHEDULE_LOG = PROJECT_DIR / "schedule_log.json"

_scheduler_thread: threading.Thread | None = None
_scheduler_running = False


def _default_config() -> dict:
    return {
        "enabled": False,
        "niches": ["eglence"],
        "region": "TR",
        "interval_minutes": 360,
        "clips_per_run": 3,
        "clip_seconds": 30,
        "min_views": 50000,
        "subtitle_style": "bold",
        "use_template": True,
        "auto_caption": True,
        "auto_publish": False,
    }


def load_config() -> dict:
    if SCHEDULE_FILE.exists():
        try:
            cfg = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
            merged = _default_config()
            merged.update(cfg)
            return merged
        except Exception:
            pass
    return _default_config()


def save_config(config: dict) -> None:
    SCHEDULE_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_log() -> list[dict]:
    if SCHEDULE_LOG.exists():
        try:
            return json.loads(SCHEDULE_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _append_log(entry: dict) -> None:
    log = _load_log()
    log.append(entry)
    log = log[-200:]
    SCHEDULE_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def run_single_discovery(config: dict | None = None) -> list[dict]:
    """Tek seferlik trend keşfi + klipleme + kanal dağıtımı."""
    config = config or load_config()

    youtube_api_key = os.getenv("YOUTUBE_API_KEY", "")
    openai_api_key = os.getenv("OPENAI_API_KEY", "")

    if not youtube_api_key:
        raise ValueError("YOUTUBE_API_KEY environment variable gerekli.")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY environment variable gerekli.")

    all_videos = []
    for niche in config.get("niches", ["eglence"]):
        try:
            videos = discover_niche_videos(
                api_key=youtube_api_key,
                niche=niche,
                region_code=config.get("region", "TR"),
                max_results=config.get("clips_per_run", 3),
                min_views=config.get("min_views", 50000),
            )
            for v in videos:
                v["niche"] = niche
            all_videos.extend(videos)
        except Exception as e:
            print(f"[Scheduler] Nis '{niche}' kesfinde hata: {e}")
            _append_log({"time": _now_str(), "type": "error", "niche": niche, "error": str(e)})

    all_videos.sort(key=lambda x: x["view_count"], reverse=True)
    selected = all_videos[:config.get("clips_per_run", 3)]

    results = []
    for video in selected:
        result = _process_video(video, config, openai_api_key)
        results.append(result)
        mark_processed([video["video_id"]])

        if result.get("status") == "done" and config.get("auto_publish"):
            _distribute_to_channels(result, video, config)

    return results


def _distribute_to_channels(result: dict, video: dict, config: dict) -> None:
    """Kliplenen videoyu ilgili kategorideki kanallara dağıt."""
    output_path = result.get("output", "")
    if not output_path or not Path(output_path).exists():
        return

    niche = video.get("niche", "eglence")
    title = video.get("title", "")[:200]
    channels = get_channels_by_category(niche)

    if not channels:
        print(f"[Scheduler] '{niche}' kategorisinde aktif kanal yok, kuyruga ekleniyor.")
        add_to_queue(output_path, title, niche)
        _append_log({
            "time": _now_str(),
            "type": "queued",
            "video_id": video.get("video_id", ""),
            "niche": niche,
            "reason": "no_active_channels",
        })
        return

    queue_item = add_to_queue(output_path, title, niche, [ch["id"] for ch in channels])
    print(f"[Scheduler] '{title[:50]}...' -> {len(channels)} kanal(a) dagitiliyor")

    for channel in channels:
        _publish_to_channel(queue_item, channel, output_path, title, video)


def _publish_to_channel(queue_item: dict, channel: dict, video_path: str, title: str, video: dict) -> None:
    """Tek bir kanala yayınla."""
    channel_id = channel["id"]
    platform = channel.get("platform", "youtube")
    account_id = channel.get("credentials", {}).get("account_id", "default")

    desc_template = channel.get("description_template", "{title}")
    tags = channel.get("tags", [])
    description = desc_template.replace("{title}", title)
    if tags:
        hashtags = " ".join(f"#{t}" for t in tags)
        if hashtags not in description:
            description = f"{description}\n\n{hashtags}"

    try:
        if platform == "youtube":
            from publisher import upload_to_youtube
            visibility = "public"
            result = upload_to_youtube(video_path, title, description, tags, visibility, account_id)
        elif platform == "tiktok":
            from publisher import upload_to_tiktok
            result = upload_to_tiktok(video_path, description, account_id)
        else:
            result = {"status": "skipped", "reason": f"desteklenmeyen platform: {platform}"}

        status = result.get("status", "error")
        update_queue_item(queue_item["id"], channel_id, status, result)

        if status == "done":
            increment_channel_stats(channel_id)
            print(f"[Scheduler] Yuklendi: {channel['name']} ({platform})")
        else:
            print(f"[Scheduler] Basarisiz: {channel['name']} - {result.get('error', 'bilinmeyen hata')}")

        _append_log({
            "time": _now_str(),
            "type": "publish",
            "video_id": video.get("video_id", ""),
            "channel": channel["name"],
            "platform": platform,
            "status": status,
            "error": result.get("error"),
        })

    except Exception as e:
        update_queue_item(queue_item["id"], channel_id, "error", {"error": str(e)})
        print(f"[Scheduler] Yayin hatasi ({channel['name']}): {e}")
        _append_log({
            "time": _now_str(),
            "type": "publish_error",
            "video_id": video.get("video_id", ""),
            "channel": channel["name"],
            "error": str(e),
        })


def process_pending_queue() -> list[dict]:
    """Kuyrukta bekleyen (pending) videolari isle."""
    data = load_channels()
    results = []

    for item in data["queue"]:
        if item["status"] != "pending":
            continue

        video_path = item.get("video_path", "")
        if not video_path or not Path(video_path).exists():
            update_queue_item(item["id"], "_system", "error", {"error": "video dosyasi bulunamadi"})
            continue

        title = item.get("title", "")
        category = item.get("category", "eglence")
        target_ids = item.get("target_channels", [])

        if not target_ids:
            channels = get_channels_by_category(category)
            target_ids = [ch["id"] for ch in channels]

        all_channels = {ch["id"]: ch for ch in data["channels"]}

        for ch_id in target_ids:
            if ch_id in item.get("results", {}):
                continue
            channel = all_channels.get(ch_id)
            if not channel or not channel.get("enabled"):
                update_queue_item(item["id"], ch_id, "skipped", {"reason": "kanal devre disi"})
                continue
            _publish_to_channel(item, channel, video_path, title, {"video_id": "", "niche": category})

        results.append(item["id"])

    return results


def _process_video(video: dict, config: dict, openai_api_key: str) -> dict:
    """Tek bir videoyu kliple."""
    video_url = video["url"]
    video_id = video["video_id"]
    timestamp = int(time.time())

    output_path = OUTPUT_DIR / f"trend_{video_id}_{timestamp}.mp4"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    caption = video.get("title", "")[:200] if config.get("auto_caption") else ""
    channel_name = video.get("channel", "")
    source_credit = f"Kaynak: @{channel_name.replace(' ', '')}" if channel_name else ""

    command = [
        sys.executable,
        str(PROJECT_DIR / "video_cutter.py"),
        video_url,
        "-o", str(output_path),
        "--clip-seconds", str(config.get("clip_seconds", 30)),
        "--num-clips", "1",
        "--subtitle-style", config.get("subtitle_style", "bold"),
    ]
    if config.get("use_template"):
        command.append("--template")
        if caption:
            command.extend(["--caption", caption])
        if source_credit:
            command.extend(["--source-credit", source_credit])

    cookies_file = PROJECT_DIR / "cookies.txt"
    if cookies_file.exists():
        command.extend(["--cookies", str(cookies_file)])

    env = os.environ.copy()
    env["OPENAI_API_KEY"] = openai_api_key

    log_entry = {
        "time": _now_str(),
        "type": "process",
        "video_id": video_id,
        "title": video["title"],
        "channel": video["channel"],
        "views": video["view_count"],
        "url": video_url,
        "niche": video.get("niche", ""),
    }

    try:
        print(f"[Scheduler] Isleniyor: {video['title'][:60]}... ({video['view_count']:,} goruntulenme)")
        result = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )

        if result.returncode == 0 and output_path.exists():
            log_entry["status"] = "done"
            log_entry["output"] = str(output_path)
            print(f"[Scheduler] Basarili: {output_path.name}")
        else:
            log_entry["status"] = "failed"
            log_entry["error"] = result.stderr[-300:] if result.stderr else result.stdout[-300:]
            print(f"[Scheduler] Basarisiz: {video_id}")
    except subprocess.TimeoutExpired:
        log_entry["status"] = "timeout"
        log_entry["error"] = "10 dakika zaman asimi"
        print(f"[Scheduler] Zaman asimi: {video_id}")
    except Exception as e:
        log_entry["status"] = "error"
        log_entry["error"] = str(e)

    _append_log(log_entry)
    return log_entry


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _scheduler_loop() -> None:
    global _scheduler_running
    print("[Scheduler] Otomasyon zamanlayici basladi.")

    while _scheduler_running:
        config = load_config()
        if not config.get("enabled"):
            time.sleep(30)
            continue

        try:
            print(f"[Scheduler] Trend taramasi basliyor... Nisler: {config.get('niches', [])}")
            run_single_discovery(config)
        except Exception as e:
            print(f"[Scheduler] Hata: {e}")
            _append_log({"time": _now_str(), "type": "error", "error": str(e)})

        if config.get("auto_publish"):
            try:
                processed = process_pending_queue()
                if processed:
                    print(f"[Scheduler] Kuyruktan {len(processed)} video islendi.")
            except Exception as e:
                print(f"[Scheduler] Kuyruk isleme hatasi: {e}")

        interval = max(10, config.get("interval_minutes", 360)) * 60
        wait_until = time.time() + interval
        while _scheduler_running and time.time() < wait_until:
            time.sleep(10)


def start_scheduler() -> bool:
    global _scheduler_thread, _scheduler_running
    if _scheduler_running:
        return False
    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()
    return True


def stop_scheduler() -> bool:
    global _scheduler_running
    if not _scheduler_running:
        return False
    _scheduler_running = False
    return True


def is_scheduler_running() -> bool:
    return _scheduler_running
