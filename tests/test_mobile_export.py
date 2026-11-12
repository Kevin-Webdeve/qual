import array
import re
import subprocess
import tempfile
import threading
import unittest
from fractions import Fraction
from pathlib import Path

from engine import export_video, ffmpeg, mobile_settings, probe, process_options
from quality_method import prepare_quality_fps


class MobileExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="qual-mobile-test-")
        cls.folder = Path(cls.temp.name)
        cls.source = cls.folder / "120fps-flash-and-beep.mp4"
        cls.run_ffmpeg(["-f", "lavfi", "-i", "color=black:size=320x180:rate=120:duration=2",
                        "-f", "lavfi", "-i", "aevalsrc=if(between(t\\,1\\,1.1)\\,0.8*sin(2*PI*1000*t)\\,0):s=48000:d=2",
                        "-vf", "drawbox=color=white:t=fill:enable='between(t,1,1.1)'", "-c:v", "libx264", "-c:a", "aac", str(cls.source)])

    @classmethod
    def run_ffmpeg(cls, arguments):
        result = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", *arguments],
                                capture_output=True, **process_options())
        if result.returncode:
            raise AssertionError(result.stderr.decode(errors="replace"))
        return result.stdout

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def assert_normal_timing(self, video, fps, duration=2, event_time=1):
        info = probe(video)
        self.assertEqual(info.fps, fps)
        self.assertAlmostEqual(info.duration, duration, delta=0.08)
        frames = self.run_ffmpeg(["-i", str(video), "-map", "0:v:0", "-vf", "scale=8:8", "-pix_fmt", "gray", "-f", "rawvideo", "-"])
        first_flash = next(index // 64 for index in range(0, len(frames), 64) if frames[index] > 200) / fps
        self.assertAlmostEqual(first_flash, event_time, delta=1 / fps + 0.005)
        audio = array.array("f")
        audio.frombytes(self.run_ffmpeg(["-i", str(video), "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"]))
        first_beep = next(index for index, sample in enumerate(audio) if abs(sample) > 0.3) / 48000
        self.assertLessEqual(abs(first_beep - first_flash), 1 / fps + 0.015)
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "frames.txt"
            self.run_ffmpeg(["-i", str(video), "-map", "0:v:0", "-c:v", "copy", "-f", "framehash", str(report)])
            records = [line.split(",") for line in report.read_text().splitlines() if line and not line.startswith("#")]
            pts = sorted(int(record[2]) for record in records)
            intervals = {second - first for first, second in zip(pts, pts[1:])}
            self.assertEqual(len(intervals), 1, "Output presentation timestamps must have constant spacing")

    def test_120fps_becomes_60_without_slow_motion_or_audio_drift(self):
        output = self.folder / "mobile-60.mp4"
        info = probe(self.source)
        export_video(self.source, output, info, mobile_settings(info, "Automatic (30/60 fps)"), threading.Event())
        self.assert_normal_timing(output, 60)
        self.assertEqual(probe(output).audio_layout, "stereo")

    def test_prepared_file_becomes_single_stereo_track_without_audio_tail(self):
        prepared = self.folder / "experimental.mp4"
        prepare_quality_fps(self.source, prepared, probe(self.source), threading.Event())
        info = probe(prepared)
        self.assertEqual(info.audio_layout, "stereo")
        self.assertEqual(info.audio_stream_index, 2)
        output = self.folder / "repaired-mobile-30.mp4"
        export_video(prepared, output, info, mobile_settings(info, "30 fps"), threading.Event())
        self.assert_normal_timing(output, 30)
        result = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(output), "-map", "0:v:0", "-frames:v", "1", "-f", "null", "-"],
                                capture_output=True, **process_options())
        tracks = [line for line in result.stderr.decode().splitlines() if "Stream #0:" in line and "Audio:" in line]
        self.assertEqual(len(tracks), 1)
        self.assertNotIn("SL+SR", tracks[0])

    def test_variable_rate_becomes_constant_60_with_beep_still_aligned(self):
        source = self.folder / "variable.mp4"
        self.run_ffmpeg(["-i", str(self.source), "-vf", "select=not(mod(n\\,3))+not(mod(n\\,7))", "-fps_mode", "vfr",
                         "-c:v", "libx264", "-c:a", "copy", str(source)])
        info = probe(source)
        output = self.folder / "variable-mobile.mp4"
        export_video(source, output, info, mobile_settings(info, "60 fps"), threading.Event())
        self.assert_normal_timing(output, 60)

    def source_4k(self):
        source = self.folder / "4k-120fps.mp4"
        if not source.exists():
            self.run_ffmpeg(["-f", "lavfi", "-i", "color=black:size=3840x2160:rate=120:duration=0.4",
                             "-f", "lavfi", "-i", "aevalsrc=if(between(t\\,0.15\\,0.25)\\,0.8*sin(2*PI*1000*t)\\,0):s=48000:d=0.4",
                             "-vf", "drawbox=color=white:t=fill:enable='between(t,0.15,0.25)'",
                             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(source)])
        return source

    def test_4k_mobile_preserves_dimensions_and_audio_timing(self):
        source = self.source_4k()
        info = probe(source)
        self.assertEqual(info.fps, 120)
        output = self.folder / "mobile-4k-60.mp4"
        export_video(source, output, info, mobile_settings(info, "Automatic (30/60 fps)"), threading.Event())
        result = probe(output)
        self.assertEqual((result.width, result.height), (3840, 2160))
        self.assert_normal_timing(output, 60, duration=0.4, event_time=0.15)
        headers = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "trace", "-i", str(output), "-map", "0:v:0",
                                  "-c:v", "copy", "-bsf:v", "trace_headers", "-frames:v", "1", "-f", "null", "-"],
                                 capture_output=True, **process_options()).stderr.decode(errors="replace")
        level = re.search(r"level_idc\s+[01]+\s*=\s*(\d+)", headers)
        self.assertIsNotNone(level, headers[-3000:])
        self.assertGreaterEqual(int(level[1]), 52, "4K60 must not be incorrectly labeled as Level 4.2")

    def test_4k_portrait_keeps_display_orientation_and_audio_timing(self):
        source = self.folder / "4k-portrait.mp4"
        self.run_ffmpeg(["-display_rotation:v:0", "90", "-i", str(self.source_4k()), "-c", "copy", str(source)])
        info = probe(source)
        output = self.folder / "mobile-portrait-4k.mp4"
        export_video(source, output, info, mobile_settings(info, "30 fps"), threading.Event())
        result = probe(output)
        self.assertEqual((result.width, result.height), (2160, 3840))
        self.assert_normal_timing(output, 30, duration=0.4, event_time=0.15)

    def test_1080p_limit_is_optional_for_a_4k_source(self):
        source = self.source_4k()
        info = probe(source)
        output = self.folder / "mobile-1080-limit.mp4"
        export_video(source, output, info, mobile_settings(info, "Automatic (30/60 fps)", resolution="Limit to 1080p"), threading.Event(), duration=0.1)
        result = probe(output)
        self.assertEqual((result.width, result.height), (1920, 1080))
        self.assertEqual(result.fps, 60)

    def presentation_times(self, video):
        text = self.run_ffmpeg(["-i", str(video), "-map", "0:v:0", "-c:v", "copy", "-f", "framehash", "-"]).decode()
        time_base = next(Fraction(line.split(":", 1)[1].strip()) for line in text.splitlines() if line.startswith("#tb 0:"))
        times = sorted(int(line.split(",")[2]) * time_base for line in text.splitlines() if line and not line.startswith("#"))
        return [moment - times[0] for moment in times]

    def assert_source_timing(self, source, output):
        first, second = self.presentation_times(source), self.presentation_times(output)
        self.assertEqual(len(first), len(second), "Native mode must preserve the frame count")
        self.assertTrue(all(abs(a-b) <= Fraction(1, 100_000) for a, b in zip(first, second)),
                        "Native mode must preserve relative frame presentation times")

    def test_native_120fps_keeps_normal_speed_frame_count_and_audio_sync(self):
        info = probe(self.source)
        output = self.folder / "native-120.mp4"
        export_video(self.source, output, info, mobile_settings(info), threading.Event())
        self.assert_normal_timing(output, 120)
        self.assert_source_timing(self.source, output)

    def test_native_4k_120fps_is_not_retimed_to_slow_motion(self):
        source = self.source_4k()
        info = probe(source)
        output = self.folder / "native-4k-120.mp4"
        export_video(source, output, info, mobile_settings(info), threading.Event())
        result = probe(output)
        self.assertEqual((result.width, result.height, result.fps), (3840, 2160, 120))
        self.assert_normal_timing(output, 120, duration=0.4, event_time=0.15)
        self.assert_source_timing(source, output)

    def test_native_fractional_11988fps_preserves_frame_timestamps(self):
        source = self.folder / "fractional.mp4"
        self.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=120000/1001:duration=0.4",
                         "-c:v", "libx264", str(source)])
        info = probe(source)
        output = self.folder / "fractional-native.mp4"
        export_video(source, output, info, mobile_settings(info), threading.Event())
        self.assertAlmostEqual(probe(output).fps, info.fps, delta=0.01)
        self.assert_source_timing(source, output)

    def test_native_variable_frame_timing_is_not_replaced_by_average_fps(self):
        source = self.folder / "native-variable-source.mp4"
        self.run_ffmpeg(["-i", str(self.source), "-vf", "select=not(mod(n\\,3))+not(mod(n\\,7))", "-fps_mode", "vfr",
                         "-c:v", "libx264", "-c:a", "copy", str(source)])
        info = probe(source)
        output = self.folder / "native-variable-output.mp4"
        export_video(source, output, info, mobile_settings(info), threading.Event())
        self.assert_source_timing(source, output)


if __name__ == "__main__":
    unittest.main()
