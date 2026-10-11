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


class MediaTests(unittest.TestCase):
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
