import io
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from douyin_downloader.adapters.transfer import download_asset
from douyin_downloader.domain.models import DownloadCancelled, DownloadError

VIDEO = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 180000


class MediaHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/redirect-watermark":
            self.send_response(302)
            self.send_header("Location", "/video.mp4?watermark=1")
            self.end_headers()
            return
        data, media_type = VIDEO, "video/mp4"
        if self.path == "/bad":
            self.send_error(403)
            return
        if self.path == "/html":
            data, media_type = b"<html>not a video</html>", "text/html"
        if self.path == "/photo":
            buffer = io.BytesIO()
            Image.new("RGB", (30, 20), "red").save(buffer, format="WEBP")
            data, media_type = buffer.getvalue(), "image/webp"
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        if self.path != "/unknown":
            self.send_header(
                "Content-Length", len(data) + 100000 if self.path == "/truncated" else len(data)
            )
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionError, OSError):
            pass


class TransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MediaHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.directory = Path(self.workspace.name)

    def test_fallback_and_known_size(self):
        progress = []
        target = self.directory / "video.mp4"
        download_asset(
            [self.base + "/bad", self.base + "/ok"],
            target,
            [],
            on_progress=lambda *p: progress.append(p),
        )
        self.assertEqual(target.read_bytes(), VIDEO)
        self.assertEqual(progress[-1][0:2], (len(VIDEO), len(VIDEO)))
        self.assertFalse(list(self.directory.glob("*.part")))

    def test_unknown_size_still_reports_progress(self):
        updates = []
        download_asset(
            [self.base + "/unknown"],
            self.directory / "video.mp4",
            [],
            on_progress=lambda *p: updates.append(p),
        )
        self.assertEqual(updates[-1][0], len(VIDEO))
        self.assertEqual(updates[-1][1], 0)

    def test_truncated_response_preserves_previous_file(self):
        target = self.directory / "video.mp4"
        target.write_bytes(b"previous complete file")
        with self.assertRaises(DownloadError):
            download_asset([self.base + "/truncated"], target, [])
        self.assertEqual(target.read_bytes(), b"previous complete file")
        self.assertFalse(list(self.directory.glob("*.part")))

    def test_html_is_rejected(self):
        with self.assertRaises(DownloadError):
            download_asset([self.base + "/html"], self.directory / "video.mp4", [])
        self.assertFalse((self.directory / "video.mp4").exists())

    def test_watermarked_candidate_and_redirect_are_rejected(self):
        for address in [self.base + "/video.mp4?watermark=1", self.base + "/redirect-watermark"]:
            with self.subTest(address=address), self.assertRaises(DownloadError):
                download_asset([address], self.directory / "video.mp4", [])
        self.assertFalse((self.directory / "video.mp4").exists())

    def test_original_photo_extension(self):
        output = download_asset(
            [self.base + "/photo"], self.directory / "image_001.image", [], kind="image"
        )
        self.assertEqual(output.suffix, ".webp")
        with Image.open(output) as image:
            self.assertEqual(image.size, (30, 20))

    def test_cancel_during_transfer_cleans_temporary_file(self):
        cancel = threading.Event()

        def update(written, *_):
            if written:
                cancel.set()

        with self.assertRaises(DownloadCancelled):
            download_asset(
                [self.base + "/ok"],
                self.directory / "video.mp4",
                [],
                cancel=cancel,
                on_progress=update,
            )
        self.assertEqual(list(self.directory.iterdir()), [])
