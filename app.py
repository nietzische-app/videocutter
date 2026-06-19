import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file

load_dotenv()

from categories import list_categories  # noqa: E402
from discovery import discover_for_category  # noqa: E402
from job_store import get_job, list_jobs, load_scheduler_state  # noqa: E402
from jobs import enqueue_job  # noqa: E402
from scheduler_service import get_config, run_scheduled_batch  # noqa: E402

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

app = Flask(__name__)


def check_dependencies() -> dict:
    config = get_config()
    return {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "openai_api_key": bool(os.getenv("OPENAI_API_KEY")),
        "youtube_upload": youtube_configured(),
        "scheduler_enabled": config["enabled"],
    }


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
    result, status = enqueue_job(payload)
    return jsonify(result), status


@app.get("/api/jobs")
def api_list_jobs():
    return jsonify({"jobs": list_jobs()})


@app.get("/api/scheduler")
def api_scheduler_status():
    state = load_scheduler_state()
    config = get_config()
    return jsonify({"config": config, "state": state})


@app.post("/api/scheduler/run")
def api_scheduler_run_now():
    """Manuel tetikleme (test icin)."""
    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "OPENAI_API_KEY gerekli."}), 400
    try:
        summary = run_scheduled_batch()
        return jsonify(summary)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/health")
def health():
    deps = check_dependencies()
    return jsonify({"ok": deps["ffmpeg"], **deps}), 200 if deps["ffmpeg"] else 503


@app.get("/api/jobs/<job_id>")
def api_get_job(job_id: str):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Is bulunamadi."}), 404

    response = dict(job)
    if response.get("output"):
        response["download_url"] = f"/download/{job_id}"
    return jsonify(response)


@app.post("/api/jobs/<job_id>/upload")
def upload_job(job_id: str):
    job = get_job(job_id)
    if not job or job.get("status") != "done":
        return jsonify({"error": "Tamamlanmis is bulunamadi."}), 404
    if not youtube_configured():
        return jsonify({"error": "YouTube OAuth ayarlanmamis."}), 400

    metadata = job.get("metadata") or {}
    try:
        result = upload_short(
            Path(job["output"]),
            title=metadata.get("youtube_title", "Short"),
            description=metadata.get("description", ""),
            tags=[t.lstrip("#") for t in metadata.get("hashtags", [])],
            privacy=os.getenv("YOUTUBE_PRIVACY", "private"),
        )
        from job_store import set_job
        set_job(job_id, youtube=result, message="YouTube'a yuklendi.")
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/download/<job_id>")
def download(job_id: str):
    job = get_job(job_id)
    if not job or job.get("status") != "done" or not job.get("output"):
        return jsonify({"error": "Dosya hazir degil."}), 404
    return send_file(job["output"], as_attachment=True, download_name=f"short_{job_id}.mp4")


@app.get("/download/<job_id>/metadata")
def download_metadata(job_id: str):
    job = get_job(job_id)
    meta_path = job.get("metadata_path") if job else None
    if not meta_path or not Path(meta_path).exists():
        return jsonify({"error": "Metadata bulunamadi."}), 404
    return send_file(meta_path, as_attachment=True, download_name=f"short_{job_id}.json")


def _boot_scheduler():
    config = get_config()
    if not config["enabled"]:
        return
    # Ayri container kullaniliyorsa (docker-compose scheduler servisi) burada baslatma
    if os.getenv("SCHEDULER_STANDALONE", "").lower() in {"1", "true", "yes"}:
        return
    try:
        from scheduler_service import start_background_scheduler
        start_background_scheduler()
        print("Otomatik zamanlayici arka planda baslatildi.", file=sys.stderr)
    except Exception as exc:
        print(f"Zamanlayici baslatilamadi: {exc}", file=sys.stderr)


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    deps = check_dependencies()
    if not deps["ffmpeg"]:
        print("UYARI: ffmpeg bulunamadi.", file=sys.stderr)
    if not deps["openai_api_key"]:
        print("UYARI: OPENAI_API_KEY ayarlanmamis.", file=sys.stderr)

    _boot_scheduler()

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "7860"))
    app.run(host=host, port=port, debug=False)
