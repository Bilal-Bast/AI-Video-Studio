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
    from PIL import Image
    from app.main import OUTPUT
    image = Image.new("RGB", (240, 400), (90, 50, 165))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    with TestClient(app) as client:
        response = client.post(
            "/api/generate",
            data={"mode": "local", "prompt": "Demo", "orientation": "landscape", "duration": "3", "motion": "pan_left"},
            files={"image": ("demo.png", buffer.getvalue(), "image/png")},
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
