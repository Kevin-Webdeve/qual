"""Hidden desktop integration check; requires an interactive Windows session."""
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import QualityStudio, ENHANCE, METHOD, MOBILE
from engine import ffmpeg, probe, process_options


def wait_for_idle(app):
    deadline = time.monotonic() + 45
    while app.busy:
        app.update()
        if time.monotonic() > deadline:
            raise TimeoutError("Desktop task did not finish")
        time.sleep(0.02)


with tempfile.TemporaryDirectory(prefix="qual-ui-") as folder:
    source = Path(folder) / "source.mp4"
    output = Path(folder) / "enhanced.mp4"
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=180x320:rate=24", "-t", "1", "-c:v", "libx264", str(source)],
                   check=True, capture_output=True, **process_options())
    app = QualityStudio()
    app.withdraw()
    try:
        app.update_idletasks()
        assert app.workflow.get() == MOBILE
        assert app.mobile_resolution.get() == "Keep original size"
        assert app.mobile_fps.get() == "Keep source (normal speed)"
        assert app.winfo_reqheight() <= 760, app.winfo_reqheight()
        with patch("app.filedialog.askopenfilename", return_value=str(source)), patch("app.messagebox.showerror", side_effect=AssertionError):
            app.choose_video()
            wait_for_idle(app)
        assert app.source == source
        assert len(app.preview_pair) == 2
        assert str(app.export_btn["state"]) == "normal"
        mobile_output = Path(folder) / "mobile.mp4"
        with patch("app.filedialog.asksaveasfilename", return_value=str(mobile_output)), patch("app.messagebox.showerror", side_effect=AssertionError):
            app.export()
            wait_for_idle(app)
        assert mobile_output.is_file()
        assert probe(mobile_output).fps == 24
        app.workflow.set(ENHANCE)
        app.preset.set("Crisp edits")
        app.apply_preset()
        assert app.settings().sharpen == 0.65
        app.resolution.set("720 × 1280")
        app.refresh_preview()
        wait_for_idle(app)
        with patch("app.filedialog.asksaveasfilename", return_value=str(output)), patch("app.messagebox.showerror", side_effect=AssertionError):
            app.export()
            wait_for_idle(app)
        assert output.is_file()
        assert app.output == output
        assert probe(output).height == 1280
        assert app.progress["value"] == 100
        app.show_detail()
        wait_for_idle(app)
        assert app.last_detail is not None
        assert app.last_detail.pair[0].size == app.last_detail.pair[1].size
        app.last_detail.destroy()
        app.analyze()
        wait_for_idle(app)
        assert app.analysis is not None
        assert app.analysis.recommended.resolution == "Original size"
        with patch("app.os.startfile"):
            app.make_sample()
            wait_for_idle(app)
        assert app.output.is_file()
        app.workflow.set(METHOD)
        prepared = Path(folder) / "quality-fps.mp4"
        with patch("app.filedialog.asksaveasfilename", return_value=str(prepared)), patch("app.messagebox.showerror", side_effect=AssertionError):
            app.export()
            wait_for_idle(app)
        assert prepared.is_file()
        assert prepared.with_suffix(".quality-fps.json").is_file()
        assert probe(prepared).fps == 24
        source_4k = Path(folder) / "4k-original.mp4"
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=black:size=3840x2160:rate=120:duration=0.2", "-c:v", "libx264", "-preset", "ultrafast", str(source_4k)],
                       check=True, capture_output=True, **process_options())
        app.workflow.set(MOBILE)
        with patch("app.filedialog.askopenfilename", return_value=str(source_4k)), patch("app.messagebox.showerror", side_effect=AssertionError):
            app.choose_video()
            wait_for_idle(app)
        for resolution, dimensions in [("Keep original size", (3840, 2160)), ("Limit to 1080p", (1920, 1080))]:
            app.mobile_resolution.set(resolution)
            saved = Path(folder) / ("ui-4k.mp4" if dimensions[0] == 3840 else "ui-1080.mp4")
            with patch("app.filedialog.asksaveasfilename", return_value=str(saved)), patch("app.messagebox.showerror", side_effect=AssertionError):
                app.export()
                wait_for_idle(app)
            result = probe(saved)
            assert (result.width, result.height) == dimensions
            assert result.fps == 120
        print("PASS: hidden desktop mobile 4K and 1080p selection/export, preview, preset, analysis, detail, sample, enhanced export, Quality + FPS, and layout")
    finally:
        app.destroy()
