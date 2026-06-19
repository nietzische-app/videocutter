"""Otomatik Shorts uretim zamanlayicisi — elle mudahale gerektirmez."""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from categories import CATEGORIES  # noqa: E402
from discovery import discover_for_category  # noqa: E402
from job_store import is_processed, load_scheduler_state, save_scheduler_state  # noqa: E402
from jobs import enqueue_job, run_shorts_job  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("scheduler")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def get_config() -> dict:
    categories_raw = os.getenv(
        "SCHEDULER_CATEGORIES",
        "comedy,film,football,roblox,foodporn,streamer",
    )
    categories = [c.strip() for c in categories_raw.split(",") if c.strip()]
    categories = [c for c in categories if c in CATEGORIES]

    cron = os.getenv("SCHEDULER_CRON", "").strip()
    interval_hours = float(os.getenv("SCHEDULER_INTERVAL_HOURS", "12"))

    return {
        "enabled": _env_bool("SCHEDULER_ENABLED", False),
        "categories": categories or list(CATEGORIES.keys()),
        "videos_per_category": int(os.getenv("SCHEDULER_VIDEOS_PER_CATEGORY", "1")),
        "max_per_run": int(os.getenv("SCHEDULER_MAX_PER_RUN", "6")),
        "clip_seconds": float(os.getenv("SCHEDULER_CLIP_SECONDS", "30")),
        "auto_upload": _env_bool("SCHEDULER_AUTO_UPLOAD", True),
        "cron": cron,
        "interval_hours": interval_hours,
    }


def run_scheduled_batch() -> dict:
    """Tek bir otomatik calisma dongusu."""
    config = get_config()
    api_key = os.getenv("OPENAI_API_KEY", "")

    if not api_key or api_key == "sk-...":
        raise RuntimeError("OPENAI_API_KEY ayarlanmamis.")

    started = datetime.now(timezone.utc).isoformat()
    log.info("Otomatik uretim basladi.")

    results: list[dict] = []
    created = 0

    for category in config["categories"]:
        if created >= config["max_per_run"]:
            break

        per_cat = 0
        try:
            videos = discover_for_category(category, limit=10)
        except Exception as exc:
            log.error("Kesif hatasi (%s): %s", category, exc)
            results.append({"category": category, "status": "discover_failed", "error": str(exc)})
            continue

        for video in videos:
            if created >= config["max_per_run"]:
                break
            if per_cat >= config["videos_per_category"]:
                break

            video_id = video.get("id", "")
            if not video_id or is_processed(video_id):
                continue

            log.info("Isleniyor: [%s] %s", category, video.get("title", "")[:60])

            payload = {
                "video_input": video["url"],
                "category": category,
                "clip_seconds": config["clip_seconds"],
                "source_channel": video.get("channel"),
                "source_url": video["url"],
                "source_video_id": video_id,
                "auto_upload": config["auto_upload"],
                "scheduled": True,
                "blocking": True,
            }

            try:
                response, status = enqueue_job(payload)
                job = response.get("job", {})
                job_status = job.get("status", "unknown")
                results.append(
                    {
                        "category": category,
                        "video_id": video_id,
                        "title": video.get("title"),
                        "job_id": response.get("job_id"),
                        "status": job_status,
                    }
                )
                if job_status == "done":
                    created += 1
                    per_cat += 1
                    log.info("Tamamlandi: %s", video_id)
                else:
                    log.warning("Basarisiz: %s — %s", video_id, job.get("message"))
            except Exception as exc:
                log.error("Is hatasi: %s", exc)
                results.append({"category": category, "video_id": video_id, "status": "error", "error": str(exc)})

    summary = {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "created": created,
        "results": results,
    }

    save_scheduler_state(
        last_run=summary["finished_at"],
        last_result=summary,
        run_log=summary,
    )

    log.info("Otomatik uretim bitti: %d video uretildi.", created)
    return summary


def _parse_cron(cron: str):
    """Basit cron: 'minute hour * * *' — APScheduler CronTrigger."""
    from apscheduler.triggers.cron import CronTrigger

    parts = cron.split()
    if len(parts) != 5:
        raise ValueError(f"Gecersiz SCHEDULER_CRON: {cron}")
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )


def start_scheduler(block: bool = True) -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.schedulers.base import BaseScheduler

    config = get_config()
    if not config["enabled"]:
        log.info("SCHEDULER_ENABLED=false — zamanlayici kapali.")
        return

    if block:
        scheduler: BaseScheduler = BlockingScheduler(timezone=os.getenv("SCHEDULER_TIMEZONE", "Europe/Istanbul"))
    else:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(timezone=os.getenv("SCHEDULER_TIMEZONE", "Europe/Istanbul"))

    if config["cron"]:
        trigger = _parse_cron(config["cron"])
        log.info("Cron zamanlama: %s", config["cron"])
    else:
        from apscheduler.triggers.interval import IntervalTrigger

        trigger = IntervalTrigger(hours=config["interval_hours"])
        log.info("Aralik zamanlama: her %.1f saat", config["interval_hours"])

    scheduler.add_job(
        run_scheduled_batch,
        trigger=trigger,
        id="shorts_autopilot",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    save_scheduler_state(
        enabled=True,
        config={k: v for k, v in config.items()},
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    # Ilk calistirmayi hemen yap (opsiyonel)
    if _env_bool("SCHEDULER_RUN_ON_START", True):
        log.info("Baslangicta ilk uretim calistiriliyor...")
        try:
            run_scheduled_batch()
        except Exception as exc:
            log.error("Ilk calistirma hatasi: %s", exc)

    next_runs = scheduler.get_jobs()
    if next_runs:
        nxt = next_runs[0].next_run_time
        save_scheduler_state(next_run=nxt.isoformat() if nxt else None)

    log.info("Zamanlayici aktif. Durdurmak icin Ctrl+C.")
    if block:
        scheduler.start()
    else:
        scheduler.start()
        return scheduler


def start_background_scheduler():
    """Flask/gunicorn icinde arka planda calistir."""
    return start_scheduler(block=False)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        summary = run_scheduled_batch()
        print(summary)
        return

    start_scheduler(block=True)


if __name__ == "__main__":
    main()
