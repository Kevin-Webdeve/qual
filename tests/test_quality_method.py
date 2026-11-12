import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from engine import Cancelled, ffmpeg, probe, process_options
from quality_method import prepare_quality_fps


class QualityMethodIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="qual-method-test-")
        cls.folder = Path(cls.temp.name)
        cls.source = cls.folder / "120fps original.mp4"
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=320x180:rate=120", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                        "-t", "0.6", "-c:v", "libx264", "-c:a", "aac", str(cls.source)],
                       check=True, capture_output=True, **process_options())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_method_preserves_120fps_video_and_decodes_two_audio_tracks(self):
        output = self.folder / "prepared.mp4"
        report = prepare_quality_fps(self.source, output, probe(self.source), threading.Event())
        self.assertEqual(probe(output).fps, 120)
        self.assertTrue(report["video_packet_hashes_unchanged"])
        self.assertEqual(report["video_packet_count"], 72)
        self.assertLessEqual(report["relative_frame_timing_max_drift_ms"], 1)
        self.assertFalse(report["video_reencoded"])
        self.assertTrue(report["decode_check_passed"])
        self.assertTrue(json.loads(output.with_suffix(".quality-fps.json").read_text())["decode_check_passed"])
        result = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(output), "-f", "null", "-"],
                                capture_output=True, **process_options())
        self.assertIn(b"SL+SR", result.stderr)
        self.assertIn(b"stereo", result.stderr)

    def test_silent_video_gets_method_audio_without_changing_video(self):
        silent = self.folder / "silent.mp4"
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(self.source), "-an", "-c:v", "copy", str(silent)],
                       check=True, capture_output=True, **process_options())
        output = self.folder / "silent-prepared.mp4"
        report = prepare_quality_fps(silent, output, probe(silent), threading.Event())
        self.assertTrue(report["video_packet_hashes_unchanged"])
        self.assertTrue(probe(output).audio)

    def test_cancellation_preserves_existing_output(self):
        output = self.folder / "cancel.mp4"
        output.write_bytes(b"existing video")
        cancel = threading.Event()
        with self.assertRaises(Cancelled):
            prepare_quality_fps(self.source, output, probe(self.source), cancel, lambda value: cancel.set())
        self.assertEqual(output.read_bytes(), b"existing video")
        self.assertFalse(list(self.folder.glob(".qual-method-*")))

    def test_variable_frame_timing_is_preserved(self):
        source = self.folder / "variable.mp4"
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(self.source),
                        "-vf", "select=not(mod(n\\,3))+not(mod(n\\,7))", "-fps_mode", "vfr",
                        "-c:v", "libx264", "-an", str(source)], check=True, capture_output=True, **process_options())
        output = self.folder / "variable-prepared.mp4"
        report = prepare_quality_fps(source, output, probe(source), threading.Event())
        self.assertTrue(report["video_packet_hashes_unchanged"])
        self.assertLess(report["video_packet_count"], 72)
        self.assertLessEqual(report["relative_frame_timing_max_drift_ms"], 1)

    def test_source_cannot_be_overwritten(self):
        before = self.source.read_bytes()
        with self.assertRaises(ValueError):
            prepare_quality_fps(self.source, self.source, probe(self.source), threading.Event())
        self.assertEqual(self.source.read_bytes(), before)

    def test_rotation_metadata_survives_video_copy(self):
        rotated = self.folder / "rotated.mp4"
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-display_rotation:v:0", "90", "-i", str(self.source),
                        "-c", "copy", str(rotated)],
                       check=True, capture_output=True, **process_options())
        info = probe(rotated)
        self.assertEqual((info.width, info.height), (180, 320))
        output = self.folder / "rotated-prepared.mp4"
        prepare_quality_fps(rotated, output, info, threading.Event())
        result = probe(output)
        self.assertEqual((result.width, result.height), (180, 320))


if __name__ == "__main__":
    unittest.main()
