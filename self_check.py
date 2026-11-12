"""Diagnostic entry point for checking the frozen desktop application."""
import json
import subprocess
import tempfile
import threading
import traceback
from pathlib import Path

from engine import Settings, export_video, ffmpeg, mobile_settings, preview_frame, probe, process_options
from quality_method import prepare_quality_fps


def run(report_path):
    report = {}
    try:
        from app import QualityStudio
        app = QualityStudio()
        app.withdraw()
        app.update_idletasks()
        report["desktop"] = "ok"
        app.destroy()
        with tempfile.TemporaryDirectory(prefix="qual-frozen-") as folder:
            source = Path(folder) / "sample.mp4"
            destination = Path(folder) / "enhanced.mp4"
            subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=180x320:rate=24", "-t", "0.5", "-c:v", "libx264", str(source)],
                           check=True, capture_output=True, **process_options())
            info = probe(source)
            preview_frame(source, Settings(resolution="720 × 1280"), 0.1)
            export_video(source, destination, info, Settings(resolution="720 × 1280"), threading.Event())
            result = probe(destination)
            assert (result.width, result.height) == (720, 1280)
            report["preview_and_export"] = "ok"
            prepared = Path(folder) / "quality-fps.mp4"
            verification = prepare_quality_fps(source, prepared, info, threading.Event())
            assert verification["video_packet_hashes_unchanged"]
            report["quality_fps_method"] = "ok"
            report["frame_timing_max_drift_ms"] = verification["relative_frame_timing_max_drift_ms"]
            mobile = Path(folder) / "mobile.mp4"
            prepared_info = probe(prepared)
            export_video(prepared, mobile, prepared_info, mobile_settings(prepared_info), threading.Event())
            mobile_info = probe(mobile)
            assert mobile_info.fps == info.fps
            assert mobile_info.audio_layout == "stereo"
            assert abs(mobile_info.duration - info.duration) < 0.08
            report["mobile_export"] = "ok"
            source_4k = Path(folder) / "4k-source.mp4"
            subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "color=black:size=3840x2160:rate=120:duration=0.1", "-c:v", "libx264", "-preset", "ultrafast", str(source_4k)],
                           check=True, capture_output=True, **process_options())
            mobile_4k = Path(folder) / "mobile-4k.mp4"
            info_4k = probe(source_4k)
            export_video(source_4k, mobile_4k, info_4k, mobile_settings(info_4k), threading.Event())
            result_4k = probe(mobile_4k)
            assert (result_4k.width, result_4k.height, result_4k.fps) == (3840, 2160, 120)
            report["mobile_4k_export"] = "ok"
            report["mobile_4k_source_fps"] = result_4k.fps
        report["passed"] = True
    except Exception:
        report["passed"] = False
        report["error"] = traceback.format_exc()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)
