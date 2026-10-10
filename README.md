# AI Video Studio (FrameForge)

A local-first YouTube Shorts creator built with Python, FastAPI, Pillow, and FFmpeg. Make scenes with local still-image animation, optionally mix in Wan 2.2 scenes from your own ComfyUI server, and render the storyboard to one MP4. No paid API is required.

## Features

- Create, edit, reorder, duplicate, and delete scenes in the storyboard.
- Choose Local Motion or Wan 2.2 separately for each scene.
- Add a prompt, an optional PNG/JPG/WEBP reference image, duration, camera motion, and optional text overlay to each scene.
- Animate local images with zoom-in, zoom-out, pan-left, or pan-right. A local scene without an image becomes a moving text card; it is not AI image generation.
- Set portrait 9:16 or landscape 16:9 output, 540p/720p/1080p resolution, and 12–60 FPS. Wan source clips are rendered through ComfyUI and then normalized to the selected project output settings.
- Add an optional MP3/WAV/M4A soundtrack to the finished video.
- Follow progress and errors per scene, preview the final video, and download its MP4.
- Configure the ComfyUI URL and job timeout in the editor or in `.env`.

### Limits

- Up to 20 scenes and 60 seconds per project.
- Local scenes: 1–12 seconds. Wan scenes: 3–6 seconds.
- Reference images: 12 MB each; soundtrack: 16 MB; combined project uploads: 64 MB.
- Prompt: 1,800 characters per scene. Overlay: 180 characters per scene.
- Wan output files downloaded from ComfyUI are limited to 250 MB.

Jobs and progress are kept in memory and reset when the server restarts. Finished MP4 files are kept in `outputs/`. Temporary project uploads are removed after each render.

## Windows setup

1. Install Python 3.11 or later from [python.org](https://www.python.org/downloads/) and enable **Add Python to PATH**.
2. Open this project folder in File Explorer.
3. Double-click `setup.bat`. It creates `.venv`, installs the Python packages, and creates `.env` from `.env.example` if needed. `imageio-ffmpeg` supplies the FFmpeg executable used by the app, so a separate FFmpeg install is not normally needed.
4. Double-click `start.bat`.
5. Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The server binds to `127.0.0.1` by default. Keep it local; this app does not have user accounts or authentication.

### PowerShell setup

```powershell
cd "$HOME\github\AI-Video-Studio"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If `py` is not available, install Python first or use `python` in its place. Do not run Uvicorn with `--host 0.0.0.0` on an untrusted network.

## FFmpeg

The normal setup uses the FFmpeg binary packaged by the `imageio-ffmpeg` Python dependency. The app falls back to `ffmpeg.exe` on `PATH` if that packaged binary is unavailable.

To install a separate Windows FFmpeg build, use the Windows executable links on [FFmpeg's download page](https://www.ffmpeg.org/download.html) (currently linked builds include Gyan.dev and BtbN). Add the folder containing `ffmpeg.exe` to your user `PATH`, open a new terminal, and check:

```powershell
ffmpeg -version
```

Restart the app after changing `PATH`. The project uses CPU encoding with H.264; render time depends on image size, FPS, scene count, and your computer.

## Configure ComfyUI and Wan 2.2

Wan generation runs on a ComfyUI server that you provide. This application does not host a GPU, download model weights, or verify GPU inference. A successful health check only confirms that the server responds and the local API workflow passes structural validation.

1. Install/update ComfyUI on the computer with your compatible GPU. Follow the current [official Wan 2.2 ComfyUI guide](https://docs.comfy.org/tutorials/video/wan/wan2_2).
2. Manually download the Wan 2.2 TI2V 5B model files referenced by the official guide. The supplied workflow expects:
   - `ComfyUI/models/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors`
   - `ComfyUI/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors`
   - `ComfyUI/models/vae/wan2.2_vae.safetensors`
3. Start ComfyUI and make sure its server is reachable from this PC (the default ComfyUI port is `8188`). For a same-PC setup, use `http://127.0.0.1:8188`. For another machine, use its reachable LAN address and port.
4. In AI Video Studio, enter the address under **ComfyUI connection**, select a timeout, click **Save settings**, then click **Test connection**. Settings are stored in the ignored local `.env` file. You can also edit:

   ```ini
   COMFYUI_URL=http://127.0.0.1:8188
   COMFYUI_TIMEOUT_SECONDS=2400
   ```

5. Use the included `workflows/wan22_5b_api.json`. It is an API-format graph with the node IDs expected by this app. The app checks for required nodes before submission and polls the ComfyUI history endpoint until completion or timeout.

The bundled workflow creates a 16 FPS source clip at its model dimensions. The final MP4 is resized/cropped to the storyboard's selected resolution, aspect ratio, and FPS. Wan scenes are limited to 3–6 seconds because that is the range configured for this workflow. A camera motion setting is sent as prompt guidance; the model may interpret it differently.

ComfyUI's official guide says the TI2V 5B workflow should fit well on 8 GB VRAM with ComfyUI native offloading, but actual performance and compatibility vary by GPU, drivers, ComfyUI version, and model setup. **This project's Wan inference has not been tested on a real GPU.**

Do not expose an unauthenticated ComfyUI port to the public Internet. If you use a separate GPU host, only connect to a host you trust; Wan prompts and reference images are sent to that configured server.

## Troubleshooting

### `FFmpeg not found`

- Run `setup.bat` again to install the Python dependencies.
- In PowerShell, run `where.exe ffmpeg` and `ffmpeg -version` if you installed a system copy.
- If the app still cannot locate FFmpeg, install a Windows build as described above, add its `bin` folder to `PATH`, then restart the server.

### ComfyUI is not detected

- Start ComfyUI and confirm its address in a browser on the same PC before testing it here.
- Check the URL and port in the editor. The default is `http://127.0.0.1:8188`.
- For another computer, check that both devices can reach each other and that the GPU host firewall allows the ComfyUI port on the trusted LAN.
- Health checks do not run a workflow and do not confirm that a GPU is available.

### Workflow validation or node errors

- Update ComfyUI. The official Wan guide notes that missing nodes can mean that ComfyUI is out of date or failed to load nodes.
- Confirm that the required model files are in the folders above and that the ComfyUI console has no model-loading errors.
- If you replace `workflows/wan22_5b_api.json`, use an API-format workflow and preserve the required node IDs/types (`3` KSampler, `6` CLIPTextEncode, `55` Wan22ImageToVideoLatent, `57` CreateVideo, `58` SaveVideo). The app's workflow validator reports missing required nodes.
- Read the ComfyUI console for the detailed node error after a failed job.

### Wan rendering times out or returns no video

- Increase **Job timeout** in the editor and save it.
- Check ComfyUI's queue/history and server logs. Model loading or generation can take a long time.
- Confirm that the workflow contains a SaveVideo node that writes an MP4. The app downloads the resulting video through ComfyUI's `/view` endpoint.
- A health check that succeeds is not evidence that inference works. This project has not verified GPU inference end to end.

### Upload rejected or render fails locally

- Check the per-scene error and keep images/audio within the stated file limits.
- Use a readable PNG, JPG, WEBP, MP3, WAV, or M4A file. The app checks image contents before saving them.
- High resolutions, 60 FPS, long projects, and many scenes use more CPU time and disk space. Try 540p or fewer scenes if local rendering is slow.
- Ensure the project has enough free disk space for temporary clips and the finished MP4.

## API

- `GET /api/health` — local service status, ComfyUI reachability, workflow validity, and `inference_tested: false`.
- `GET /api/settings` and `POST /api/settings` — read or save the ComfyUI URL and timeout.
- `POST /api/render` — multipart form with `project` (JSON string), repeated `reference_images` files, and optional `music` file. Each scene has `id`, `engine` (`local`/`wan`), `prompt`, `duration`, `motion`, `overlay`, and optional `image_index`.
- `POST /api/generate` — compatible single-scene MVP endpoint (`mode`, `prompt`, `orientation`, `duration`, `motion`, optional `image` and `audio`).
- `GET /api/jobs/{job_id}` — overall status and per-scene progress/error data.
- `GET /api/videos/{job_id}` — stream/download the completed MP4.

## Tests

Install pytest into the project venv (it is a development-only dependency), then run the suite:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

The suite includes CPU FFmpeg renders and a mocked ComfyUI adapter. Mocked Wan tests do not test a real ComfyUI server or GPU inference.

## Project layout

```text
app/main.py                 FastAPI endpoints, settings, uploads, and render jobs
app/animation.py            Pillow cards and FFmpeg scene/video processing
app/comfy.py                ComfyUI Wan 2.2 workflow, polling, and retrieval
web/index.html              Storyboard editor and output preview
web/app.js                  Scene controls, upload handling, progress, and settings
web/styles.css              Responsive editor styles
workflows/wan22_5b_api.json ComfyUI API-format workflow
tests/test_smoke.py         API, CPU rendering, validation, and mocked adapter tests
outputs/                    Finished MP4s (not committed)
uploads/                    Temporary render files (not committed)
```
