import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from douyin_downloader.domain.models import DownloadCancelled, DownloadError, DownloadOptions
from douyin_downloader.presentation import cli


class CliTests(unittest.TestCase):
    def test_windowed_mode_opens_gui_before_network(self):
        with (
            patch.object(cli.sys, "stdout", None),
            patch("douyin_downloader.presentation.gui.launch_gui", return_value=1) as gui,
            patch("douyin_downloader.application.service.run_download") as network,
        ):
            self.assertEqual(cli.main(["invalid link"]), 1)
            gui.assert_called_once()
            network.assert_not_called()


@unittest.skipUnless(os.environ.get("RUN_GUI_TESTS") == "1", "Enable RUN_GUI_TESTS=1 on a desktop")
class GuiTests(unittest.TestCase):
    def test_responsive_error_remains_visible_and_no_worker_tk_calls(self):
        import tkinter as tk

        from douyin_downloader.presentation.gui import DownloaderApp

        with tempfile.TemporaryDirectory() as name:
            root = tk.Tk()
            calls = []
            ticks = []

            def runner(options, cancel, status, progress, export):
                calls.append(threading.get_ident())
                status("Resolving...")
                time.sleep(0.3)
                raise DownloadError("network unavailable")

            app = DownloaderApp(
                root, DownloadOptions("test", Path(name)), Path(name) / "log", runner
            )
            root.after(150, lambda: ticks.append(time.monotonic()))
            errors = []
            root.report_callback_exception = lambda *args: errors.append(args)

            def verify():
                try:
                    self.assertTrue(ticks)
                    self.assertNotEqual(calls[0], threading.get_ident())
                    self.assertEqual(app.status.cget("text"), "Download failed")
                    self.assertIn("network unavailable", app.detail.get("1.0", "end"))
                    self.assertEqual(app.download_button.cget("text"), "Retry")
                except AssertionError as exc:
                    errors.append(exc)
                finally:
                    root.destroy()

            root.after(3700, verify)
            root.mainloop()
            app.worker.join()
            self.assertFalse(errors)

    def test_window_close_cancels_and_joins_worker(self):
        import tkinter as tk

        from douyin_downloader.presentation.gui import DownloaderApp

        with tempfile.TemporaryDirectory() as name:
            root = tk.Tk()
            cancelled = threading.Event()

            def runner(options, cancel, *_):
                cancel.wait(timeout=2)
                cancelled.set()
                raise DownloadCancelled()

            app = DownloaderApp(
                root, DownloadOptions("test", Path(name)), Path(name) / "log", runner
            )
            root.after(200, app.close)
            root.mainloop()
            app.worker.join(timeout=3)
            self.assertTrue(cancelled.is_set())
            self.assertFalse(app.worker.is_alive())
