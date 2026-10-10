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
            current = ""
            for character in word:
                candidate = current + character
                if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
                    lines.append(current)
                    current = character
                else:
                    current = candidate
    if current:
        lines.append(current)
    return lines[:7]


def render_size(orientation: str, resolution: int) -> tuple[int, int]:
    if orientation not in SIZE or resolution not in {540, 720, 1080}:
        raise ValueError("Unsupported orientation or resolution")
    if orientation == "portrait":
        return (540, 960) if resolution == 540 else (resolution, round(resolution * 16 / 9))
    return (round(resolution * 16 / 9), resolution)


def text_poster(prompt: str, path: Path, orientation: str, size: tuple[int, int] | None = None) -> None:
    """Produces a typographic card, not an AI-generated photographic image."""
    width, height = size or SIZE[orientation]
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


def normalize_image(input_image: Path, output: Path, orientation: str,
                    size: tuple[int, int] | None = None) -> None:
    width, height = size or SIZE[orientation]
    # Input images only need the exact target size: zoompan dynamically crops within the image.
    with Image.open(input_image) as source:
        image = ImageOps.fit(ImageOps.exif_transpose(source.convert("RGB")), (width, height), method=Image.Resampling.LANCZOS)
        image.save(output, "JPEG", quality=92)


def _overlay_image(text: str, path: Path, width: int, height: int) -> None:
    """Create a transparent, safely rendered text overlay without FFmpeg escaping."""
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font_size = max(16, width // 20)
    min_font_size = max(12, width // 42)
    font = _font(font_size)
    lines = _lines(draw, text.strip()[:180], font, int(width * .84))
    while len(lines) > 4 and font_size > min_font_size:
        font_size -= 1
        font = _font(font_size)
        lines = _lines(draw, text.strip()[:180], font, int(width * .84))
    lines = lines[:4]
    if not lines:
        return
    spacing = max(4, width // 80)
    boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_heights = [box[3] - box[1] for box in boxes]
    text_height = sum(line_heights) + spacing * (len(lines) - 1)
    pad_x, pad_y = width // 28, height // 90
    center_y = round(height * .79)
    top = center_y - text_height // 2
    widest = max(draw.textbbox((0, 0), line, font=font)[2] for line in lines)
    box = (width // 2 - widest // 2 - pad_x, top - pad_y,
           width // 2 + widest // 2 + pad_x, top + text_height + pad_y)
    draw.rounded_rectangle(box, radius=max(8, width // 60), fill=(0, 0, 0, 155))
    y = top
    for line, line_height in zip(lines, line_heights):
        draw.text((width // 2, y + line_height // 2), line, font=font,
                  fill=(255, 255, 255, 255), anchor="mm", stroke_width=1,
                  stroke_fill=(0, 0, 0, 180))
        y += line_height + spacing
    layer.save(path, "PNG")


def animate(image: Path, video: Path, duration: int, orientation: str, motion: str,
            audio: Path | None = None, *, size: tuple[int, int] | None = None,
            fps: int = FPS, overlay_text: str = "") -> None:
    if orientation not in SIZE or motion not in {"zoom_in", "zoom_out", "pan_left", "pan_right"}:
        raise ValueError("Unsupported orientation or motion")
    if not 1 <= duration <= 12:
        raise ValueError("Duration must be 1–12 seconds")
    width, height = size or SIZE[orientation]
    if not 12 <= fps <= 60 or width % 2 or height % 2:
        raise ValueError("FPS must be 12–60 and output dimensions must be even")
    frames = fps * duration
    if motion == "zoom_in":
        zoom, x, y = "min(1.16,1+on*0.0014)", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"
    elif motion == "zoom_out":
        zoom, x, y = "max(1.0,1.16-on*0.0014)", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"
    elif motion == "pan_left":
        zoom, x, y = "1.14", f"(iw-iw/zoom)*(1-on/{frames})", "ih/2-ih/zoom/2"
    else:
        zoom, x, y = "1.14", f"(iw-iw/zoom)*on/{frames}", "ih/2-ih/zoom/2"
    vf = (
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
        f"fade=t=in:st=0:d=0.20,fade=t=out:st={duration - .25}:d=0.25,format=yuv420p"
    )
    command = [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(image)]
    overlay_path = video.with_name(f"{video.stem}-overlay.png")
    use_overlay = bool(overlay_text.strip())
    if use_overlay:
        _overlay_image(overlay_text, overlay_path, width, height)
        command += ["-loop", "1", "-i", str(overlay_path)]
    audio_index = 2 if use_overlay else 1
    if audio:
        command += ["-stream_loop", "-1", "-i", str(audio)]
    if use_overlay:
        command += ["-filter_complex", f"[0:v]{vf}[base];[base][1:v]overlay=0:0:shortest=1:format=auto,format=yuv420p[v]", "-map", "[v]"]
    else:
        command += ["-vf", vf]
    command += ["-frames:v", str(frames), "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p"]
    if audio:
        if not use_overlay:
            command += ["-map", "0:v:0"]
        command += ["-map", f"{audio_index}:a:0", "-c:a", "aac", "-b:a", "128k", "-af", f"afade=t=out:st={max(0, duration-.5)}:d=0.5", "-shortest"]
    command += ["-movflags", "+faststart", "-t", str(duration), str(video)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    finally:
        overlay_path.unlink(missing_ok=True)
    if result.returncode or not video.is_file() or video.stat().st_size < 500:
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-1200:]}")


def transcode_scene(source: Path, video: Path, duration: int, orientation: str,
                    resolution: int, fps: int, overlay_text: str = "") -> None:
    """Normalize an AI-generated clip to the project canvas and frame rate."""
    width, height = render_size(orientation, resolution)
    if not 12 <= fps <= 60:
        raise ValueError("FPS must be between 12 and 60")
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
          f"crop={width}:{height},fps={fps},trim=duration={duration},"
          "setpts=PTS-STARTPTS,format=yuv420p")
    command = [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(source)]
    overlay_path = video.with_name(f"{video.stem}-overlay.png")
    use_overlay = bool(overlay_text.strip())
    if use_overlay:
        _overlay_image(overlay_text, overlay_path, width, height)
        command += ["-loop", "1", "-i", str(overlay_path)]
        command += ["-filter_complex", f"[0:v]{vf}[base];[base][1:v]overlay=0:0:shortest=1:format=auto,format=yuv420p[v]", "-map", "[v]"]
    else:
        command += ["-vf", vf]
    command += ["-an", "-t", str(duration), "-r", str(fps), "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(video)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    finally:
        overlay_path.unlink(missing_ok=True)
    if result.returncode or not video.is_file() or video.stat().st_size < 500:
        raise RuntimeError(f"FFmpeg could not normalize a scene: {result.stderr[-1200:]}")


def concat_scenes(scenes: list[Path], concat_file: Path, video: Path, fps: int) -> None:
    """Join normalized scenes in order, re-encoding for reliable Windows playback."""
    def quote(path: Path) -> str:
        return path.resolve().as_posix().replace("'", "'\\''")
    concat_file.write_text("".join(f"file '{quote(scene)}'\n" for scene in scenes), encoding="utf-8")
    command = [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "concat", "-safe", "0", "-i", str(concat_file),
               "-an", "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1200)
    if result.returncode or not video.is_file() or video.stat().st_size < 500:
        raise RuntimeError(f"FFmpeg could not combine scenes: {result.stderr[-1200:]}")


def add_audio_track(video: Path, audio: Path, output: Path, duration: int) -> None:
    command = [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
               "-stream_loop", "-1", "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
               "-t", str(duration), "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
               "-af", f"afade=t=out:st={max(0, duration - .5)}:d=0.5", "-shortest",
               "-movflags", "+faststart", str(output)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode or not output.is_file() or output.stat().st_size < 500:
        raise RuntimeError(f"FFmpeg could not add the soundtrack: {result.stderr[-1200:]}")
