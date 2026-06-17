"""Otomasyon zamanlayıcı — trend videoları keşfet, kliple, kuyruğa al."""

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from trend_discovery import discover_niche_videos, mark_processed, get_available_niches

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
    """Tek seferlik trend keşfi + klipleme. Bulunan videoları döndürür."""
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

    return results


def _process_video(video: dict, config: dict, openai_api_key: str) -> dict:
    """Tek bir videoyu kliple."""
    video_url = video["url"]
    video_id = video["video_id"]
    timestamp = int(time.time())

    output_path = OUTPUT_DIR / f"trend_{video_id}_{timestamp}.mp4"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    caption = video.get("title", "")[:200] if config.get("auto_caption") else ""

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
