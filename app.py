import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", PROJECT_DIR / "outputs")).resolve()
JOBS: dict[str, dict] = {}

app = Flask(__name__)


def set_job(job_id: str, **updates) -> None:
    JOBS.setdefault(job_id, {}).update(updates)


def run_video_job(job_id: str, video_input: str, api_key: str, clip_seconds: float) -> None:
    output_path = OUTPUT_DIR / f"clip_{job_id}.mp4"
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = api_key

    command = [
        sys.executable,
        str(PROJECT_DIR / "video_cutter.py"),
        video_input,
        "-o",
        str(output_path),
        "--clip-seconds",
        str(clip_seconds),
    ]

    set_job(job_id, status="running", message="Video isleniyor...", output=None, log="")

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
            set_job(job_id, log="\n".join(log_lines[-80:]), message=line.strip() or "Calisiyor...")

        return_code = process.wait()
        if return_code != 0:
            set_job(job_id, status="failed", message="Islem basarisiz oldu.", log="\n".join(log_lines[-120:]))
            return

        set_job(
            job_id,
            status="done",
            message="Bitti.",
            output=str(output_path),
            log="\n".join(log_lines[-120:]),
        )
    except Exception as exc:
        set_job(job_id, status="failed", message=str(exc))


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/jobs")
def create_job():
    payload = request.get_json(force=True)
    video_input = str(payload.get("video_input", "")).strip()
    api_key = str(payload.get("api_key", "")).strip() or os.getenv("OPENAI_API_KEY", "")
    clip_seconds = float(payload.get("clip_seconds") or 30)

    if not video_input:
        return jsonify({"error": "YouTube linki veya video yolu gerekli."}), 400
    if not api_key or api_key == "sk-...":
        return jsonify({"error": "OpenAI API key gerekli."}), 400
    if clip_seconds <= 0:
        return jsonify({"error": "Klip suresi pozitif olmali."}), 400

    job_id = uuid.uuid4().hex[:12]
    set_job(job_id, status="queued", message="Sira alindi.", created_at=time.time())

    thread = threading.Thread(
        target=run_video_job,
        args=(job_id, video_input, api_key, clip_seconds),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Is bulunamadi."}), 404

    response = dict(job)
    if response.get("output"):
        response["download_url"] = f"/download/{job_id}"
    return jsonify(response)


@app.get("/download/<job_id>")
def download(job_id: str):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done" or not job.get("output"):
        return jsonify({"error": "Dosya hazir degil."}), 404

    return send_file(job["output"], as_attachment=True, download_name="clip_vertical.mp4")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "7860"))
    app.run(host=host, port=port, debug=False)
