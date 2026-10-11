import argparse
import logging
import sys
from pathlib import Path

from .. import __version__
from ..domain.models import (
    DownloadCancelled,
    DownloadOptions,
    DynamicSourceUnavailable,
    MediaRejectedError,
)
from ..infrastructure.runtime import app_dir, redact, setup_logging


def main(argv=None) -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if stream and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Douyin Material Downloader - dxy")
    parser.add_argument("link", nargs="?", help="Douyin share link or text")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--gui", action="store_true", help="Open the desktop window")
    parser.add_argument("--show", action="store_true", help="Show the browser for verification")
    parser.add_argument("--quality", help="Quality keyword: 1080 / 720 / 540 / hdr")
    parser.add_argument("--output", type=Path, default=app_dir() / "downloads")
    parser.add_argument("--photo-mode", choices=["both", "originals"], default="both")
    parser.add_argument(
        "--slide-seconds",
        type=float,
        default=3.0,
        help="Seconds per photo when music is unavailable",
    )
    args = parser.parse_args(argv)
    options = DownloadOptions(
        link=args.link or "",
        output_dir=args.output.resolve(),
        quality=args.quality,
        photo_mode=args.photo_mode,
        slide_seconds=args.slide_seconds,
        show_browser=args.show,
    )
    log_path = setup_logging()
    try:
        # 先创建 GUI 再做任何网络操作，避免 windowed 模式出现不可见的失败。
        if args.gui or not args.link or sys.stdout is None:
            from .gui import launch_gui

            return launch_gui(options, log_path)
        from ..application.service import run_download

        def status(message):
            print(f"[*] {message}", flush=True)

        def progress(written, total, elapsed):
            size = (
                f"{written / 1048576:.1f}/{total / 1048576:.1f}"
                if total
                else f"{written / 1048576:.1f}"
            )
            print(
                f"\r    {size} MB  {written / max(elapsed, 0.001) / 1048576:.2f} MB/s    ",
                end="",
                flush=True,
            )

        result = run_download(options, on_status=status, on_progress=progress)
        print()
        for path in result.files:
            print(f"[OK] {path}")
        for warning in result.warnings:
            print(f"[!] {warning}")
        return 2 if result.unavailable_motion else 0
    except (KeyboardInterrupt, DownloadCancelled):
        return 130
    except (DynamicSourceUnavailable, MediaRejectedError) as exc:
        message = redact(str(exc))
        rejected = isinstance(exc, MediaRejectedError) or exc.policy_rejected
        logging.getLogger(__name__).warning("%s: %s", type(exc).__name__, message)
        print(f"\n[{'REJECTED' if rejected else 'INCOMPLETE'}] {message}", file=sys.stderr)
        for path in getattr(exc, "files", ()):
            print(f"[SAVED] {path}")
        return 3 if rejected else 1
    except Exception as exc:
        message = redact(str(exc))
        logging.getLogger(__name__).error("%s: %s", type(exc).__name__, message)
        if sys.stdout is None:
            from tkinter import messagebox

            messagebox.showerror("Douyin Material Downloader", f"{message}\n\nLog: {log_path}")
        else:
            print(f"\n[!] {message}\nLog: {log_path}", file=sys.stderr)
        return 1
