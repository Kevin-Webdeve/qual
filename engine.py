"""Local FFmpeg video enhancement. No network or user media uploads."""
from __future__ import annotations

import io
import math
import os
import queue
import re
import subprocess
import threading
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageStat


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    duration: float
    fps: float
    audio: bool
    hdr: bool = False
    codec: str = "unknown"
    color_space: str = ""
    color_transfer: str = ""
    color_primaries: str = ""
    color_range: str = "tv"
    interlaced: bool = False
    sample_aspect: float = 1.0
    audio_stream_index: int | None = None
    audio_layout: str = ""


@dataclass(frozen=True)
class Settings:
    resolution: str = "1080 × 1920"
    framing: str = "Fit with black bars"
    fps: str = "Keep source"
    quality: str = "High quality"
    sharpen: float = 0.35
    denoise: float = 0.8
    contrast: float = 1.02
    saturation: float = 1.03
    brightness: float = 0.0
    gamma: float = 1.0
    sharpening: str = "Adaptive"
    deband: bool = False
    speed: str = "Slow / better compression"
    motion: str = "Preserve source motion"
    crop_x: float = 0.5
    crop_y: float = 0.5
    mobile_compatible: bool = False
    mobile_resolution: str = "Keep original size"


RESOLUTIONS = {"720 × 1280": (720, 1280), "1080 × 1920": (1080, 1920), "2160 × 3840 (4K)": (2160, 3840)}
QUALITIES = {"Maximum detail": 16, "High quality": 18, "Smaller file": 22}
SPEEDS = {"Slow / better compression": "slow", "Balanced speed": "medium", "Fast preview / export": "fast"}
MOTION_MODES = ("Preserve source motion", "Smooth to 60 fps (slow)")
MOBILE_RESOLUTIONS = ("Keep original size", "Limit to 1080p")
MOBILE_FRAME_RATES = ("Keep source (normal speed)", "Automatic (30/60 fps)", "30 fps", "60 fps")


PRESETS = {
    "Balanced": dict(sharpen=0.35, denoise=0.8, contrast=1.02, saturation=1.03, brightness=0.0, gamma=1.0),
    "Crisp edits": dict(sharpen=0.65, denoise=0.4, contrast=1.04, saturation=1.06, brightness=0.0, gamma=1.0),
    "Low light": dict(sharpen=0.2, denoise=2.0, contrast=1.0, saturation=1.02, brightness=0.015, gamma=1.08),
    "Natural": dict(sharpen=0.15, denoise=0.0, contrast=1.0, saturation=1.0, brightness=0.0, gamma=1.0),
    "Animation / gaming": dict(sharpen=0.4, denoise=0.0, contrast=1.02, saturation=1.04, brightness=0.0, gamma=1.0),
}


def validate_settings(settings: Settings) -> None:
    choices = {"resolution": (*RESOLUTIONS, "Original size"), "framing": ("Fit with black bars", "Center crop"),
               "fps": ("Keep source", "30 fps", "60 fps"), "quality": QUALITIES,
               "speed": SPEEDS, "motion": MOTION_MODES, "sharpening": ("Adaptive", "Classic"),
               "mobile_resolution": MOBILE_RESOLUTIONS}
    for name, allowed in choices.items():
        if getattr(settings, name) not in allowed:
            raise ValueError(f"Unsupported {name}: {getattr(settings, name)}")
    limits = {"sharpen": (0, 1), "denoise": (0, 5), "contrast": (0.8, 1.3), "saturation": (0, 1.5),
              "brightness": (-0.1, 0.1), "gamma": (0.8, 1.3), "crop_x": (0, 1), "crop_y": (0, 1)}
    for name, (low, high) in limits.items():
        value = getattr(settings, name)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}.")


def ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def process_options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def probe(path: Path) -> VideoInfo:
    result = subprocess.run(
        [ffmpeg(), "-hide_banner", "-nostdin", "-i", str(path), "-map", "0:v:0",
         "-frames:v", "1", "-f", "null", "-"],
        capture_output=True, timeout=45, **process_options(),
    )
    details = result.stderr.decode("utf-8", errors="replace")
    video_line = next((line for line in details.splitlines() if "Stream #" in line and "Video:" in line), "")
    size = re.search(r"\b([1-9]\d{0,4})x([1-9]\d{0,4})\b", video_line)
    duration = re.search(r"Duration: (\d+):(\d+):([\d.]+)", details)
    fps = re.search(r"([\d.]+) fps", video_line)
    if result.returncode or not size or not duration:
        raise ValueError("This file could not be decoded. Try an MP4, MOV, MKV, or WebM video.\n" + details[-800:])
    width, height = map(int, size.groups())
    rotation = re.search(r"rotation of (-?[\d.]+) degrees", details)
    if rotation and round(float(rotation[1])) % 180:
        width, height = height, width
    seconds = int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
    if seconds <= 0:
        raise ValueError("The video has no readable duration.")
    codec = re.search(r"Video: ([\w]+)", video_line)
    color = re.search(r"\b(bt709|bt470bg|smpte170m|smpte240m|bt2020nc|bt2020c|gbr)/(\w[\w-]*)/(\w[\w-]*)", video_line)
    sar = re.search(r"SAR (\d+):(\d+)", video_line)
    aspect = int(sar[1]) / max(1, int(sar[2])) if sar else 1.0
    if rotation and round(float(rotation[1])) % 180:
        aspect = 1 / aspect
    hdr = "smpte2084" in video_line or "arib-std-b67" in video_line
    shorthand = "bt709" if not color and re.search(r"\bbt709\b", video_line) else ""
    hdr_transfer = "arib-std-b67" if "arib-std-b67" in video_line else "smpte2084" if hdr else ""
    audio_lines = [line for line in details.splitlines() if re.search(r"Stream #0:\d+", line) and "Audio:" in line]
    audio_line = audio_lines[0] if audio_lines else ""
    # SL/SR method files have a conventional stereo duplicate. Prefer that track
    # when converting them back to a standard, single-audio-track MP4.
    prepared_method = "Patched by Compressbase" in details
    if prepared_method or "SL+SR" in audio_line:
        stereo_lines = [line for line in audio_lines if re.search(r"\bstereo\b", line)]
        if stereo_lines:
            # The first track can start as stereo and change layout only in its
            # silent tail, so its initial codec header alone is insufficient.
            audio_line = stereo_lines[-1] if prepared_method else stereo_lines[0]
    audio_index = re.search(r"Stream #0:(\d+)", audio_line)
    audio_layout = "SL+SR" if "SL+SR" in audio_line else "stereo" if "stereo" in audio_line else ""
    return VideoInfo(width, height, seconds, float(fps[1]) if fps else 30.0,
                     "Audio:" in details, hdr, codec[1] if codec else "unknown",
                     color[1] if color else shorthand, color[3] if color else hdr_transfer or shorthand, color[2] if color else shorthand,
                     "pc" if re.search(r"\(pc\b", video_line) else "tv",
                     bool(re.search(r"(?:top|bottom)(?: coded)? first|\b(?:tt|bb|tb|bt)\b", video_line)), aspect,
                     int(audio_index[1]) if audio_index else None, audio_layout)


def color_filters(info: VideoInfo | None) -> list[str]:
    """Convert pixels, then tag the result: setting metadata alone does not convert color."""
    if info and info.hdr:
        transfer = info.color_transfer or "smpte2084"
        matrix = info.color_space or "bt2020nc"
        primaries = info.color_primaries or "bt2020"
        return [f"zscale=matrixin={matrix}:primariesin={primaries}:transferin={transfer}:rangein={info.color_range}:transfer=linear:npl=100",
                "format=gbrpf32le", "zscale=primaries=bt709", "tonemap=tonemap=hable:desat=2",
                "zscale=transfer=bt709:matrix=bt709:range=tv:dither=error_diffusion", "format=yuv420p", "sidedata=mode=delete"]
    if info and info.color_space and info.color_primaries and info.color_transfer:
        return [f"zscale=matrixin={info.color_space}:primariesin={info.color_primaries}:transferin={info.color_transfer}:rangein={info.color_range}:matrix=bt709:primaries=bt709:transfer=bt709:range=tv:dither=error_diffusion",
                "format=yuv420p"]
    matrix = "bt709" if not info or max(info.width, info.height) >= 1280 else "bt601"
    color_range = info.color_range if info else "tv"
    return [f"scale=in_color_matrix={matrix}:out_color_matrix=bt709:in_range={color_range}:out_range=tv", "format=yuv420p"]


def output_dimensions(settings: Settings, info: VideoInfo) -> tuple[int, int]:
    if settings.mobile_compatible:
        width = max(2, int(info.width * info.sample_aspect) // 2 * 2)
        height = max(2, info.height // 2 * 2)
        if settings.mobile_resolution == "Keep original size":
            return width, height
        cap_w, cap_h = (1920, 1080) if width > height else (1080, 1920)
        scale = min(1, cap_w / width, cap_h / height)
        return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)
    return RESOLUTIONS.get(settings.resolution, (max(2, int(info.width * info.sample_aspect) // 2 * 2), max(2, info.height // 2 * 2)))


def mobile_settings(info: VideoInfo, fps: str = "Keep source (normal speed)",
                    resolution: str = "Keep original size") -> Settings:
    selected = "Keep source" if fps == MOBILE_FRAME_RATES[0] else fps
    if selected == "Automatic (30/60 fps)":
        selected = "30 fps" if info.fps <= 30.1 else "60 fps"
    if selected not in ("Keep source", "30 fps", "60 fps"):
        raise ValueError("Choose Keep source, Automatic, 30 fps, or 60 fps for mobile export.")
    if resolution not in MOBILE_RESOLUTIONS:
        raise ValueError("Choose Keep original size or Limit to 1080p for mobile resolution.")
    return Settings(resolution="Original size", fps=selected, sharpen=0, denoise=0, contrast=1,
                    saturation=1, brightness=0, gamma=1, mobile_compatible=True, mobile_resolution=resolution)


def filters(settings: Settings, preview: bool = False, info: VideoInfo | None = None,
            original: bool = False, include_motion: bool = True) -> str:
    validate_settings(settings)
    chain = []
    if info and info.interlaced:
        chain.append("bwdif=mode=send_frame:parity=auto:deint=all")
    chain += color_filters(info)
    chain += ["scale=w=max(2\\,trunc(iw*sar/2)*2):h=max(2\\,trunc(ih/2)*2):flags=lanczos", "setsar=1"]
    if settings.denoise > 0 and not original:
        amount = settings.denoise
        chain.append(f"hqdn3d={amount:.3f}:{amount * 0.75:.3f}:{amount * 1.5:.3f}:{amount * 1.125:.3f}")
    if settings.mobile_compatible:
        if info is None:
            raise ValueError("Source information is required for mobile export.")
        width, height = output_dimensions(settings, info)
        chain.append(f"scale={width}:{height}:flags=lanczos")
    elif settings.resolution != "Original size":
        width, height = RESOLUTIONS[settings.resolution]
        mode = "increase" if settings.framing == "Center crop" else "decrease"
        chain.append(f"scale={width}:{height}:force_original_aspect_ratio={mode}:force_divisible_by=2:flags=lanczos")
        chain.append(f"crop={width}:{height}:(iw-ow)*{settings.crop_x:.4f}:(ih-oh)*{settings.crop_y:.4f}" if mode == "increase" else f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    if not original:
        if settings.deband:
            chain.append("deband=1thr=0.008:2thr=0.008:3thr=0.008:range=12:blur=false")
        chain.append(f"eq=contrast={settings.contrast:.4f}:saturation={settings.saturation:.4f}:brightness={settings.brightness:.4f}:gamma={settings.gamma:.4f}")
        if settings.sharpen > 0:
            chain.append(f"cas=strength={settings.sharpen:.3f}:planes=1" if settings.sharpening == "Adaptive" else f"unsharp=5:5:{settings.sharpen:.3f}:5:5:0")
    if include_motion and not original and settings.motion == MOTION_MODES[1] and (not info or info.fps < 59.9):
        # Work at source-sized pixels before portrait padding would be preferable for speed,
        # but output geometry here makes the sample and full export use identical estimation.
        chain += ["tpad=stop_mode=clone:stop_duration=0.15",
                  "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"]
    if preview:
        chain.append("scale=360:540:force_original_aspect_ratio=decrease:flags=lanczos")
    chain += ["format=yuv420p", "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709"]
    if settings.mobile_compatible and include_motion and settings.fps != "Keep source":
        # Sample the existing timeline. Never assign timestamps from the source
        # frame count: doing so could stretch a 120 fps file into slow motion.
        chain.append(f"fps=fps={settings.fps.split()[0]}:start_time=0:round=near")
    return ",".join(chain)


def preview_frame(path: Path, settings: Settings | None, seconds: float, info: VideoInfo | None = None,
                  original: bool = False, full_size: bool = False) -> Image.Image:
    if info is None:
        info = probe(path)
    moment = max(0, min(seconds, max(0, info.duration - 1 / max(info.fps, 1))))
    # Decode preceding frames so temporal noise reduction has history at the chosen frame.
    start = max(0, moment - 0.75)
    baseline = settings or Settings(resolution="Original size")
    chain = filters(baseline, preview=not full_size, info=info, original=original or settings is None, include_motion=False)
    result = subprocess.run(
        [ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", str(start),
         "-i", str(path), "-ss", str(moment - start), "-map", "0:v:0", "-vf", chain, "-frames:v", "1",
         "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, timeout=120, **process_options(),
    )
    if result.returncode or not result.stdout:
        raise ValueError("Preview failed: " + result.stderr.decode(errors="replace")[-700:])
    with Image.open(io.BytesIO(result.stdout)) as frame:
        return frame.convert("RGB")


def preview_pair(path: Path, settings: Settings, seconds: float, info: VideoInfo, full_size: bool = False):
    return (preview_frame(path, settings, seconds, info, original=True, full_size=full_size),
            preview_frame(path, settings, seconds, info, full_size=full_size))


@dataclass(frozen=True)
class Analysis:
    recommended: Settings
    notes: tuple[str, ...]
    mean_brightness: float


def analyze_source(path: Path, info: VideoInfo) -> Analysis:
    brightness = []
    shadow_fraction = []
    for fraction in (0.15, 0.5, 0.8):
        frame = preview_frame(path, None, info.duration * fraction, info).convert("L")
        brightness.append(ImageStat.Stat(frame).mean[0])
        histogram = frame.histogram()
        shadow_fraction.append(sum(histogram[:9]) / (frame.width * frame.height))
    mean = sum(brightness) / len(brightness)
    notes = []
    dark = sum(value < 65 for value in brightness) >= 2
    values = PRESETS["Low light" if dark else "Balanced"]
    recommended = Settings(**values)
    if info.width >= 1080 and info.height >= 1920:
        recommended = replace(recommended, resolution="1080 × 1920")
    elif info.width >= 720 and info.height >= 1280:
        recommended = replace(recommended, resolution="720 × 1280")
    else:
        recommended = replace(recommended, resolution="Original size")
        notes.append("Keep the original size to avoid enlarging low-resolution footage or reframing landscape video.")
    if dark:
        notes.append("Two or more sampled frames are dark. Try mild shadow lift and noise reduction, then check skin and motion.")
    else:
        notes.append("Use gentle sharpening and restrained color changes; stronger filtering can erase fine detail.")
    if sum(shadow_fraction) / 3 > 0.2:
        notes.append("Many sampled pixels are near black. Raising brightness cannot restore clipped shadow detail.")
    if info.hdr:
        notes.append("HDR detected: previews and Enhance exports are tone-mapped to SDR BT.709. Quality + FPS keeps the original HDR video.")
    if info.interlaced:
        notes.append("Interlaced source detected: Enhance mode deinterlaces automatically; Quality + FPS preserves the original video.")
    if info.fps > 60:
        recommended = replace(recommended, fps="60 fps")
        notes.append("For an Enhance export, the recommendation uses 60 fps. Quality + FPS and keep-source mode can preserve the original higher rate.")
    else:
        notes.append(f"Keep the source's {info.fps:g} fps to preserve its motion without duplicating frames.")
    notes.append("These recommendations use three sampled frames and metadata, not a full-video quality measurement.")
    return Analysis(recommended, tuple(notes), mean)


def export_advice(info: VideoInfo, settings: Settings) -> list[str]:
    width, height = output_dimensions(settings, info)
    notes = []
    source_w, source_h = info.width * info.sample_aspect, info.height
    factor = max(width / source_w, height / source_h) if settings.framing == "Center crop" else min(width / source_w, height / source_h)
    if settings.resolution != "Original size" and factor > 1.05:
        notes.append("This canvas enlarges the source. A larger pixel count will not add captured detail.")
    if settings.resolution != "Original size" and settings.framing == "Center crop":
        retained = (width * height) / (source_w * source_h * factor * factor)
        if retained < 0.75:
            notes.append(f"Crop keeps about {retained:.0%} of the source image area. Adjust the horizontal/vertical crop position.")
    if settings.motion == MOTION_MODES[1] and info.fps < 59.9:
        notes.append("60 fps interpolation generates frames and can warp edges or text. Check a sample clip; processing is slow.")
    elif settings.fps == "60 fps" and info.fps < 59.9:
        notes.append("60 fps export alone duplicates frames. Choose Smooth to 60 fps only if you want generated in-between frames.")
    if settings.sharpen >= 0.7:
        notes.append("Strong sharpening can cause halos and amplify noise. Check the 100% detail view.")
    if settings.denoise >= 2.5 or settings.deband:
        notes.append("Cleanup can soften textures. Compare fine detail and moving areas before the full export.")
    if width > 1080 or height > 1920:
        notes.append("Higher-resolution export preserves a larger master; it does not guarantee TikTok will play it at that resolution.")
    return notes


def export_video(source: Path, destination: Path, info: VideoInfo, settings: Settings,
                 cancel: threading.Event, progress=lambda value: None,
                 start: float = 0.0, duration: float | None = None) -> None:
    validate_settings(settings)
    if source.resolve() == destination.resolve():
        raise ValueError("Choose a different output file to preserve your original.")
    if destination.suffix.lower() != ".mp4":
        raise ValueError("Choose an .mp4 filename for the enhanced export.")
    if not math.isfinite(start) or start < 0 or start >= info.duration:
        raise ValueError("The export start time is outside the video.")
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise ValueError("The sample duration must be positive.")
    length = min(info.duration - start, duration) if duration is not None else info.duration - start
    temporary = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.partial.mp4")
    command = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-ss", str(start),
               "-i", str(source), "-t", str(length), "-map", "0:v:0", "-map",
               f"0:{info.audio_stream_index}" if info.audio_stream_index is not None else "0:a:0?",
               "-vf", filters(settings, info=info), "-c:v", "libx264", "-preset", SPEEDS[settings.speed],
               "-crf", str(QUALITIES[settings.quality]), "-pix_fmt", "yuv420p", "-profile:v", "high",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
               "-map_metadata", "-1", "-map_chapters", "-1"]
    if settings.mobile_compatible:
        keep_source = settings.fps == "Keep source"
        rate = info.fps if keep_source else float(settings.fps.split()[0])
        width, height = output_dimensions(settings, info)
        high_resolution = width * height > 1920 * 1080
        maximum_mbps = (100 if rate > 60.1 else 60 if rate > 30.1 else 40) if high_resolution else (40 if rate > 60.1 else 20 if rate > 30.1 else 12)
        # Let x264 select a valid level for the actual dimensions and frame rate.
        # The old fixed Level 4.2 restriction was inappropriate for 4K output.
        if keep_source:
            # Retain actual presentation times, including fractional rates and
            # variable cadence. A high timescale represents common 120/240 and
            # NTSC rates without rounding them into different playback speeds.
            command += ["-fps_mode", "passthrough", "-enc_time_base:v", "filter", "-video_track_timescale", "240000"]
        else:
            command += ["-r", settings.fps.split()[0], "-fps_mode", "cfr", "-video_track_timescale", "60000"]
        command += ["-maxrate", f"{maximum_mbps}M", "-bufsize", f"{maximum_mbps * 2}M",
                    "-g", str(max(1, round(rate * 2))), "-bf", "2", "-refs", "3"]
        if info.audio:
            audio_filters = ["channelmap=map=0-0|1-1:channel_layout=stereo"] if info.audio_layout == "SL+SR" else []
            audio_filters += ["aresample=48000:async=1:first_pts=0", "apad"]
            command += ["-af", ",".join(audio_filters), "-ac", "2", "-profile:a", "aac_low", "-shortest"]
    elif settings.motion == MOTION_MODES[1] and info.fps < 59.9:
        command += ["-r", "60"]
    elif settings.fps != "Keep source":
        command += ["-r", settings.fps.split()[0]]
    else:
        command += ["-fps_mode", "vfr"]
    command += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
                "-progress", "pipe:1", "-nostats", str(temporary)]
    proc = None
    readers = []
    events = queue.Queue()
    errors = []

    def read_progress():
        for line in proc.stdout:
            events.put(line)

    def read_errors():
        for line in proc.stderr:
            errors.append(line)
            if len(errors) > 60:
                del errors[0]

    try:
        if cancel.is_set():
            raise Cancelled()
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", **process_options())
        readers = [threading.Thread(target=read_progress, daemon=True), threading.Thread(target=read_errors, daemon=True)]
        for reader in readers:
            reader.start()
        while proc.poll() is None or not events.empty():
            if cancel.is_set():
                raise Cancelled()
            try:
                line = events.get(timeout=0.1).strip()
            except queue.Empty:
                continue
            if line.startswith("out_time_us="):
                try:
                    progress(min(0.99, max(0.0, int(line.split("=", 1)[1]) / 1_000_000 / length)))
                except ValueError:
                    pass
        for reader in readers:
            reader.join(timeout=2)
        if proc.returncode:
            raise RuntimeError("Export failed. " + "".join(errors)[-1600:])
        if cancel.is_set():
            raise Cancelled()
        os.replace(temporary, destination)
        progress(1.0)
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            for reader in readers:
                reader.join(timeout=2)
            for pipe in (proc.stdout, proc.stderr):
                if pipe:
                    pipe.close()
        temporary.unlink(missing_ok=True)
