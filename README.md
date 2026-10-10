# ✦ AI Video Studio (FrameForge) — Free-first MVP

A local-first video-making web app for Windows, built with **Python + FastAPI + FFmpeg** and an optional **Wan 2.2 / ComfyUI GPU connector**. No paid API key is required. A real GPU is still needed for generative AI video.

## What works

- ✅ **Local Motion**: Upload PNG/JPG/WEBP and render an MP4 with zoom-in, zoom-out, left or right pan; portrait 9:16 and landscape 16:9; 3–12 seconds; optional MP3/WAV/M4A soundtrack.
- ✅ **Text-card mode**: If no image is uploaded, your prompt is rendered as a moving title card. **This is not an AI-generated scene.**
- ✅ **Wan 2.2 / ComfyUI**: Submit text-to-video or image-to-video jobs to **your own configured ComfyUI GPU server**, poll progress, retrieve video and download it.
- ✅ Local web UI, background jobs, upload limits, inline preview and MP4 download.

### Not part of version 1

Automatic image generation, speech generation, full 12-second AI-generated scenes, multi-clip timelines, persisted jobs, account system, GPU provisioning or unlimited cloud inference. Wan videos are 3–6 seconds with 16fps settings; frames may require substantial GPU time.

## Installation on Windows

1. Install **Python 3.11 or newer** from https://www.python.org/downloads/ (enable **Add Python to PATH**).
2. Extract the ZIP into your GitHub projects directory (for example `C:\Users\bilal\github\AI-Video-Studio`).
3. Double-click **`setup.bat`**. This installs Python packages in an isolated `.venv`, including a bundled FFmpeg binary (no separate FFmpeg download normally needed).
4. Double-click **`start.bat`**.
5. Open **http://127.0.0.1:8000**.
6. Choose **Local Motion**, upload an image, select a motion and duration, then click **Generate video**. Download the result as MP4.

PowerShell alternative:

```powershell
cd "$HOME\github\AI-Video-Studio"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If `python` isn't available, install Python first. Windows antivirus/Windows SmartScreen may ask for confirmation when running locally-created batch files.

## Connect Wan 2.2 when a GPU is available

This project **does not include a free cloud GPU**. Your existing ASUS integrated Radeon laptop graphics are not an appropriate target for running Wan 2.2 at reasonable speeds. Free cloud GPU services may be unavailable, restricted or have short quotas. A compatible ComfyUI server running on another GPU computer is the intended target.

1. On a GPU machine, install an up-to-date **ComfyUI**: https://github.com/Comfy-Org/ComfyUI
2. In ComfyUI, load **Workflow → Browse Templates → Video → Wan 2.2 5B video generation** (or consult https://docs.comfy.org/tutorials/video/wan/wan2_2 ). Ensure `CreateVideo` and `SaveVideo` nodes are available.
3. Install the three model files referenced in the official tutorial:

   - `ComfyUI/models/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors`
   - `ComfyUI/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors`
   - `ComfyUI/models/vae/wan2.2_vae.safetensors`

4. In `AI-Video-Studio/.env`, set `COMFYUI_URL=http://127.0.0.1:8188` for a same-PC ComfyUI or **the GPU machine's reachable address**. Only use an endpoint you trust. Do not expose an unauthenticated ComfyUI port to the public Internet.
5. Restart `start.bat`, choose **Wan 2.2 AI**, enter a prompt, optionally upload a reference image and generate.

`workflows/wan22_5b_api.json` is a small **API-format** workflow based on the official ComfyUI 5B graph. It uses 448×800 portrait or 800×448 landscape (approximately 9:16/16:9; both divisible by 32), 16fps, a 20-step sampler, and SaveVideo (MP4 H.264). Actual success depends on ComfyUI version, required nodes, model files, available GPU memory and permissions; the supplied model workflow **has not been executed on a real GPU as part of this delivery**.

If your ComfyUI's node options differ, export your working workflow **in API format** and adjust `workflows/wan22_5b_api.json`. The code expects node IDs `6` (positive prompt), `3` (seed), `55` (latent dimensions and optional start image), `56` (uploaded reference image), and `58` (SaveVideo). Visual ComfyUI workflow exports are **not** API-format workflows.

**Remote-host notes:** Many free notebooks prohibit or block server port exposure. A remotely hosted ComfyUI server must be reachable from your computer; the app does not include a tunneling or proxy service. A GPU service may charge you even though this app is free.

## Folder structure

```text
AI-Video-Studio/
├── app/
│   ├── __init__.py
│   ├── main.py                 FastAPI API, job queue, file handling
│   ├── animation.py            CPU-only FFmpeg animations
│   └── comfy.py                Wan 2.2 / ComfyUI adapter
├── web/
│   ├── index.html              Responsive creator UI
│   ├── styles.css              Dark interface
│   └── app.js                  Upload, progress, video preview
├── workflows/
│   └── wan22_5b_api.json       ComfyUI API workflow
├── tests/
│   └── test_smoke.py           FastAPI + render tests
├── outputs/                     Finished MP4 clips (not committed)
├── uploads/                     Temporary media (cleared after each job)
├── .env.example
├── requirements.txt
├── setup.bat
└── start.bat
```

## Programmatic API

- `GET /api/health` — check service and ComfyUI connectivity
- `POST /api/generate` — `multipart/form-data`: `mode` local/wan, `prompt`, `orientation`, `duration`, `motion`, optional `image` and `audio` (audio only for local)
- `GET /api/jobs/{job_id}` — queued/running/complete/error and progress message
- `GET /api/videos/{job_id}` — stream/download finished MP4

Run tests (install `pytest`):

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

## Practical usage / privacy

- Run only on `127.0.0.1` for your own computer. This MVP has no logins or rate limiting and is not production-secure for Internet-facing hosting.
- Images/music uploaded in local mode are processed on your own computer; reference images/prompts for Wan are transmitted to the configured ComfyUI host.
- Rendering uses CPU and may be slow on laptops. Do not close `start.bat` during a render.
- Saved outputs live under `outputs/` and can be manually deleted; job statuses live in memory and reset on server restart.
- You are responsible for rights to uploaded images and music, and for any costs of GPU services you choose.

## Next releases

V2: Storyboard of multiple clips, smooth transitions and custom sound library. V3: image-generation plugin, voiceover/TTS, subtitles and reusable templates. V4: optional user accounts and persistent jobs if needed.
