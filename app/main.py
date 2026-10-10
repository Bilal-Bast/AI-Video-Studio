"""AI Video Studio: web API + CPU animation + optional ComfyUI GPU jobs."""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from .animation import animate, normalize_image, text_poster
from .comfy import check_connection, generate

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "outputs"
UPLOAD = ROOT / "uploads"
WEB = ROOT / "web"
OUTPUT.mkdir(exist_ok=True)
UPLOAD.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188")

app = FastAPI(title="AI Video Studio", version="1.0.0")
app.mount("/static", StaticFiles(directory=WEB), name="static")
_jobs: dict[str, dict] = {}
_mutex = threading.Lock()
_worker_limit = threading.Semaphore(1)
MAX_IMAGE = 12 * 1024 * 1024
MAX_AUDIO = 16 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 22_000_000


def _set(job_id: str, **updates) -> None:
    with _mutex:
        _jobs[job_id].update(updates)


def _read_file(file: UploadFile, target: Path, max_bytes: int) -> None:
    written = 0
    with target.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                target.unlink(missing_ok=True)
                raise HTTPException(413, f"Upload is too large (limit {max_bytes // (1024 * 1024)} MB)")
            out.write(chunk)
    if written == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(422, "Empty upload")


def _work(job_id: str, mode: str, prompt: str, orientation: str, duration: int, motion: str,
          image_path: Path | None, audio_path: Path | None) -> None:
    with _worker_limit:
        _set(job_id, status="running", progress="Preparing video")
        poster = UPLOAD / f"{job_id}-poster.jpg"
        output_path = OUTPUT / f"{job_id}.mp4"
        try:
            if mode == "local":
                _set(job_id, progress="Building local animation with FFmpeg")
                if image_path:
                    normalize_image(image_path, poster, orientation)
                else:
                    text_poster(prompt, poster, orientation)
                animate(poster, output_path, duration, orientation, motion, audio_path)
            else:
                generate(COMFYUI_URL, prompt, orientation, duration, output_path,
                         image_path=image_path,
                         on_progress=lambda status: _set(job_id, progress=status))
            _set(job_id, status="complete", progress="Ready", video_url=f"/api/videos/{job_id}")
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            _set(job_id, status="error", progress="Generation failed", error=str(exc)[:1000])
        finally:
            poster.unlink(missing_ok=True)
            if image_path: image_path.unlink(missing_ok=True)
            if audio_path: audio_path.unlink(missing_ok=True)


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "comfyui_connected": check_connection(COMFYUI_URL)}


@app.post("/api/generate", status_code=202)
def submit(
    background_tasks: BackgroundTasks,
    mode: str = Form("local"),
    prompt: str = Form(""),
    orientation: str = Form("portrait"),
    duration: int = Form(4),
    motion: str = Form("zoom_in"),
    image: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
):
    if mode not in ("local", "wan"):
        raise HTTPException(422, "Invalid generation mode")
    if orientation not in ("portrait", "landscape"):
        raise HTTPException(422, "Invalid orientation")
    if motion not in ("zoom_in", "zoom_out", "pan_left", "pan_right"):
        raise HTTPException(422, "Invalid camera motion")
    if not 3 <= duration <= (12 if mode == "local" else 6):
        raise HTTPException(422, "Invalid duration: local 3–12 seconds, Wan 3–6 seconds")
    if mode == "wan" and not prompt.strip():
        raise HTTPException(422, "Wan 2.2 needs a text prompt")
    if len(prompt) > 1800:
        raise HTTPException(422, "Prompt exceeds 1800 characters")
    if audio and mode == "wan":
        raise HTTPException(422, "Music upload is supported in Local Motion mode only")
    job_id = uuid.uuid4().hex
    image_path = None
    audio_path = None
    try:
        if image:
            if Path(image.filename or "").suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise HTTPException(422, "Supported image types: PNG, JPG, WEBP")
            image_path = UPLOAD / f"{job_id}-image.jpg"
            raw_path = UPLOAD / f"{job_id}-original"
            _read_file(image, raw_path, MAX_IMAGE)
            try:
                with Image.open(raw_path) as img:
                    if img.width * img.height > 22_000_000:
                        raise HTTPException(413, "Image dimensions are too large")
                    img.load()  # Reject malformed files and huge decompression bombs.
                    img.convert("RGB").save(image_path, "JPEG", quality=92)
            except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
                raise HTTPException(422, "Image could not be decoded safely") from exc
            finally:
                raw_path.unlink(missing_ok=True)
        if audio:
            suffix = Path(audio.filename or "").suffix.lower()
            if suffix not in {".mp3", ".wav", ".m4a"}:
                raise HTTPException(422, "Supported audio types: MP3, WAV, M4A")
            audio_path = UPLOAD / f"{job_id}-music{suffix}"
            _read_file(audio, audio_path, MAX_AUDIO)
        with _mutex:
            _jobs[job_id] = {"id": job_id, "status": "queued", "progress": "Waiting for worker", "video_url": None, "error": None, "mode": mode}
        background_tasks.add_task(_work, job_id, mode, prompt.strip(), orientation, duration, motion, image_path, audio_path)
        return {"id": job_id, "status": "queued"}
    except Exception:
        if image_path: image_path.unlink(missing_ok=True)
        if audio_path: audio_path.unlink(missing_ok=True)
        raise
    finally:
        if image: image.file.close()
        if audio: audio.file.close()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with _mutex:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job (jobs reset when server restarts)")
        return job.copy()


@app.get("/api/videos/{job_id}")
def get_video(job_id: str):
    with _mutex:
        job = _jobs.get(job_id)
        if not job or job["status"] != "complete":
            raise HTTPException(404, "Video is not available")
    path = OUTPUT / f"{job_id}.mp4"
    if not path.is_file():
        raise HTTPException(404, "Video file is missing")
    return FileResponse(path, media_type="video/mp4", filename=f"ai-video-{job_id[:8]}.mp4", content_disposition_type="inline")
