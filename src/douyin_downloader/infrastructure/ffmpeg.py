"""FFmpeg 独立下载与缓存；发布包不重分发 GPL 编码器二进制。"""

import hashlib
import json
import os
import tempfile
import time
import zipfile
from pathlib import Path

import requests

from ..domain.models import DownloadError
from .runtime import check_cancel

WHEEL_NAME = "imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl"
PACKAGE_API = "https://pypi.org/pypi/imageio-ffmpeg/0.6.0/json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_ffmpeg(cancel=None, on_status=lambda _: None, on_progress=lambda *_: None):
    import sys

    if not getattr(sys, "frozen", False) or os.environ.get("IMAGEIO_FFMPEG_EXE"):
        return
    cache = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "douyin-downloader" / "ffmpeg"
    executable = cache / "ffmpeg.exe"
    manifest = cache / "manifest.json"
    if executable.is_file() and manifest.is_file():
        try:
            record = json.loads(manifest.read_text(encoding="utf-8"))
            if record.get("wheel") == WHEEL_NAME and record.get("sha256") == _sha256(executable):
                os.environ["IMAGEIO_FFMPEG_EXE"] = str(executable)
                return
        except (OSError, ValueError):
            pass
    check_cancel(cancel)
    on_status("Downloading FFmpeg (~31 MB)...")
    cache.mkdir(parents=True, exist_ok=True)
    with requests.get(PACKAGE_API, timeout=(10, 30)) as response:
        response.raise_for_status()
        package = response.json()
    candidate = next((entry for entry in package["urls"] if entry["filename"] == WHEEL_NAME), None)
    if not candidate or not candidate["url"].startswith("https://files.pythonhosted.org/"):
        raise DownloadError("Cannot locate the official FFmpeg runtime package.")
    with tempfile.TemporaryDirectory(prefix=".install-", dir=cache) as directory:
        directory = Path(directory)
        wheel = directory / WHEEL_NAME
        started = time.monotonic()
        with requests.get(candidate["url"], stream=True, timeout=(10, 30)) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            written = 0
            with wheel.open("wb") as stream:
                for chunk in response.iter_content(1 << 20):
                    check_cancel(cancel)
                    stream.write(chunk)
                    written += len(chunk)
                    on_progress(written, total, time.monotonic() - started)
        if _sha256(wheel) != candidate["digests"]["sha256"]:
            raise DownloadError("FFmpeg runtime package checksum mismatch.")
        with zipfile.ZipFile(wheel) as archive:
            binaries = [
                name
                for name in archive.namelist()
                if name.startswith("imageio_ffmpeg/binaries/") and name.endswith(".exe")
            ]
            if len(binaries) != 1:
                raise DownloadError("FFmpeg runtime package has an unexpected layout.")
            temporary = directory / "ffmpeg.exe"
            temporary.write_bytes(archive.read(binaries[0]))
        check_cancel(cancel)
        digest = _sha256(temporary)
        os.replace(temporary, executable)
        record_path = directory / "manifest.json"
        record_path.write_text(
            json.dumps({"wheel": WHEEL_NAME, "sha256": digest}), encoding="utf-8"
        )
        os.replace(record_path, manifest)
    os.environ["IMAGEIO_FFMPEG_EXE"] = str(executable)
