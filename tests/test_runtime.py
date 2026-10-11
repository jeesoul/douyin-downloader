import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from douyin_downloader.domain.models import DownloadCancelled, DownloadError
from douyin_downloader.infrastructure.ffmpeg import WHEEL_NAME, ensure_ffmpeg
from douyin_downloader.infrastructure.runtime import ensure_browser, run_process


class RuntimeTests(unittest.TestCase):
    def test_frozen_browser_installer_calls_bundled_node(self):
        context = MagicMock()
        context.__enter__.return_value.chromium.executable_path = "missing-required-browser"
        with (
            patch("playwright.sync_api.sync_playwright", return_value=context),
            patch(
                "playwright._impl._driver.compute_driver_executable",
                return_value=("node.exe", "cli.js"),
            ),
            patch("douyin_downloader.infrastructure.runtime.run_process") as execute,
        ):
            ensure_browser()
            self.assertEqual(
                execute.call_args.args[0], ["node.exe", "cli.js", "install", "chromium"]
            )

    def test_cancel_terminates_and_reaps_subprocess(self):
        cancel = threading.Event()
        timer = threading.Timer(0.2, cancel.set)
        timer.start()
        try:
            with self.assertRaises(DownloadCancelled):
                run_process([sys.executable, "-c", "import time; time.sleep(30)"], cancel)
        finally:
            timer.join()

    def wheel_responses(self, expected_checksum=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("imageio_ffmpeg/binaries/ffmpeg.exe", b"test ffmpeg payload")
        payload = output.getvalue()
        metadata = MagicMock()
        metadata.__enter__.return_value = metadata
        metadata.json.return_value = {
            "urls": [
                {
                    "filename": WHEEL_NAME,
                    "url": "https://files.pythonhosted.org/test.whl",
                    "digests": {"sha256": expected_checksum or hashlib.sha256(payload).hexdigest()},
                }
            ]
        }
        binary = MagicMock()
        binary.__enter__.return_value = binary
        binary.headers = {"Content-Length": str(len(payload))}
        binary.iter_content.return_value = [payload]
        return [metadata, binary]

    def test_ffmpeg_download_is_checked_and_cached(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(sys, "frozen", True, create=True),
            patch.dict(os.environ, {"LOCALAPPDATA": directory}),
        ):
            os.environ.pop("IMAGEIO_FFMPEG_EXE", None)
            with patch(
                "douyin_downloader.infrastructure.ffmpeg.requests.get",
                side_effect=self.wheel_responses(),
            ) as request:
                ensure_ffmpeg()
                cached = Path(os.environ["IMAGEIO_FFMPEG_EXE"])
                self.assertEqual(cached.read_bytes(), b"test ffmpeg payload")
                os.environ.pop("IMAGEIO_FFMPEG_EXE")
                ensure_ffmpeg()
                self.assertEqual(request.call_count, 2)
                self.assertEqual(
                    json.loads(cached.with_name("manifest.json").read_text())["wheel"], WHEEL_NAME
                )

    def test_ffmpeg_checksum_mismatch_is_not_installed(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(sys, "frozen", True, create=True),
            patch.dict(os.environ, {"LOCALAPPDATA": directory}),
        ):
            os.environ.pop("IMAGEIO_FFMPEG_EXE", None)
            with patch(
                "douyin_downloader.infrastructure.ffmpeg.requests.get",
                side_effect=self.wheel_responses("wrong"),
            ):
                with self.assertRaisesRegex(DownloadError, "checksum"):
                    ensure_ffmpeg()
            self.assertFalse(list(Path(directory).rglob("ffmpeg.exe")))
