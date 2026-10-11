import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import imageio_ffmpeg
from PIL import Image

from douyin_downloader.adapters.media import compose_slideshow
from douyin_downloader.application.service import run_download
from douyin_downloader.domain.models import (
    Content,
    DownloadCancelled,
    DownloadError,
    DownloadOptions,
)
from douyin_downloader.infrastructure.assets import record_rejected_asset


class MediaTests(unittest.TestCase):
    @staticmethod
    def create_motion(path):
        writer = imageio_ffmpeg.write_frames(
            str(path), (64, 64), fps=4, codec="libx264", ffmpeg_log_level="error"
        )
        writer.send(None)
        try:
            for color in ("red", "blue", "red", "blue"):
                writer.send(Image.new("RGB", (64, 64), color).tobytes())
        finally:
            writer.close()

    def test_dynamic_video_loops_with_music_and_mixed_still_image(self):
        with tempfile.TemporaryDirectory(prefix="motion's 中文 ") as name:
            folder = Path(name)
            cover, still, motion, audio = [
                folder / file for file in ("cover.png", "still.png", "motion.mp4", "music.wav")
            ]
            Image.new("RGB", (64, 64), "yellow").save(cover)
            Image.new("RGB", (64, 64), (0, 255, 0)).save(still)
            self.create_motion(motion)
            with wave.open(str(audio), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(8000)
                stream.writeframes(b"\x00\x00" * 32000)
            updates = []
            target = compose_slideshow(
                [cover, still],
                audio,
                folder / "result.mp4",
                videos={0: motion},
                on_progress=lambda *p: updates.append(p),
            )
            reader = imageio_ffmpeg.read_frames(str(target))
            try:
                info = next(reader)
                pixels = {}
                for index, frame in enumerate(reader):
                    if index in {2, 9, 28, 60}:
                        pixels[index] = Image.frombytes("RGB", info["size"], frame).getpixel(
                            (32, 32)
                        )
                self.assertEqual(info["audio_codec"], "aac")
                self.assertAlmostEqual(info["duration"], 4.0, delta=0.1)
                for index in (2, 28):
                    self.assertGreater(pixels[index][0], 200)
                    self.assertLess(pixels[index][2], 20)
                self.assertGreater(pixels[9][2], 200)
                self.assertGreater(pixels[60][1], 200)
            finally:
                reader.close()
            self.assertEqual(updates[-1], (4.0, 4.0))
            self.assertEqual([p[0] for p in updates], sorted(p[0] for p in updates))
            self.assertFalse(list(folder.glob(".slideshow-*")))

    def test_dynamic_video_without_music_preserves_original_duration(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            cover, motion = folder / "cover.png", folder / "motion.mp4"
            Image.new("RGB", (64, 64), "yellow").save(cover)
            self.create_motion(motion)
            output = compose_slideshow([cover], None, folder / "result.mp4", videos={0: motion})
            reader = imageio_ffmpeg.read_frames(str(output))
            try:
                self.assertAlmostEqual(next(reader)["duration"], 1.0, delta=0.1)
            finally:
                reader.close()

    def test_real_video_with_audio_and_mixed_image_sizes(self):
        with tempfile.TemporaryDirectory(prefix="test's 中文 ") as name:
            folder = Path(name)
            first, second = folder / "red.png", folder / "green.png"
            Image.new("RGB", (101, 151), "red").save(first)
            Image.new("RGB", (200, 100), "green").save(second)
            audio = folder / "music.wav"
            with wave.open(str(audio), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(8000)
                stream.writeframes(b"\x00\x00" * 8000)
            updates = []
            target = compose_slideshow(
                [first, second],
                audio,
                folder / "result.mp4",
                on_progress=lambda *p: updates.append(p),
            )
            reader = imageio_ffmpeg.read_frames(str(target))
            try:
                info = next(reader)
                frame = next(reader)
                self.assertEqual(info["codec"], "h264")
                self.assertEqual(info["audio_codec"], "aac")
                self.assertEqual(info["size"], (100, 150))
                self.assertAlmostEqual(info["duration"], 1.0, delta=0.1)
                self.assertTrue(any(frame))
            finally:
                reader.close()
            self.assertEqual(updates[-1], (1.0, 1.0))
            self.assertFalse(list(folder.glob(".slideshow-*")))

    def test_cancel_does_not_replace_existing_video(self):
        with tempfile.TemporaryDirectory() as name:
            image = Path(name) / "photo.png"
            target = Path(name) / "result.mp4"
            Image.new("RGB", (20, 20)).save(image)
            target.write_bytes(b"original")
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(DownloadCancelled):
                compose_slideshow([image], None, target, cancel=cancel)
            self.assertEqual(target.read_bytes(), b"original")


class ServiceTests(unittest.TestCase):
    def test_rejected_cached_image_is_not_reused(self):
        with (
            patch(
                "douyin_downloader.application.service.capture_content",
                return_value=(self.content, []),
            ),
            patch(
                "douyin_downloader.application.service.download_asset", side_effect=self.write_photo
            ),
            patch(
                "douyin_downloader.infrastructure.assets.validation_path",
                return_value=self.folder / "validation.json",
            ),
        ):
            first = run_download(self.options)
            record_rejected_asset(first.files[0], "Embedded mark verified.")
            with self.assertRaisesRegex(DownloadError, "Known watermarked"):
                run_download(self.options)

    def test_dynamic_download_failure_is_not_static_success(self):
        self.content.image_videos = {0: ("https://example/motion",)}

        def transfer(addresses, path, cookies, kind, *_):
            if kind == "video":
                raise DownloadError("motion stream failed")
            return self.write_photo(addresses, path)

        with (
            patch(
                "douyin_downloader.application.service.capture_content",
                return_value=(self.content, []),
            ),
            patch("douyin_downloader.application.service.download_asset", side_effect=transfer),
            patch("douyin_downloader.application.service.compose_slideshow") as compose,
        ):
            with self.assertRaisesRegex(DownloadError, "Motion cannot be preserved"):
                run_download(self.options)
            compose.assert_not_called()

    def test_static_cache_is_regenerated_when_motion_is_discovered(self):
        def transfer(addresses, path, cookies, kind, *_):
            if kind == "video":
                path.write_bytes(b"motion data")
                return path
            return self.write_photo(addresses, path)

        def compose(images, music, output, *_, **kwargs):
            output.write_bytes(b"exported video")
            return output

        with (
            patch(
                "douyin_downloader.application.service.capture_content",
                return_value=(self.content, []),
            ),
            patch("douyin_downloader.application.service.download_asset", side_effect=transfer),
            patch(
                "douyin_downloader.application.service.compose_slideshow", side_effect=compose
            ) as renderer,
        ):
            run_download(self.options)
            self.content.image_videos = {0: ("https://example/motion",)}
            result = run_download(self.options)
            self.assertEqual(renderer.call_count, 2)
            self.assertIn(0, renderer.call_args.kwargs["videos"])
            self.assertTrue(any(path.name == "live_001.mp4" for path in result.files))

    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.folder = Path(self.workspace.name)
        self.content = Content("123", "title", "author", images=[("https://example/photo",)])
        self.options = DownloadOptions("https://www.douyin.com/note/123", self.folder)

    def write_photo(self, urls, path, *_):
        target = path.with_suffix(".png")
        Image.new("RGB", (20, 30), "red").save(target)
        return target

    def test_photo_both_exports_and_verified_cache(self):
        with (
            patch(
                "douyin_downloader.application.service.capture_content",
                return_value=(self.content, []),
            ),
            patch(
                "douyin_downloader.application.service.download_asset", side_effect=self.write_photo
            ) as download,
        ):
            first = run_download(self.options)
            self.assertEqual([p.suffix for p in first.files], [".png", ".mp4"])
            self.assertTrue(first.warnings)
            second = run_download(self.options)
            self.assertEqual(first.files, second.files)
            self.assertEqual(download.call_count, 1)
            first.files[0].write_bytes(b"damaged")
            run_download(self.options)
            self.assertEqual(download.call_count, 2)

    def test_export_failure_keeps_originals_and_incomplete_state(self):
        with (
            patch(
                "douyin_downloader.application.service.capture_content",
                return_value=(self.content, []),
            ),
            patch(
                "douyin_downloader.application.service.download_asset", side_effect=self.write_photo
            ),
            patch(
                "douyin_downloader.application.service.compose_slideshow",
                side_effect=DownloadError("export failed"),
            ),
        ):
            with self.assertRaisesRegex(DownloadError, "export failed"):
                run_download(self.options)
        metadata = json.loads(next(self.folder.rglob("metadata.json")).read_text(encoding="utf-8"))
        self.assertEqual(metadata["state"], "in_progress")
        self.assertEqual(len(metadata["files"]), 1)
        self.assertTrue(next(self.folder.rglob("*.png")).is_file())

    def test_change_slide_duration_regenerates_video(self):
        with (
            patch(
                "douyin_downloader.application.service.capture_content",
                return_value=(self.content, []),
            ),
            patch(
                "douyin_downloader.application.service.download_asset", side_effect=self.write_photo
            ),
            patch(
                "douyin_downloader.application.service.compose_slideshow", wraps=compose_slideshow
            ) as compose,
        ):
            run_download(DownloadOptions(self.options.link, self.folder, slide_seconds=0.2))
            run_download(DownloadOptions(self.options.link, self.folder, slide_seconds=0.4))
            self.assertEqual(compose.call_count, 2)

    def test_legacy_cache_is_not_reused_after_watermark_policy_change(self):
        with (
            patch(
                "douyin_downloader.application.service.capture_content",
                return_value=(self.content, []),
            ),
            patch(
                "douyin_downloader.application.service.download_asset", side_effect=self.write_photo
            ) as download,
        ):
            run_download(self.options)
            path = next(self.folder.rglob("metadata.json"))
            metadata = json.loads(path.read_text(encoding="utf-8"))
            metadata.pop("source_policy")
            path.write_text(json.dumps(metadata), encoding="utf-8")
            run_download(self.options)
            self.assertEqual(download.call_count, 2)
