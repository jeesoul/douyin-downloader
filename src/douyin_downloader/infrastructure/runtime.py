import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from ..domain.models import DownloadCancelled, DownloadError


def app_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()


def check_cancel(cancel: threading.Event | None):
    if cancel and cancel.is_set():
        raise DownloadCancelled("Cancelled.")


def redact(message: str) -> str:
    return re.sub(r"https?://[^\s'\"]+", "<url>", message)


def setup_logging() -> Path:
    from logging.handlers import RotatingFileHandler

    base = app_dir() / "logs"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path(tempfile.gettempdir()) / "douyin-downloader" / "logs"
        base.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("douyin_downloader")
    if not logger.handlers:
        handler = RotatingFileHandler(
            base / "downloader.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return base / "downloader.log"


def run_process(command: list[str], cancel=None, on_line=None, env=None) -> str:
    check_cancel(cancel)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    lines = []
    messages = queue.Queue()
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
            env=env,
        )

        def read_output():
            for line in process.stdout:
                messages.put(line)
            messages.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            ended = False
            while not ended:
                check_cancel(cancel)
                try:
                    line = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    ended = True
                else:
                    lines.append(line)
                    if on_line:
                        on_line(line.strip())
            process.wait()
            if process.returncode:
                errors.seek(0)
                message = errors.read().decode("utf-8", errors="replace")[-1800:]
                raise DownloadError(f"Command failed ({process.returncode}): {redact(message)}")
            return "".join(lines)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            reader.join(timeout=3)
            process.stdout.close()


def ensure_browser(cancel=None, on_status=lambda _: None):
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    from playwright.sync_api import sync_playwright

    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        if sys.platform == "win32":
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(
                Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
            )
        elif sys.platform == "darwin":
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(
                Path.home() / "Library" / "Caches" / "ms-playwright"
            )
        else:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path.home() / ".cache" / "ms-playwright")
    check_cancel(cancel)
    with sync_playwright() as p:
        present = Path(p.chromium.executable_path).is_file()
    if not present:
        on_status("Downloading Chromium browser...")
        node, cli = compute_driver_executable()
        # 打包后 sys.executable 是本程序，必须调用随包携带的 Node 安装浏览器。
        run_process([node, cli, "install", "chromium"], cancel, env=get_driver_env())
    check_cancel(cancel)
