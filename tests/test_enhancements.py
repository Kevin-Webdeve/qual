import subprocess
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from engine import (MOTION_MODES, Settings, analyze_source, export_video, ffmpeg,
                    preview_frame, preview_pair, probe, process_options)


class EnhancementIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="qual-enhancement-")
        cls.folder = Path(cls.temp.name)
        cls.source = cls.folder / "source.mp4"
        cls.command(["-f", "lavfi", "-i", "testsrc2=size=160x288:rate=24", "-t", "1",
                     "-c:v", "libx264", str(cls.source)])
        cls.info = probe(cls.source)

    @classmethod
    def command(cls, arguments):
        result = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", *arguments],
                                capture_output=True, **process_options())
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))
        return result

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_matching_canvas_and_full_resolution_preview(self):
        settings = Settings(resolution="720 × 1280", framing="Center crop")
        original, enhanced = preview_pair(self.source, settings, 0.4, self.info, full_size=True)
        self.assertEqual(original.size, (720, 1280))
        self.assertEqual(original.size, enhanced.size)
        self.assertNotEqual(original.tobytes(), enhanced.tobytes())

    def test_hdr_pq_and_hlg_tone_map_to_sdr(self):
        for transfer in ("smpte2084", "arib-std-b67"):
            with self.subTest(transfer=transfer):
                source = self.folder / f"hdr-{transfer}.mp4"
                self.command(["-i", str(self.source), "-t", "0.3", "-vf",
                              "zscale=matrixin=bt709:primariesin=bt709:transferin=bt709:rangein=tv:matrix=bt2020nc:primaries=bt2020:transfer=" + transfer,
                              "-pix_fmt", "yuv420p10le", "-c:v", "libx265", "-preset", "ultrafast",
                              "-x265-params", "pools=1:frame-threads=1", "-color_primaries", "bt2020",
                              "-colorspace", "bt2020nc", "-color_trc", transfer, str(source)])
                info = probe(source)
                self.assertTrue(info.hdr)
                self.assertEqual(info.color_transfer, transfer)
                preview = preview_frame(source, Settings(resolution="Original size"), 0.1, info)
                self.assertGreater(preview.convert("L").getextrema()[1], 80)
                output = self.folder / f"sdr-{transfer}.mp4"
                export_video(source, output, info, Settings(resolution="Original size"), threading.Event())
                result = probe(output)
                self.assertFalse(result.hdr)
                self.assertEqual(result.color_transfer, "bt709")
                self.assertEqual(result.color_range, "tv")

    def test_interpolation_creates_distinct_frames_and_preserves_duration(self):
        output = self.folder / "motion.mp4"
        settings = Settings(resolution="Original size", motion=MOTION_MODES[1])
        export_video(self.source, output, self.info, settings, threading.Event())
        info = probe(output)
        self.assertEqual(info.fps, 60)
        self.assertAlmostEqual(info.duration, self.info.duration, delta=0.08)
        hashes = self.command(["-i", str(output), "-map", "0:v:0", "-f", "framehash", "-"]).stdout.decode()
        unique = {line.split(",")[-1].strip() for line in hashes.splitlines() if not line.startswith("#")}
        self.assertGreater(len(unique), 24)

    def test_short_clip_and_cleanup_filters(self):
        output = self.folder / "sample.mp4"
        settings = Settings(resolution="Original size", deband=True, sharpening="Classic", gamma=1.1)
        export_video(self.source, output, self.info, settings, threading.Event(), start=0.3, duration=0.4)
        self.assertAlmostEqual(probe(output).duration, 0.4, delta=0.08)

    def test_dark_source_analysis_is_conservative(self):
        source = self.folder / "dark.mp4"
        self.command(["-f", "lavfi", "-i", "color=black:size=160x288:rate=24", "-t", "0.4", "-c:v", "libx264", str(source)])
        analysis = analyze_source(source, probe(source))
        self.assertEqual(analysis.recommended.resolution, "Original size")
        self.assertLessEqual(analysis.recommended.sharpen, 0.35)
        self.assertTrue(any("near black" in note for note in analysis.notes))

    def test_invalid_settings_do_not_replace_existing_file(self):
        output = self.folder / "invalid.mp4"
        output.write_bytes(b"existing file")
        with self.assertRaises(ValueError):
            export_video(self.source, output, self.info, replace(Settings(), sharpen=float("nan")), threading.Event())
        self.assertEqual(output.read_bytes(), b"existing file")

    def test_real_4k_export(self):
        output = self.folder / "4k.mp4"
        settings = Settings(resolution="2160 × 3840 (4K)", speed="Fast preview / export", denoise=0)
        export_video(self.source, output, self.info, settings, threading.Event(), duration=0.1)
        info = probe(output)
        self.assertEqual((info.width, info.height), (2160, 3840))

    def test_interlaced_source_is_deinterlaced(self):
        source = self.folder / "interlaced.mp4"
        self.command(["-i", str(self.source), "-vf", "tinterlace=mode=interleave_top", "-c:v", "libx264",
                      "-flags:v", "+ilme+ildct", "-x264-params", "tff=1", str(source)])
        info = probe(source)
        self.assertTrue(info.interlaced)
        output = self.folder / "progressive.mp4"
        export_video(source, output, info, Settings(resolution="Original size"), threading.Event())
        self.assertFalse(probe(output).interlaced)

    def test_full_range_gray_converts_without_washing_out(self):
        source = self.folder / "full-range.mp4"
        self.command(["-f", "lavfi", "-i", "color=0x808080:size=160x288:rate=24", "-t", "0.3",
                      "-vf", "scale=out_range=full", "-color_range", "pc", "-c:v", "libx264", "-qp", "0", str(source)])
        info = probe(source)
        self.assertEqual(info.color_range, "pc")
        frame = preview_frame(source, None, 0.1, info)
        low, high = frame.convert("L").getextrema()
        self.assertGreaterEqual(low, 123)
        self.assertLessEqual(high, 133)


if __name__ == "__main__":
    unittest.main()
