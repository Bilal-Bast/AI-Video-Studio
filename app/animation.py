"""CPU-only still-image animation powered by bundled FFmpeg."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageOps

SIZE = {"portrait": (540, 960), "landscape": (960, 540)}
FPS = 20


def ffmpeg_binary() -> str:
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        executable = shutil.which("ffmpeg")
        if executable:
            return executable
        raise RuntimeError("FFmpeg not found. Run setup.bat to install dependencies.")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for filename in [
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(filename, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _lines(draw: ImageDraw.ImageDraw, message: str, font, max_width: int) -> list[str]:
    words = message.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:7]


def text_poster(prompt: str, path: Path, orientation: str) -> None:
    """Produces a typographic card, not an AI-generated photographic image."""
    width, height = SIZE[orientation]
    img = Image.new("RGB", (width, height))
    pixels = img.load()
    for y in range(height):
        a = y / max(1, height - 1)
        for x in range(width):
            b = x / max(1, width - 1)
            pixels[x, y] = (int(11 + 35 * b), int(14 + 16 * a), int(35 + 48 * (1 - a)))
    draw = ImageDraw.Draw(img)
    cx, cy = width // 2, height // 2
    draw.ellipse((cx - 90, cy - 200, cx + 240, cy + 130), outline=(102, 83, 204), width=3)
    draw.ellipse((cx - 200, cy - 320, cx + 100, cy - 20), outline=(48, 151, 192), width=2)
    title = (prompt or "YOUR STORY STARTS HERE").strip()[:180]
    font = _font(max(26, round(width / 14)))
    lines = _lines(draw, title, font, int(width * .78))
    spacing = round(width / 34)
    boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    total = sum(b[3] - b[1] for b in boxes) + spacing * max(0, len(lines) - 1)
    top = round((height - total) / 2)
    for line, rect in zip(lines, boxes):
        line_h = rect[3] - rect[1]
        draw.text((cx, top), line, font=font, fill=(255, 255, 255), anchor="mt", stroke_width=1)
        top += line_h + spacing
    label_font = _font(max(15, width // 38))
    draw.text((width // 2, height - 66), "AI VIDEO STUDIO  /  LOCAL MOTION", font=label_font, fill=(156, 177, 215), anchor="mm")
    img.save(path, "JPEG", quality=92)


def normalize_image(input_image: Path, output: Path, orientation: str) -> None:
    width, height = SIZE[orientation]
    # Input images only need the exact target size: zoompan dynamically crops within the image.
    with Image.open(input_image) as source:
        image = ImageOps.fit(ImageOps.exif_transpose(source.convert("RGB")), (width, height), method=Image.Resampling.LANCZOS)
        image.save(output, "JPEG", quality=92)


def animate(image: Path, video: Path, duration: int, orientation: str, motion: str, audio: Path | None = None) -> None:
    if orientation not in SIZE or motion not in {"zoom_in", "zoom_out", "pan_left", "pan_right"}:
        raise ValueError("Unsupported orientation or motion")
    if not 3 <= duration <= 12:
        raise ValueError("Duration must be 3–12 seconds")
    width, height = SIZE[orientation]
    frames = FPS * duration
    if motion == "zoom_in":
        zoom, x, y = "min(1.16,1+on*0.0014)", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"
    elif motion == "zoom_out":
        zoom, x, y = "max(1.0,1.16-on*0.0014)", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"
    elif motion == "pan_left":
        zoom, x, y = "1.14", f"(iw-iw/zoom)*(1-on/{frames})", "ih/2-ih/zoom/2"
    else:
        zoom, x, y = "1.14", f"(iw-iw/zoom)*on/{frames}", "ih/2-ih/zoom/2"
    vf = (
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={FPS},"
        f"fade=t=in:st=0:d=0.20,fade=t=out:st={duration - .25}:d=0.25,format=yuv420p"
    )
    command = [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(image)]
    if audio:
        command += ["-stream_loop", "-1", "-i", str(audio)]
    command += ["-vf", vf, "-frames:v", str(frames), "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p"]
    if audio:
        command += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "128k", "-af", f"afade=t=out:st={max(0, duration-.5)}:d=.5", "-shortest"]
    command += ["-movflags", "+faststart", "-t", str(duration), str(video)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode or not video.is_file() or video.stat().st_size < 500:
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-1200:]}")
