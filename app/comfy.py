"""Run Wan 2.2 on a separately running ComfyUI instance (not a hosted free GPU)."""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

WORKFLOW = Path(__file__).resolve().parent.parent / "workflows" / "wan22_5b_api.json"
MAX_VIDEO_BYTES = 250 * 1024 * 1024
REQUIRED_NODES = {
    "3": "KSampler",
    "6": "CLIPTextEncode",
    "55": "Wan22ImageToVideoLatent",
    "57": "CreateVideo",
    "58": "SaveVideo",
}


def validate_server_url(base_url: str) -> str:
    url = urlparse(base_url)
    try:
        valid_port = url.port is None or 1 <= url.port <= 65535
    except ValueError:
        valid_port = False
    if (url.scheme not in ("http", "https") or not url.hostname or not valid_port
            or url.username or url.password or url.query or url.fragment):
        raise ValueError("COMFYUI_URL must be a valid http(s) URL")
    return base_url.rstrip("/")


def validate_workflow(workflow: dict | None = None) -> dict:
    """Load and check the API-format workflow before sending it to ComfyUI."""
    if workflow is None:
        try:
            workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Wan workflow could not be read: {exc}") from exc
    if not isinstance(workflow, dict):
        raise ValueError("Wan workflow must be an API-format node object")
    for node_id, class_type in REQUIRED_NODES.items():
        node = workflow.get(node_id)
        if not isinstance(node, dict) or node.get("class_type") != class_type:
            raise ValueError(f"Wan workflow is missing required node {node_id} ({class_type})")
        if not isinstance(node.get("inputs"), dict):
            raise ValueError(f"Wan workflow node {node_id} has no inputs object")

    def check_links(value) -> None:
        if isinstance(value, list):
            if len(value) == 2 and isinstance(value[0], str) and value[0].isdigit():
                if value[0] not in workflow or not isinstance(value[1], int):
                    raise ValueError(f"Wan workflow contains an invalid node link: {value}")
                return
            for child in value:
                check_links(child)
        elif isinstance(value, dict):
            for child in value.values():
                check_links(child)

    check_links(workflow)
    return workflow


def check_connection(base_url: str) -> bool:
    try:
        with httpx.Client(timeout=4.0, follow_redirects=False) as client:
            response = client.get(f"{validate_server_url(base_url)}/system_stats")
            return response.is_success
    except (httpx.HTTPError, ValueError):
        return False


def make_workflow(prompt: str, orientation: str, duration: int, filename: str | None = None,
                  fps: int = 16) -> dict:
    if orientation not in ("portrait", "landscape") or not 3 <= duration <= 6:
        raise ValueError("Wan scenes support portrait/landscape and 3–6 seconds")
    if not 12 <= fps <= 60:
        raise ValueError("Wan output FPS must be between 12 and 60")
    workflow = validate_workflow()
    workflow["6"]["inputs"]["text"] = prompt
    workflow["3"]["inputs"]["seed"] = secrets.randbelow(2**50)
    width, height = (448, 800) if orientation == "portrait" else (800, 448)
    workflow["55"]["inputs"].update(width=width, height=height, length=fps * duration + 1)
    workflow["57"]["inputs"]["fps"] = fps
    if filename:
        workflow["56"] = {"class_type": "LoadImage", "inputs": {"image": filename}}
        workflow["55"]["inputs"]["start_image"] = ["56", 0]
    return workflow


def _find_video(history: dict) -> dict:
    for output in history.get("outputs", {}).values():
        for kind in ("videos", "gifs", "files", "images"):
            for item in output.get(kind, []):
                filename = item.get("filename", "")
                if Path(filename).suffix.lower() in (".mp4", ".webm", ".mov", ".mkv"):
                    return item
    raise RuntimeError("ComfyUI finished, but no video output was found. Check the SaveVideo node.")


def generate(
    base_url: str, prompt: str, orientation: str, duration: int,
    output_path: Path, image_path: Path | None = None,
    on_progress=None, poll_interval: float = 3, max_wait_seconds: int = 2400,
    fps: int = 16,
) -> None:
    base = validate_server_url(base_url)
    validate_workflow()
    with httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=False) as client:
        try:
            client.get(f"{base}/system_stats").raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Cannot reach ComfyUI at {base}. Start ComfyUI and verify the configured server URL.") from exc
        uploaded_filename = None
        if image_path:
            if on_progress: on_progress("Uploading reference image to ComfyUI")
            with image_path.open("rb") as image:
                upload = client.post(f"{base}/upload/image", files={"image": (image_path.name, image, "image/jpeg")}, data={"overwrite": "false"})
            upload.raise_for_status()
            uploaded_filename = upload.json()["name"]
        workflow = make_workflow(prompt, orientation, duration, uploaded_filename, fps=fps)
        if on_progress: on_progress("Submitting Wan 2.2 generation")
        response = client.post(f"{base}/prompt", json={"prompt": workflow})
        response.raise_for_status()
        payload = response.json()
        if "error" in payload or "prompt_id" not in payload:
            raise RuntimeError(f"ComfyUI rejected the workflow: {str(payload)[:700]}")
        prompt_id = payload["prompt_id"]
        if on_progress: on_progress(f"Wan 2.2 job running in ComfyUI (job {prompt_id[:8]})")
        deadline = time.monotonic() + max_wait_seconds
        while time.monotonic() < deadline:
            history_response = client.get(f"{base}/history/{prompt_id}")
            history_response.raise_for_status()
            info = history_response.json().get(prompt_id)
            if info:
                status = info.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError("ComfyUI generation failed. See the GPU server console for node errors.")
                if status.get("completed") or status.get("status_str") == "success":
                    item = _find_video(info)
                    if on_progress: on_progress("Downloading AI-generated video")
                    with client.stream("GET", f"{base}/view", params={
                        "filename": item["filename"],
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    }) as downloaded:
                        downloaded.raise_for_status()
                        byte_count = 0
                        with output_path.open("wb") as out:
                            for chunk in downloaded.iter_bytes(1024 * 1024):
                                byte_count += len(chunk)
                                if byte_count > MAX_VIDEO_BYTES:
                                    raise RuntimeError("Generated video exceeds the 250 MB download limit")
                                out.write(chunk)
                    if byte_count < 100:
                        raise RuntimeError("ComfyUI returned an empty video")
                    return
            time.sleep(poll_interval)
        raise TimeoutError(f"Wan job exceeded its configured timeout ({max_wait_seconds} seconds). Check ComfyUI history for its state.")
