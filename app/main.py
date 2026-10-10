"""Local-first AI Video Studio API and per-scene render pipeline."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError, field_validator

from .animation import (add_audio_track, animate, concat_scenes,
                        normalize_image, render_size, text_poster,
                        transcode_scene)
from .comfy import (check_connection, generate as generate_wan,
                    validate_server_url, validate_workflow)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "outputs"
UPLOAD = ROOT / "uploads"
WEB = ROOT / "web"
ENV_PATH = ROOT / ".env"
OUTPUT.mkdir(exist_ok=True)
UPLOAD.mkdir(exist_ok=True)
load_dotenv(ENV_PATH)
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188")
try:
    COMFYUI_TIMEOUT_SECONDS = min(7200, max(60, int(os.getenv("COMFYUI_TIMEOUT_SECONDS", "2400"))))
except ValueError:
    COMFYUI_TIMEOUT_SECONDS = 2400

app = FastAPI(title="AI Video Studio", version="2.0.0")
app.mount("/static", StaticFiles(directory=WEB), name="static")
_jobs: dict[str, dict] = {}
_mutex = threading.Lock()
_worker_limit = threading.Semaphore(1)
MAX_IMAGE = 12 * 1024 * 1024
MAX_AUDIO = 16 * 1024 * 1024
MAX_PROJECT_UPLOAD = 64 * 1024 * 1024
MAX_SCENES = 20
MAX_PROJECT_DURATION = 60
Image.MAX_IMAGE_PIXELS = 22_000_000


class SceneSpec(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    engine: Literal["local", "wan"] = "local"
    prompt: str = Field(default="", max_length=1800)
    duration: int = Field(ge=1, le=12)
    motion: Literal["zoom_in", "zoom_out", "pan_left", "pan_right"] = "zoom_in"
    overlay: str = Field(default="", max_length=180)
    image_index: int | None = Field(default=None, ge=0, le=MAX_SCENES - 1)

    @field_validator("id")
    @classmethod
    def safe_scene_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise ValueError("Scene IDs may contain only letters, numbers, hyphens, and underscores")
        return value


class ProjectSpec(BaseModel):
    scenes: list[SceneSpec] = Field(min_length=1, max_length=MAX_SCENES)
    orientation: Literal["portrait", "landscape"] = "portrait"
    resolution: Literal[540, 720, 1080] = 720
    fps: int = Field(default=24, ge=12, le=60)


class ComfySettings(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    timeout_seconds: int = Field(default=2400, ge=60, le=7200)


def _set(job_id: str, **updates) -> None:
    with _mutex:
        _jobs[job_id].update(updates)


def _set_scene(job_id: str, index: int, **updates) -> None:
    with _mutex:
        _jobs[job_id]["scene_progress"][index].update(updates)


def _read_file(file: UploadFile, target: Path, max_bytes: int) -> int:
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
    return written


def _store_image(file: UploadFile, target: Path) -> int:
    if Path(file.filename or "").suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(422, "Supported image types: PNG, JPG, WEBP")
    raw = target.with_suffix(".upload")
    written = _read_file(file, raw, MAX_IMAGE)
    try:
        with Image.open(raw) as img:
            if img.width * img.height > 22_000_000:
                raise HTTPException(413, "Image dimensions are too large")
            img.load()
            ImageOps.exif_transpose(img).convert("RGB").save(target, "JPEG", quality=92)
    except HTTPException:
        raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Image could not be decoded safely") from exc
    finally:
        raw.unlink(missing_ok=True)
    return written


def _save_env_settings(url: str, timeout_seconds: int) -> None:
    values = {"COMFYUI_URL": url, "COMFYUI_TIMEOUT_SECONDS": str(timeout_seconds)}
    original = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.is_file() else ""
    seen: set[str] = set()
    lines = []
    for line in original.splitlines():
        match = re.match(r"^\s*(COMFYUI_URL|COMFYUI_TIMEOUT_SECONDS)\s*=", line)
        if match:
            key = match.group(1)
            if key not in seen:
                lines.append(f"{key}={values[key]}")
                seen.add(key)
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in values.items() if key not in seen)
    temporary = ENV_PATH.with_name(f"{ENV_PATH.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        temporary.replace(ENV_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_project(project: ProjectSpec, references: list[UploadFile] | None) -> None:
    references = references or []
    if len(references) > MAX_SCENES:
        raise HTTPException(422, f"A project can have at most {MAX_SCENES} reference images")
    total_duration = sum(scene.duration for scene in project.scenes)
    if total_duration > MAX_PROJECT_DURATION:
        raise HTTPException(422, f"A project can be at most {MAX_PROJECT_DURATION} seconds")
    used_indices = set()
    for scene in project.scenes:
        if scene.image_index is not None:
            used_indices.add(scene.image_index)
        if scene.engine == "wan":
            if not scene.prompt.strip():
                raise HTTPException(422, f"Scene {scene.id}: Wan 2.2 needs a text prompt")
            if not 3 <= scene.duration <= 6:
                raise HTTPException(422, f"Scene {scene.id}: Wan duration must be 3–6 seconds")
    if used_indices != set(range(len(references))):
        raise HTTPException(422, "Reference image list does not match the scene references")


def _render_project(job_id: str, project: ProjectSpec, reference_paths: list[Path],
                    music_path: Path | None, job_dir: Path) -> None:
    with _worker_limit:
        _set(job_id, status="running", progress="Preparing scenes")
        output_path = OUTPUT / f"{job_id}.mp4"
        current_index: int | None = None
        try:
            size = render_size(project.orientation, project.resolution)
            rendered_scenes: list[Path] = []
            for index, scene in enumerate(project.scenes):
                current_index = index
                image_path = reference_paths[scene.image_index] if scene.image_index is not None else None
                raw_path = job_dir / f"scene-{index:02d}-raw.mp4"
                final_scene = job_dir / f"scene-{index:02d}.mp4"
                _set_scene(job_id, index, status="rendering", progress=f"Rendering scene {index + 1} of {len(project.scenes)}")

                def report(message: str, i: int = index) -> None:
                    _set_scene(job_id, i, progress=message)
                    _set(job_id, progress=f"Scene {i + 1} of {len(project.scenes)}: {message}")

                if scene.engine == "local":
                    poster = job_dir / f"scene-{index:02d}-poster.jpg"
                    if image_path:
                        normalize_image(image_path, poster, project.orientation, size)
                    else:
                        text_poster(scene.prompt, poster, project.orientation, size)
                    report("Animating image with local FFmpeg")
                    animate(poster, final_scene, scene.duration, project.orientation,
                            scene.motion, size=size, fps=project.fps,
                            overlay_text=scene.overlay)
                    poster.unlink(missing_ok=True)
                else:
                    report("Submitting scene to configured ComfyUI server")
                    motion_guidance = {
                        "zoom_in": "slow camera push-in",
                        "zoom_out": "slow camera pull-back",
                        "pan_left": "camera pans left",
                        "pan_right": "camera pans right",
                    }[scene.motion]
                    wan_prompt = f"{scene.prompt.strip()} Camera motion guidance: {motion_guidance}."
                    generate_wan(COMFYUI_URL, wan_prompt, project.orientation,
                                 scene.duration, raw_path, image_path=image_path,
                                 fps=16, max_wait_seconds=COMFYUI_TIMEOUT_SECONDS,
                                 on_progress=report)
                    report("Normalizing ComfyUI video for the project")
                    transcode_scene(raw_path, final_scene, scene.duration,
                                    project.orientation, project.resolution,
                                    project.fps, scene.overlay)
                    raw_path.unlink(missing_ok=True)

                rendered_scenes.append(final_scene)
                _set_scene(job_id, index, status="complete", progress="Scene ready")

            _set(job_id, progress="Combining scenes into one MP4")
            joined = job_dir / "joined.mp4"
            concat_scenes(rendered_scenes, job_dir / "scenes.txt", joined, project.fps)
            total_duration = sum(scene.duration for scene in project.scenes)
            if music_path:
                _set(job_id, progress="Adding soundtrack")
                add_audio_track(joined, music_path, output_path, total_duration)
            else:
                shutil.copyfile(joined, output_path)
            _set(job_id, status="complete", progress="Ready",
                 video_url=f"/api/videos/{job_id}")
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            if current_index is not None:
                _set_scene(job_id, current_index, status="error", error=str(exc)[:1000])
            _set(job_id, status="error", progress="Rendering failed", error=str(exc)[:1000])
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/settings")
def get_settings():
    try:
        validate_workflow()
        workflow_valid, workflow_error = True, None
    except ValueError as exc:
        workflow_valid, workflow_error = False, str(exc)
    return {"comfyui_url": COMFYUI_URL,
            "timeout_seconds": COMFYUI_TIMEOUT_SECONDS,
            "workflow_valid": workflow_valid,
            "workflow_error": workflow_error}


@app.post("/api/settings")
def save_settings(settings: ComfySettings):
    global COMFYUI_URL, COMFYUI_TIMEOUT_SECONDS
    try:
        url = validate_server_url(settings.url.strip())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if any(char.isspace() for char in url):
        raise HTTPException(422, "ComfyUI URL cannot contain whitespace")
    try:
        _save_env_settings(url, settings.timeout_seconds)
    except OSError as exc:
        raise HTTPException(500, "Could not save settings to .env") from exc
    COMFYUI_URL = url
    COMFYUI_TIMEOUT_SECONDS = settings.timeout_seconds
    return {"comfyui_url": COMFYUI_URL,
            "timeout_seconds": COMFYUI_TIMEOUT_SECONDS,
            "saved": True}


@app.get("/api/health")
def health():
    try:
        validate_workflow()
        workflow_valid = True
    except ValueError:
        workflow_valid = False
    connected = check_connection(COMFYUI_URL)
    return {"ok": True, "comfyui_connected": connected,
            "comfyui_url": COMFYUI_URL,
            "workflow_valid": workflow_valid,
            "inference_tested": False}


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
    """Keep the v1 single-scene API compatible for existing clients."""
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
            image_path = UPLOAD / f"{job_id}-image.jpg"
            _store_image(image, image_path)
        if audio:
            suffix = Path(audio.filename or "").suffix.lower()
            if suffix not in {".mp3", ".wav", ".m4a"}:
                raise HTTPException(422, "Supported audio types: MP3, WAV, M4A")
            audio_path = UPLOAD / f"{job_id}-music{suffix}"
            _read_file(audio, audio_path, MAX_AUDIO)
        with _mutex:
            _jobs[job_id] = {"id": job_id, "status": "queued", "progress": "Waiting for worker",
                             "video_url": None, "error": None, "mode": mode}
        background_tasks.add_task(_work, job_id, mode, prompt.strip(), orientation,
                                  duration, motion, image_path, audio_path)
        return {"id": job_id, "status": "queued"}
    except Exception:
        if image_path:
            image_path.unlink(missing_ok=True)
        if audio_path:
            audio_path.unlink(missing_ok=True)
        raise
    finally:
        if image:
            image.file.close()
        if audio:
            audio.file.close()


def _work(job_id: str, mode: str, prompt: str, orientation: str, duration: int,
          motion: str, image_path: Path | None, audio_path: Path | None) -> None:
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
                generate_wan(COMFYUI_URL, prompt, orientation, duration, output_path,
                             image_path=image_path, fps=16,
                             max_wait_seconds=COMFYUI_TIMEOUT_SECONDS,
                             on_progress=lambda status: _set(job_id, progress=status))
            _set(job_id, status="complete", progress="Ready", video_url=f"/api/videos/{job_id}")
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            _set(job_id, status="error", progress="Generation failed", error=str(exc)[:1000])
        finally:
            poster.unlink(missing_ok=True)
            if image_path:
                image_path.unlink(missing_ok=True)
            if audio_path:
                audio_path.unlink(missing_ok=True)


@app.post("/api/render", status_code=202)
def render_project(
    background_tasks: BackgroundTasks,
    project: str = Form(...),
    reference_images: list[UploadFile] = File(default=[]),
    music: UploadFile | None = File(None),
):
    if len(project) > 60_000:
        raise HTTPException(413, "Project description is too large")
    try:
        data = json.loads(project)
        spec = ProjectSpec.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        detail = str(exc)[:1200]
        raise HTTPException(422, f"Invalid project: {detail}") from exc
    _validate_project(spec, reference_images)
    job_id = uuid.uuid4().hex
    job_dir = UPLOAD / job_id
    job_dir.mkdir()
    reference_paths: list[Path] = []
    music_path = None
    total_upload_bytes = 0
    try:
        for index, upload in enumerate(reference_images):
            target = job_dir / f"reference-{index:02d}.jpg"
            total_upload_bytes += _store_image(upload, target)
            reference_paths.append(target)
            if total_upload_bytes > MAX_PROJECT_UPLOAD:
                raise HTTPException(413, "Combined project uploads exceed the 64 MB limit")
        if music:
            suffix = Path(music.filename or "").suffix.lower()
            if suffix not in {".mp3", ".wav", ".m4a"}:
                raise HTTPException(422, "Supported audio types: MP3, WAV, M4A")
            music_path = job_dir / f"music{suffix}"
            total_upload_bytes += _read_file(music, music_path, MAX_AUDIO)
            if total_upload_bytes > MAX_PROJECT_UPLOAD:
                raise HTTPException(413, "Combined project uploads exceed the 64 MB limit")

        progress = [{"id": scene.id, "status": "queued", "progress": "Waiting", "error": None}
                    for scene in spec.scenes]
        with _mutex:
            _jobs[job_id] = {"id": job_id, "status": "queued", "progress": "Waiting for worker",
                             "video_url": None, "error": None, "scene_progress": progress,
                             "orientation": spec.orientation, "resolution": spec.resolution,
                             "fps": spec.fps}
        background_tasks.add_task(_render_project, job_id, spec, reference_paths,
                                  music_path, job_dir)
        return {"id": job_id, "status": "queued", "scenes": progress}
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    finally:
        for upload in reference_images:
            upload.file.close()
        if music:
            music.file.close()


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
    return FileResponse(path, media_type="video/mp4", filename=f"ai-video-{job_id[:8]}.mp4",
                        content_disposition_type="inline")
