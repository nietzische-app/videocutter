"""Kalici is ve islenmis video kaydi."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_DIR / "data")).resolve()
JOBS_FILE = DATA_DIR / "jobs.json"
PROCESSED_FILE = DATA_DIR / "processed_videos.json"
SCHEDULER_STATE_FILE = DATA_DIR / "scheduler_state.json"

_lock = threading.Lock()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data) -> None:
    _ensure_data_dir()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_jobs() -> dict[str, dict]:
    with _lock:
        return _read_json(JOBS_FILE, {})


def save_jobs(jobs: dict[str, dict]) -> None:
    with _lock:
        _write_json(JOBS_FILE, jobs)


def get_job(job_id: str) -> dict | None:
    return load_jobs().get(job_id)


def set_job(job_id: str, **updates) -> dict:
    with _lock:
        jobs = _read_json(JOBS_FILE, {})
        job = jobs.setdefault(job_id, {})
        job.update(updates)
        if "created_at" not in job:
            job["created_at"] = time.time()
        jobs[job_id] = job
        _write_json(JOBS_FILE, jobs)
        return job


def list_jobs(limit: int = 50) -> list[dict]:
    jobs = load_jobs().values()
    return sorted(jobs, key=lambda j: j.get("created_at", 0), reverse=True)[:limit]


def load_processed_ids() -> set[str]:
    with _lock:
        data = _read_json(PROCESSED_FILE, {"video_ids": []})
        return set(data.get("video_ids", []))


def mark_processed(video_id: str) -> None:
    with _lock:
        data = _read_json(PROCESSED_FILE, {"video_ids": []})
        ids: set[str] = set(data.get("video_ids", []))
        ids.add(video_id)
        data["video_ids"] = sorted(ids)[-5000:]
        _write_json(PROCESSED_FILE, data)


def is_processed(video_id: str) -> bool:
    return video_id in load_processed_ids()


def load_scheduler_state() -> dict:
    with _lock:
        return _read_json(
            SCHEDULER_STATE_FILE,
            {
                "enabled": False,
                "last_run": None,
                "last_result": None,
                "next_run": None,
                "runs": [],
            },
        )


def save_scheduler_state(**updates) -> dict:
    with _lock:
        state = _read_json(SCHEDULER_STATE_FILE, {})
        state.update(updates)
        runs = state.get("runs", [])
        if "run_log" in updates:
            runs.insert(0, updates["run_log"])
            state["runs"] = runs[:30]
            state.pop("run_log", None)
        _write_json(SCHEDULER_STATE_FILE, state)
        return state
