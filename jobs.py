"""Shorts uretim isleri — app ve scheduler ortak kullanir."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from job_store import mark_processed, set_job

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", PROJECT_DIR / "outputs")).resolve()

try:
    from youtube_upload import is_configured as youtube_configured
    from youtube_upload import upload_short
except ImportError:
    def youtube_configured() -> bool:
        return False

    def upload_short(*args, **kwargs):
        raise RuntimeError("YouTube kutuphanesi kurulu degil.")


def run_shorts_job(
    job_id: str,
    video_input: str,
    api_key: str,
    *,
    category: str,
    clip_seconds: float,
    title: str | None = None,
    source_channel: str | None = None,
    source_url: str | None = None,
    source_video_id: str | None = None,
    auto_upload: bool = False,
    scheduled: bool = False,
) -> None:
    output_path = OUTPUT_DIR / f"short_{job_id}.mp4"
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = api_key

    command = [
        sys.executable,
        str(PROJECT_DIR / "shorts_pipeline.py"),
        video_input,
        "-o",
        str(output_path),
        "--category",
        category,
        "--clip-seconds",
        str(clip_seconds),
    ]

    if title:
        command.extend(["--title", title])
    if source_channel:
        command.extend(["--source-channel", source_channel])
    if source_url:
        command.extend(["--source-url", source_url])

    for env_key, flag in (
        ("GPT_MODEL", "--gpt-model"),
        ("WHISPER_MODEL", "--whisper-model"),
    ):
        if os.getenv(env_key):
            command.extend([flag, os.getenv(env_key)])

    language = os.getenv("WHISPER_LANGUAGE", "tr")
    if language:
        command.extend(["--language", language])

    set_job(
        job_id,
        status="running",
        message="Shorts uretiliyor...",
        output=None,
        log="",
        category=category,
        video_input=video_input,
        title=title,
        scheduled=scheduled,
        source_video_id=source_video_id,
    )

    try:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        log_lines: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            log_lines.append(line.rstrip())
            set_job(job_id, log="\n".join(log_lines[-100:]), message=line.strip() or "Calisiyor...")

        return_code = process.wait()
        metadata_path = output_path.with_suffix(".json")

        if return_code != 0:
            set_job(
                job_id,
                status="failed",
                message=f"Islem basarisiz: {log_lines[-1] if log_lines else 'Bilinmeyen hata'}",
                log="\n".join(log_lines[-150:]),
            )
            return

        if not output_path.exists():
            set_job(job_id, status="failed", message="Cikti dosyasi bulunamadi.", log="\n".join(log_lines[-150:]))
            return

        metadata = {}
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        youtube_result = None
        if auto_upload and youtube_configured() and metadata:
            set_job(job_id, message="YouTube'a yukleniyor...")
            try:
                youtube_result = upload_short(
                    output_path,
                    title=metadata.get("youtube_title", "Short"),
                    description=metadata.get("description", ""),
                    tags=[t.lstrip("#") for t in metadata.get("hashtags", [])],
                    privacy=os.getenv("YOUTUBE_PRIVACY", "private"),
                )
            except Exception as exc:
                metadata["upload_error"] = str(exc)

        if source_video_id:
            mark_processed(source_video_id)

        set_job(
            job_id,
            status="done",
            message="Bitti.",
            output=str(output_path),
            metadata=metadata,
            metadata_path=str(metadata_path) if metadata_path.exists() else None,
            youtube=youtube_result,
            log="\n".join(log_lines[-150:]),
        )
    except Exception as exc:
        set_job(job_id, status="failed", message=str(exc))


def enqueue_job(payload: dict) -> tuple[dict, int]:
    video_input = str(payload.get("video_input", "")).strip()
    api_key = str(payload.get("api_key", "")).strip() or os.getenv("OPENAI_API_KEY", "")
    category = str(payload.get("category", "comedy")).strip()
    clip_seconds = float(payload.get("clip_seconds") or 30)
    title = payload.get("title") or None
    source_channel = payload.get("source_channel") or None
    source_url = payload.get("source_url") or video_input
    source_video_id = payload.get("source_video_id") or None
    auto_upload = bool(payload.get("auto_upload", False))
    scheduled = bool(payload.get("scheduled", False))
    blocking = bool(payload.get("blocking", False))

    if not video_input:
        return {"error": "Video linki gerekli."}, 400
    if not api_key or api_key == "sk-...":
        return {"error": "OpenAI API key gerekli."}, 400
    if clip_seconds <= 0:
        return {"error": "Klip suresi pozitif olmali."}, 400

    job_id = uuid.uuid4().hex[:12]
    set_job(
        job_id,
        status="queued",
        message="Siraya alindi.",
        category=category,
        video_input=video_input,
        title=title,
        scheduled=scheduled,
        source_video_id=source_video_id,
    )

    kwargs = {
        "job_id": job_id,
        "video_input": video_input,
        "api_key": api_key,
        "category": category,
        "clip_seconds": clip_seconds,
        "title": title,
        "source_channel": source_channel,
        "source_url": source_url,
        "source_video_id": source_video_id,
        "auto_upload": auto_upload,
        "scheduled": scheduled,
    }

    if blocking:
        run_shorts_job(**kwargs)
        from job_store import get_job
        return {"job_id": job_id, "job": get_job(job_id)}, 200

    thread = threading.Thread(target=run_shorts_job, kwargs=kwargs, daemon=True)
    thread.start()
    return {"job_id": job_id}, 200
