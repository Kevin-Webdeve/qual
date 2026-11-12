import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from engine import Cancelled, Settings, export_video, ffmpeg, preview_frame, probe, process_options


class ExportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="qual-test-")
        cls.folder = Path(cls.temp.name)
        cls.source = cls.folder / "original video.mp4"
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=320x180:rate=24", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                        "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.source)],
                       check=True, capture_output=True, **process_options())
        cls.info = probe(cls.source)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_probe_and_real_preview(self):
        self.assertEqual((self.info.width, self.info.height), (320, 180))
        self.assertTrue(self.info.audio)
        self.assertEqual(self.info.fps, 24)
        original = preview_frame(self.source, None, 0.2)
        enhanced = preview_frame(self.source, Settings(resolution="720 × 1280"), 0.2)
        self.assertGreater(original.width, original.height)
        self.assertGreater(enhanced.height, enhanced.width)

    def test_export_portrait_audio_fps_and_atomic_overwrite(self):
        output = self.folder / "portrait.mp4"
        output.write_bytes(b"old destination")
        progress = []
        export_video(self.source, output, self.info, Settings(resolution="720 × 1280", fps="30 fps"),
                     threading.Event(), progress.append)
        info = probe(output)
        self.assertEqual((info.width, info.height), (720, 1280))
        self.assertEqual(info.fps, 30)
        self.assertTrue(info.audio)
        self.assertEqual(progress[-1], 1)
        self.assertFalse(list(self.folder.glob("*.partial.mp4")))

    def test_center_crop_silent_video(self):
        silent = self.folder / "silent.mp4"
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(self.source),
                        "-an", "-c:v", "copy", str(silent)], check=True, capture_output=True, **process_options())
        output = self.folder / "cropped.mp4"
        export_video(silent, output, probe(silent), Settings(resolution="720 × 1280", framing="Center crop"), threading.Event())
        info = probe(output)
        self.assertEqual((info.width, info.height), (720, 1280))
        self.assertFalse(info.audio)
        self.assertEqual(info.fps, 24)

    def test_original_dimensions_and_source_protection(self):
        before = self.source.read_bytes()
        with self.assertRaises(ValueError):
            export_video(self.source, self.source, self.info, Settings(), threading.Event())
        self.assertEqual(self.source.read_bytes(), before)
        output = self.folder / "original-size.mp4"
        export_video(self.source, output, self.info, Settings(resolution="Original size"), threading.Event())
        self.assertEqual((probe(output).width, probe(output).height), (320, 180))

    def test_cancel_during_export_preserves_destination(self):
        destination = self.folder / "cancelled.mp4"
        destination.write_bytes(b"preserve existing destination")
        cancel = threading.Event()

        def stop(value):
            cancel.set()

        with self.assertRaises(Cancelled):
            export_video(self.source, destination, self.info, Settings(), cancel, stop)
        self.assertEqual(destination.read_bytes(), b"preserve existing destination")
        self.assertFalse(list(self.folder.glob("*.partial.mp4")))

    def test_invalid_input(self):
        invalid = self.folder / "broken.mp4"
        invalid.write_text("not a video")
        with self.assertRaises(ValueError):
            probe(invalid)


if __name__ == "__main__":
    unittest.main()
