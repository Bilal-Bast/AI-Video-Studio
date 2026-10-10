"""Run with python -m pytest -q (pytest is a dev-only dependency)."""
from fastapi.testclient import TestClient

from app.animation import animate, ffmpeg_binary, text_poster
from app.comfy import make_workflow
from app.main import app


def test_home_and_health():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "AI Video Studio" in response.text
        assert client.get("/static/app.js").status_code == 200
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        assert health.json()["workflow_valid"] is True
        assert health.json()["inference_tested"] is False


def test_api_validation():
    with TestClient(app) as client:
        assert client.post("/api/generate", data={"mode": "wan", "prompt": ""}).status_code == 422
        assert client.post("/api/generate", data={"mode": "local", "duration": "99"}).status_code == 422
        assert client.get("/api/jobs/not-a-real-job").status_code == 404


def test_workflow_for_text_and_image():
    wf = make_workflow("A small dog jumps", "portrait", 4)
    assert wf["6"]["inputs"]["text"] == "A small dog jumps"
    assert wf["55"]["inputs"]["length"] == 65
    assert "56" not in wf
    wf2 = make_workflow("A flying bird", "landscape", 3, "input.png")
    assert wf2["55"]["inputs"]["width"] == 800
    assert wf2["55"]["inputs"]["start_image"] == ["56", 0]
    wf3 = make_workflow("A bird", "portrait", 3, fps=24)
    assert wf3["57"]["inputs"]["fps"] == 24
    assert wf3["55"]["inputs"]["length"] == 73


def test_real_local_animation(tmp_path):
    """Tests a real FFmpeg MP4 render end-to-end without GPUs."""
    image = tmp_path / "poster.jpg"
    video = tmp_path / "short.mp4"
    text_poster("Hello from the free video maker!", image, "portrait")
    assert image.exists()
    assert ffmpeg_binary()
    animate(image, video, 3, "portrait", "zoom_in")
    assert video.exists() and video.stat().st_size > 1000
    assert video.read_bytes()[:8].endswith(b"ftyp")


def test_api_real_upload_and_download():
    import io
    import subprocess
    import wave
    from PIL import Image
    from app.animation import ffmpeg_binary
    from app.main import OUTPUT
    image = Image.new("RGB", (240, 400), (90, 50, 165))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    soundtrack = io.BytesIO()
    with wave.open(soundtrack, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 8000 * 4)
    with TestClient(app) as client:
        response = client.post(
            "/api/generate",
            data={"mode": "local", "prompt": "Demo", "orientation": "landscape", "duration": "3", "motion": "pan_left"},
            files=[("image", ("demo.png", buffer.getvalue(), "image/png")),
                   ("audio", ("music.wav", soundtrack.getvalue(), "audio/wav"))],
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        status = client.get(f"/api/jobs/{job_id}").json()
        assert status["status"] == "complete", status
        video = client.get(status["video_url"])
        assert video.status_code == 200
        assert video.headers["content-type"] == "video/mp4"
        assert "inline" in video.headers["content-disposition"]
        assert len(video.content) > 1000
        details = subprocess.run([ffmpeg_binary(), "-hide_banner", "-i", str(OUTPUT / f"{job_id}.mp4")], capture_output=True, text=True)
        assert "Audio:" in details.stderr, details.stderr
        (OUTPUT / f"{job_id}.mp4").unlink(missing_ok=True)


def test_comfy_adapter_with_mocked_http(tmp_path, monkeypatch):
    import json
    import httpx
    from app import comfy
    observed = {"uploaded": False, "submitted": False, "downloaded": False}
    fake_video = b"VIDEO_RESULT" * 25
    def handler(req):
        if req.url.path == "/system_stats":
            return httpx.Response(200, json={"system": {}})
        if req.url.path == "/upload/image":
            observed["uploaded"] = True
            return httpx.Response(200, json={"name": "test-reference.jpg"})
        if req.url.path == "/prompt":
            body = json.loads(req.content)
            assert body["prompt"]["6"]["inputs"]["text"] == "A dancing cockatiel"
            assert body["prompt"]["55"]["inputs"]["start_image"] == ["56", 0]
            observed["submitted"] = True
            return httpx.Response(200, json={"prompt_id": "1234567890abcdef"})
        if req.url.path == "/history/1234567890abcdef":
            return httpx.Response(200, json={"1234567890abcdef": {"status": {"completed": True}, "outputs": {"58": {"videos": [{"filename": "created.mp4", "type": "output", "subfolder": "video"}]}}}})
        if req.url.path == "/view":
            observed["downloaded"] = True
            return httpx.Response(200, content=fake_video)
        return httpx.Response(404)
    original = httpx.Client
    monkeypatch.setattr(comfy.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    image = tmp_path / "input.jpg"
    image.write_bytes(b"jpeg placeholder")
    output = tmp_path / "wan.mp4"
    comfy.generate("http://localhost:8188", "A dancing cockatiel", "portrait", 3, output, image, poll_interval=0)
    assert output.read_bytes() == fake_video
    assert all(observed.values())


def test_comfy_job_timeout_is_reported(monkeypatch, tmp_path):
    import httpx
    from app import comfy
    original = httpx.Client
    def handler(req):
        if req.url.path == "/system_stats":
            return httpx.Response(200, json={"system": {}})
        if req.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "timeout-job"})
        return httpx.Response(404)
    monkeypatch.setattr(comfy.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    try:
        comfy.generate("http://localhost:8188", "A short scene", "portrait", 3,
                       tmp_path / "timeout.mp4", max_wait_seconds=0)
    except TimeoutError as exc:
        assert "configured timeout (0 seconds)" in str(exc)
    else:
        raise AssertionError("Timed-out ComfyUI jobs must report an error")


def test_workflow_validation_and_render_sizes():
    from app.animation import render_size
    from app.comfy import validate_workflow
    assert validate_workflow()["58"]["class_type"] == "SaveVideo"
    assert render_size("portrait", 720) == (720, 1280)
    assert render_size("landscape", 1080) == (1920, 1080)
    try:
        validate_workflow({"55": {"class_type": "WrongNode", "inputs": {}}})
    except ValueError as exc:
        assert "required node" in str(exc)
    else:
        raise AssertionError("Invalid ComfyUI workflow was accepted")


def test_project_renders_local_and_mocked_wan_scenes(tmp_path, monkeypatch):
    import json
    import io
    import subprocess
    import wave
    from app import main
    from app.animation import animate, ffmpeg_binary, render_size, text_poster
    from PIL import Image

    calls = []
    def fake_wan(base_url, prompt, orientation, duration, output_path,
                 image_path=None, on_progress=None, **kwargs):
        calls.append((prompt, kwargs.get("fps")))
        assert image_path is not None and image_path.is_file()
        poster = tmp_path / "mock-wan-poster.jpg"
        text_poster(prompt, poster, orientation, render_size(orientation, 540))
        animate(poster, output_path, duration, orientation, "zoom_in",
                fps=16, size=render_size(orientation, 540))
        if on_progress:
            on_progress("Mocked ComfyUI result (no GPU inference)")

    monkeypatch.setattr(main, "generate_wan", fake_wan)
    payload = {
        "orientation": "portrait", "resolution": 540, "fps": 12,
        "scenes": [
            {"id": "intro", "engine": "local", "prompt": "Opening scene", "duration": 1,
             "motion": "pan_left", "overlay": "Scene one", "image_index": 0},
            {"id": "ai-scene", "engine": "wan", "prompt": "A little robot waves", "duration": 3,
             "motion": "zoom_in", "overlay": "Generated on configured ComfyUI", "image_index": 1},
        ],
    }
    reference = io.BytesIO()
    Image.new("RGB", (120, 180), (90, 50, 165)).save(reference, format="PNG")
    references = reference.getvalue()
    soundtrack = io.BytesIO()
    with wave.open(soundtrack, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * 8000 * 5)
    with TestClient(app) as client:
        response = client.post("/api/render", data={"project": json.dumps(payload)}, files=[
            ("reference_images", ("local.png", references, "image/png")),
            ("reference_images", ("wan.png", references, "image/png")),
            ("music", ("music.wav", soundtrack.getvalue(), "audio/wav")),
        ])
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["status"] == "complete", job.get("error") or job
        assert [scene["status"] for scene in job["scene_progress"]] == ["complete", "complete"]
        assert calls == [("A little robot waves Camera motion guidance: slow camera push-in.", 16)]
        video = client.get(job["video_url"])
        assert video.status_code == 200
        assert video.headers["content-type"] == "video/mp4"
        assert video.content[:8].endswith(b"ftyp")
        details = subprocess.run([ffmpeg_binary(), "-hide_banner", "-i", str(main.OUTPUT / f"{job_id}.mp4")], capture_output=True, text=True)
        assert "540x960" in details.stderr and "12 fps" in details.stderr, details.stderr
        assert "Audio:" in details.stderr, details.stderr
        (main.OUTPUT / f"{job_id}.mp4").unlink(missing_ok=True)


def test_project_validation_and_comfy_settings(tmp_path, monkeypatch):
    import json
    from app import main
    project = {"scenes": [{"id": "too-short", "engine": "wan", "prompt": "Test", "duration": 2}]}
    monkeypatch.setattr(main, "COMFYUI_URL", main.COMFYUI_URL)
    monkeypatch.setattr(main, "COMFYUI_TIMEOUT_SECONDS", main.COMFYUI_TIMEOUT_SECONDS)
    with TestClient(app) as client:
        invalid = client.post("/api/render", data={"project": json.dumps(project)})
        assert invalid.status_code == 422
        unsafe = {"scenes": [{"id": "../outside", "engine": "local", "duration": 3}]}
        assert client.post("/api/render", data={"project": json.dumps(unsafe)}).status_code == 422

        env_path = tmp_path / ".env"
        env_path.write_text("# keep this comment\nOTHER_SETTING=unchanged\nCOMFYUI_URL=http://old:8188\n", encoding="utf-8")
        monkeypatch.setattr(main, "ENV_PATH", env_path)
        settings = client.post("/api/settings", json={"url": "http://192.168.1.8:8188", "timeout_seconds": 1800})
        assert settings.status_code == 200
        saved = env_path.read_text(encoding="utf-8")
        assert "# keep this comment" in saved and "OTHER_SETTING=unchanged" in saved
        assert "COMFYUI_URL=http://192.168.1.8:8188" in saved
        assert "COMFYUI_TIMEOUT_SECONDS=1800" in saved
        assert client.post("/api/settings", json={"url": "file:///tmp/x"}).status_code == 422


def test_scene_failure_is_reported(monkeypatch):
    import json
    from app import main
    monkeypatch.setattr(main, "generate_wan", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("mock ComfyUI failure")))
    project = {"scenes": [{"id": "wan-failure", "engine": "wan", "prompt": "A scene", "duration": 3}]}
    with TestClient(app) as client:
        response = client.post("/api/render", data={"project": json.dumps(project)})
        assert response.status_code == 202
        job = client.get(f"/api/jobs/{response.json()['id']}").json()
        assert job["status"] == "error"
        assert job["scene_progress"][0]["status"] == "error"
        assert "mock ComfyUI failure" in job["scene_progress"][0]["error"]
