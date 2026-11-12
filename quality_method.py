"""Offline desktop integration of CompressBase's public local SL/SR helper.

Video packets and relative presentation times are verified before committing output.
The helper is third-party code; credit and provenance are bundled with the app.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from fractions import Fraction
from pathlib import Path

from engine import Cancelled, VideoInfo, ffmpeg, process_options


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _run(command: list[str], cancel: threading.Event) -> bytes:
    if cancel.is_set():
        raise Cancelled()
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=output, stderr=errors, **process_options())
        try:
            while process.poll() is None:
                if cancel.wait(0.1):
                    raise Cancelled()
            if cancel.is_set():
                raise Cancelled()
            if process.returncode:
                errors.seek(0, os.SEEK_END)
                errors.seek(max(0, errors.tell() - 5000))
                raise ValueError(errors.read().decode("utf-8", errors="replace") or "The video preparation command failed.")
            output.seek(0)
            return output.read(100_000)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def _frames(path: Path):
    time_base = Fraction(1, 1)
    first_pts = None
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("#tb 0:"):
                time_base = Fraction(line.split(":", 1)[1].strip())
            elif line.strip() and not line.startswith("#"):
                columns = [item.strip() for item in line.split(",")]
                if len(columns) != 6:
                    raise ValueError("Unexpected video verification format.")
                pts = int(columns[2]) * time_base
                if first_pts is None:
                    first_pts = pts
                yield pts - first_pts, int(columns[4]), columns[5], int(columns[3]) * time_base


def verify_video_packets(source: Path, output: Path, folder: Path, cancel: threading.Event) -> dict:
    files = [folder / "source.frames", folder / "output.frames"]
    for video, report in zip((source, output), files):
        _run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(video),
              "-map", "0:v:0", "-c:v", "copy", "-f", "framehash", "-hash", "sha256", str(report)], cancel)
    from itertools import zip_longest
    count = 0
    digest = hashlib.sha256()
    maximum_drift = Fraction(0)
    for original, prepared in zip_longest(_frames(files[0]), _frames(files[1])):
        if cancel.is_set():
            raise Cancelled()
        if original is None or prepared is None or original[1:3] != prepared[1:3]:
            raise ValueError("Video packet verification failed. No prepared video was saved.")
        drift = max(abs(original[0] - prepared[0]), abs(original[3] - prepared[3]))
        maximum_drift = max(maximum_drift, drift)
        if drift > Fraction(1, 1000):
            raise ValueError("Video frame timing changed by more than 1 ms. No prepared video was saved.")
        digest.update(f"{original[1]}:{original[2]}\n".encode())
        count += 1
    if not count:
        raise ValueError("The video contains no verifiable packets.")
    return {"video_packet_count": count, "video_packet_hashes_unchanged": True,
            "relative_frame_timing_max_drift_ms": float(maximum_drift * 1000),
            "packet_manifest_sha256": digest.hexdigest()}


def prepare_quality_fps(source: Path, destination: Path, info: VideoInfo,
                        cancel: threading.Event, progress=lambda value: None,
                        status=lambda value: None) -> dict:
    if source.resolve() == destination.resolve():
        raise ValueError("Choose a different output filename to preserve your original.")
    if source.suffix.lower() not in (".mp4", ".mov", ".m4v"):
        raise ValueError("Quality + FPS accepts MP4, MOV, or M4V. Use Enhance + export to create an MP4 first.")
    if destination.suffix.lower() != ".mp4":
        raise ValueError("Save the prepared video as an .mp4 file.")
    if info.codec not in ("h264", "hevc", "av1"):
        raise ValueError("Quality + FPS preserves H.264, HEVC, or AV1 video. Use Enhance + export to convert this video first.")
    if source.stat().st_size > 8 * 1024 ** 3:
        raise ValueError("This method supports source files up to 8 GiB.")
    assets = resource_root()
    node = assets / "vendor" / "node" / "node.exe"
    helper = assets / "vendor" / "method" / "sl-sr.mjs"
    runner = assets / "method_runner.mjs"
    if not all(path.is_file() for path in (node, helper, runner)):
        raise ValueError("The local method runtime is missing. Run tools/setup_method.py or use the complete packaged app folder.")
    provenance = json.loads((assets / "vendor" / "method-provenance.json").read_text(encoding="utf-8"))
    if hashlib.sha256(helper.read_bytes()).hexdigest() != provenance["helper_sha256"]:
        raise ValueError("The bundled method helper failed its integrity check. Restore the complete app folder.")
    if cancel.is_set():
        raise Cancelled()
    with tempfile.TemporaryDirectory(prefix=".qual-method-", dir=destination.parent) as folder:
        folder = Path(folder)
        normalized = folder / "normalized.mp4"
        prepared = folder / "prepared.mp4"
        status("Preparing AAC stereo audio; copying the encoded video without filters…")
        command = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-noautorotate", "-i", str(source)]
        if not info.audio:
            command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        command += ["-map", "0:v:0", "-map", "0:a:0" if info.audio else "1:a:0", "-c:v", "copy",
                    "-c:a", "aac", "-profile:a", "aac_low", "-ac", "2", "-ar", "48000", "-b:a", "192k",
                    "-map_metadata", "-1", "-map_chapters", "-1", "-metadata", "comment=Patched by Compressbase",
                    "-movflags", "+faststart", "-t", str(info.duration), str(normalized)]
        _run(command, cancel)
        progress(0.3)
        status("Applying CompressBase's local Quality + FPS method…")
        _run([str(node), "--no-warnings", str(runner), str(helper), str(normalized), str(prepared)], cancel)
        progress(0.55)
        status("Verifying that encoded video packets and frame timing are unchanged…")
        verification = verify_video_packets(source, prepared, folder, cancel)
        progress(0.8)
        status("Checking that the prepared video and both audio tracks decode…")
        # The helper intentionally uses SL/SR for its first track. Relabel its two
        # decoded channels for the null-output PCM encoder, which cannot resample
        # an isolated SL/SR pair. This validation does not modify the saved file.
        _run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-xerror", "-nostdin", "-i", str(prepared),
              "-map", "0:v:0", "-map", "0:a:0", "-map", "0:a:1", "-filter:a:0", "channelmap=map=0-0|1-1:channel_layout=stereo",
              "-f", "null", "-"], cancel)
        report = {"method": "CompressBase public local SL/SR Quality + FPS", "source": str(source),
                  "output": str(destination), "source_fps": info.fps, "source_resolution": [info.width, info.height],
                  "video_reencoded": False, "audio": "AAC-LC stereo conversion, SL/SR tail and stereo duplicate",
                  "verified_audio_tracks": 2,
                  "decode_check_passed": True, "output_bytes": prepared.stat().st_size,
                  "note": "Preserves local encoded video; does not guarantee TikTok resolution, FPS, or compression behavior.",
                  **verification}
        report_file = folder / "report.json"
        report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if cancel.is_set():
            raise Cancelled()
        # Commit only after every local verification passes.
        os.replace(prepared, destination)
        os.replace(report_file, destination.with_suffix(".quality-fps.json"))
        progress(1.0)
        return report
