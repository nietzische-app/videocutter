import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", PROJECT_DIR / "outputs")).resolve()
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", PROJECT_DIR / "uploads")).resolve()
JOBS: dict[str, dict] = {}

MAX_JOBS_PER_IP = 5
RATE_WINDOW = 3600
CLEANUP_MAX_AGE = 3600
MAX_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB

_rate_limit: dict[str, list[float]] = defaultdict(list)
_SAFE_JOB_ID_RE = re.compile(r"^[a-f0-9]{12}$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE


def set_job(job_id: str, **updates) -> None:
    JOBS.setdefault(job_id, {}).update(updates)


def check_rate_limit(ip: str) -> bool:
    now = time.time()
    timestamps = _rate_limit[ip]
    _rate_limit[ip] = [t for t in timestamps if now - t < RATE_WINDOW]
    if len(_rate_limit[ip]) >= MAX_JOBS_PER_IP:
        return False
    _rate_limit[ip].append(now)
    return True


def is_safe_video_input(value: str) -> bool:
    if any(c in value for c in (";", "|", "&", "`", "$", "\n", "\r")):
        return False
    if value.startswith(("http://", "https://")):
        return True
    if ".." in value:
        return False
    return True


def cleanup_loop() -> None:
    while True:
        time.sleep(300)
        now = time.time()
        expired = [
            jid for jid, j in list(JOBS.items())
            if j.get("status") in ("done", "failed")
            and now - j.get("created_at", now) > CLEANUP_MAX_AGE
        ]
        for jid in expired:
            job = JOBS.pop(jid, {})
            output = job.get("output")
            if output:
                try:
                    Path(output).unlink(missing_ok=True)
                except Exception:
                    pass
            upload = job.get("upload_path")
            if upload:
                try:
                    Path(upload).unlink(missing_ok=True)
                except Exception:
                    pass


def run_video_job(job_id: str, video_input: str, api_key: str, clip_seconds: float, subtitle_style: str = "bold") -> None:
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
        "--num-clips",
        "3",
        "--subtitle-style",
        subtitle_style,
    ]

    set_job(job_id, status="running", message="Video isleniyor...", output=None, log="", step="", candidates=None)

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
        candidates_json = None
        assert process.stdout is not None
        for line in process.stdout:
            stripped = line.strip()
            log_lines.append(line.rstrip())

            if stripped.startswith("CANDIDATES_JSON:"):
                try:
                    candidates_json = json.loads(stripped[len("CANDIDATES_JSON:"):])
                except Exception:
                    pass
                continue

            step_match = re.match(r"STEP:(\d+/\d+)\s+(.*)", stripped)
            if step_match:
                set_job(
                    job_id,
                    step=step_match.group(1),
                    message=step_match.group(2),
                    log="\n".join(log_lines[-80:]),
                )
            else:
                set_job(job_id, log="\n".join(log_lines[-80:]), message=stripped or "Calisiyor...")

        return_code = process.wait()
        if return_code != 0:
            set_job(job_id, status="failed", message="Islem basarisiz oldu.", log="\n".join(log_lines[-120:]))
            return

        # Build outputs list for multiple candidates
        outputs = []
        if output_path.exists():
            outputs.append({"path": str(output_path), "label": "Aday #1"})
        for i in range(2, 4):
            alt = output_path.parent / f"{output_path.stem}_aday{i}{output_path.suffix}"
            if alt.exists():
                outputs.append({"path": str(alt), "label": f"Aday #{i}"})

        set_job(
            job_id,
            status="done",
            message="Bitti!",
            output=str(output_path),
            outputs=outputs,
            candidates=candidates_json,
            log="\n".join(log_lines[-120:]),
        )
    except Exception as exc:
        set_job(job_id, status="failed", message=str(exc))


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/upload")
def upload_video():
    if "file" not in request.files:
        return jsonify({"error": "Dosya bulunamadi."}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Dosya adi bos."}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".flv", ".wmv"):
        return jsonify({"error": "Desteklenmeyen dosya formati. MP4, MKV, AVI, MOV, WEBM desteklenir."}), 400

    file_id = uuid.uuid4().hex[:12]
    safe_name = f"upload_{file_id}{ext}"
    save_path = UPLOAD_DIR / safe_name
    file.save(str(save_path))

    return jsonify({"path": str(save_path), "filename": file.filename})


@app.post("/api/jobs")
def create_job():
    payload = request.get_json(force=True)
    video_input = str(payload.get("video_input", "")).strip()
    api_key = str(payload.get("api_key", "")).strip() or os.getenv("OPENAI_API_KEY", "")
    clip_seconds = float(payload.get("clip_seconds") or 30)
    subtitle_style = str(payload.get("subtitle_style", "bold")).strip()
    if subtitle_style not in ("bold", "highlight", "minimal", "none"):
        subtitle_style = "bold"

    if not video_input:
        return jsonify({"error": "Video yukleyin veya YouTube linki girin."}), 400
    if not is_safe_video_input(video_input):
        return jsonify({"error": "Gecersiz video girisi."}), 400
    if not api_key or api_key == "sk-...":
        return jsonify({"error": "OpenAI API key gerekli."}), 400
    if clip_seconds < 5 or clip_seconds > 180:
        return jsonify({"error": "Klip suresi 5-180 saniye arasi olmali."}), 400

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not check_rate_limit(client_ip):
        return jsonify({"error": "Cok fazla istek. Lutfen bir saat bekleyin."}), 429

    job_id = uuid.uuid4().hex[:12]
    upload_path = video_input if video_input.startswith(str(UPLOAD_DIR)) else None
    set_job(job_id, status="queued", message="Sira alindi.", created_at=time.time(), upload_path=upload_path)

    thread = threading.Thread(
        target=run_video_job,
        args=(job_id, video_input, api_key, clip_seconds, subtitle_style),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    if not _SAFE_JOB_ID_RE.match(job_id):
        return jsonify({"error": "Gecersiz job_id."}), 400
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Is bulunamadi."}), 404

    response = dict(job)
    response.pop("upload_path", None)

    outputs = response.get("outputs") or []
    if outputs:
        clip_list = []
        for i, out in enumerate(outputs):
            clip_list.append({
                "label": out.get("label", f"Aday #{i+1}"),
                "download_url": f"/download/{job_id}/{i}",
                "preview_url": f"/preview/{job_id}/{i}",
            })
        response["clip_list"] = clip_list

    if response.get("output"):
        response["download_url"] = f"/download/{job_id}/0"
        response["preview_url"] = f"/preview/{job_id}/0"

    response.pop("outputs", None)
    return jsonify(response)


def _get_output_path(job_id: str, clip_index: int) -> str | None:
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        return None
    outputs = job.get("outputs") or []
    if 0 <= clip_index < len(outputs):
        p = outputs[clip_index].get("path")
        if p and Path(p).exists():
            return p
    if clip_index == 0 and job.get("output"):
        return job["output"]
    return None


@app.get("/download/<job_id>/<int:clip_index>")
def download(job_id: str, clip_index: int):
    if not _SAFE_JOB_ID_RE.match(job_id):
        return jsonify({"error": "Gecersiz job_id."}), 400
    path = _get_output_path(job_id, clip_index)
    if not path:
        return jsonify({"error": "Dosya hazir degil."}), 404
    return send_file(path, as_attachment=True, download_name=f"clip_{clip_index+1}.mp4")


@app.get("/preview/<job_id>/<int:clip_index>")
def preview(job_id: str, clip_index: int):
    if not _SAFE_JOB_ID_RE.match(job_id):
        return jsonify({"error": "Gecersiz job_id."}), 400
    path = _get_output_path(job_id, clip_index)
    if not path:
        return jsonify({"error": "Dosya hazir degil."}), 404
    return send_file(path, mimetype="video/mp4", conditional=True)


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=cleanup_loop, daemon=True).start()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "7860"))
    app.run(host=host, port=port, debug=False)
