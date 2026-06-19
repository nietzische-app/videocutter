import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file

load_dotenv()

from categories import list_categories  # noqa: E402
from discovery import discover_for_category  # noqa: E402

try:
    from youtube_upload import is_configured as youtube_configured
    from youtube_upload import upload_short
except ImportError:
    def youtube_configured() -> bool:
        return False

    def upload_short(*args, **kwargs):
        raise RuntimeError("YouTube kutuphanesi kurulu degil.")


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", PROJECT_DIR / "outputs")).resolve()
JOBS: dict[str, dict] = {}

app = Flask(__name__)


def set_job(job_id: str, **updates) -> None:
    JOBS.setdefault(job_id, {}).update(updates)


def check_dependencies() -> dict:
    return {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "openai_api_key": bool(os.getenv("OPENAI_API_KEY")),
        "youtube_upload": youtube_configured(),
    }


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
    auto_upload: bool = False,
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

    gpt_model = os.getenv("GPT_MODEL")
    whisper_model = os.getenv("WHISPER_MODEL")
    language = os.getenv("WHISPER_LANGUAGE", "tr")
    if gpt_model:
        command.extend(["--gpt-model", gpt_model])
    if whisper_model:
        command.extend(["--whisper-model", whisper_model])
    if language:
        command.extend(["--language", language])

    set_job(job_id, status="running", message="Shorts uretiliyor...", output=None, log="")

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


def start_job(payload: dict) -> tuple[dict, int]:
    video_input = str(payload.get("video_input", "")).strip()
    api_key = str(payload.get("api_key", "")).strip() or os.getenv("OPENAI_API_KEY", "")
    category = str(payload.get("category", "comedy")).strip()
    clip_seconds = float(payload.get("clip_seconds") or 30)
    title = payload.get("title") or None
    source_channel = payload.get("source_channel") or None
    source_url = payload.get("source_url") or video_input
    auto_upload = bool(payload.get("auto_upload", False))

    if not video_input:
        return {"error": "Video linki gerekli."}, 400
    if not api_key or api_key == "sk-...":
        return {"error": "OpenAI API key gerekli."}, 400
    if clip_seconds <= 0:
        return {"error": "Klip suresi pozitif olmali."}, 400

    deps = check_dependencies()
    if not deps["ffmpeg"]:
        return {"error": "ffmpeg kurulu degil."}, 500

    job_id = uuid.uuid4().hex[:12]
    set_job(
        job_id,
        status="queued",
        message="Siraya alindi.",
        created_at=time.time(),
        category=category,
        video_input=video_input,
        title=title,
    )

    thread = threading.Thread(
        target=run_shorts_job,
        kwargs={
            "job_id": job_id,
            "video_input": video_input,
            "api_key": api_key,
            "category": category,
            "clip_seconds": clip_seconds,
            "title": title,
            "source_channel": source_channel,
            "source_url": source_url,
            "auto_upload": auto_upload,
        },
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}, 200


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/categories")
def api_categories():
    return jsonify(list_categories())


@app.post("/api/discover")
def api_discover():
    payload = request.get_json(silent=True) or {}
    category = str(payload.get("category", "comedy")).strip()
    limit = min(int(payload.get("limit") or 8), 20)
    try:
        videos = discover_for_category(category, limit=limit)
        return jsonify({"category": category, "videos": videos})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/jobs")
def create_job():
    payload = request.get_json(silent=True) or {}
    result, status = start_job(payload)
    return jsonify(result), status


@app.get("/api/jobs")
def list_jobs():
    items = sorted(JOBS.values(), key=lambda j: j.get("created_at", 0), reverse=True)
    return jsonify({"jobs": items[:50]})


@app.get("/health")
def health():
    deps = check_dependencies()
    return jsonify({"ok": deps["ffmpeg"], **deps}), 200 if deps["ffmpeg"] else 503


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Is bulunamadi."}), 404

    response = dict(job)
    if response.get("output"):
        response["download_url"] = f"/download/{job_id}"
    return jsonify(response)


@app.post("/api/jobs/<job_id>/upload")
def upload_job(job_id: str):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        return jsonify({"error": "Tamamlanmis is bulunamadi."}), 404
    if not youtube_configured():
        return jsonify({"error": "YouTube OAuth ayarlanmamis. youtube_upload.py --auth calistirin."}), 400

    metadata = job.get("metadata") or {}
    try:
        result = upload_short(
            Path(job["output"]),
            title=metadata.get("youtube_title", "Short"),
            description=metadata.get("description", ""),
            tags=[t.lstrip("#") for t in metadata.get("hashtags", [])],
            privacy=os.getenv("YOUTUBE_PRIVACY", "private"),
        )
        set_job(job_id, youtube=result, message="YouTube'a yuklendi.")
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/download/<job_id>")
def download(job_id: str):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done" or not job.get("output"):
        return jsonify({"error": "Dosya hazir degil."}), 404
    return send_file(job["output"], as_attachment=True, download_name=f"short_{job_id}.mp4")


@app.get("/download/<job_id>/metadata")
def download_metadata(job_id: str):
    job = JOBS.get(job_id)
    meta_path = job.get("metadata_path") if job else None
    if not meta_path or not Path(meta_path).exists():
        return jsonify({"error": "Metadata bulunamadi."}), 404
    return send_file(meta_path, as_attachment=True, download_name=f"short_{job_id}.json")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    deps = check_dependencies()
    if not deps["ffmpeg"]:
        print("UYARI: ffmpeg bulunamadi.", file=sys.stderr)
    if not deps["openai_api_key"]:
        print("UYARI: OPENAI_API_KEY ayarlanmamis.", file=sys.stderr)

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "7860"))
    app.run(host=host, port=port, debug=False)
