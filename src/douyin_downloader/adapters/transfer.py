import os
import re
import tempfile
import threading
import time
from pathlib import Path

import requests

from ..domain.models import DownloadCancelled, DownloadError, MediaRejectedError, TransferCallback
from ..infrastructure.assets import require_accepted_asset, sha256
from ..infrastructure.runtime import check_cancel, redact
from .douyin.addresses import is_watermarked_url
from .douyin.links import USER_AGENT


def safe_name(text: str, limit=80) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f#]', "", str(text))
    value = re.sub(r"\s+", " ", value).strip().rstrip(" .")[:limit].rstrip(" .") or "douyin"
    if value.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        value = "_" + value
    return value


def download_asset(
    urls: tuple[str, ...] | list[str],
    destination: Path,
    cookies: list[dict],
    kind: str = "video",
    cancel: threading.Event | None = None,
    on_progress: TransferCallback = lambda *_: None,
) -> Path:
    """依次尝试无水印地址；响应和完整性校验通过后才替换正式文件。"""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.douyin.com/", "Accept": "*/*"}
    if cookies:
        headers["Cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    failures = []
    rejections = []
    for url in urls:
        check_cancel(cancel)
        if is_watermarked_url(url):
            rejections.append("Watermarked media address rejected.")
            continue
        temporary = None
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(10, 30)) as response:
                response.raise_for_status()
                if is_watermarked_url(response.url):
                    raise MediaRejectedError("Redirected to a watermarked media address.")
                media_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if media_type.startswith("text/") or "json" in media_type:
                    raise DownloadError("The server returned a page instead of media.")
                total = int(response.headers.get("Content-Length") or 0)
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    total = 0
                # 每次尝试独占一个临时文件，避免失败、取消和并发任务污染正式输出。
                descriptor, name = tempfile.mkstemp(
                    prefix=".download-", suffix=".part", dir=destination.parent
                )
                temporary = Path(name)
                written = 0
                started = time.monotonic()
                last_update = 0
                on_progress(0, total, 0)
                with os.fdopen(descriptor, "wb") as stream:
                    for chunk in response.iter_content(65536):
                        check_cancel(cancel)
                        if chunk:
                            stream.write(chunk)
                            written += len(chunk)
                            now = time.monotonic()
                            if now - last_update >= 0.2:
                                on_progress(written, total, now - started)
                                last_update = now
                check_cancel(cancel)
                if not written or (total and written != total):
                    raise DownloadError(f"Incomplete download ({written}/{total} bytes).")
                # 地址看起来无水印并不代表画面干净，已核验的不合格文件不能作为兜底。
                require_accepted_asset(sha256(temporary))
                if kind == "image":
                    from PIL import Image

                    with Image.open(temporary) as image:
                        image.verify()
                        extension = {
                            "JPEG": ".jpg",
                            "PNG": ".png",
                            "WEBP": ".webp",
                            "GIF": ".gif",
                            "AVIF": ".avif",
                        }.get(image.format)
                    if not extension:
                        raise DownloadError("Unsupported image format.")
                    target = destination.with_suffix(extension)
                elif kind == "audio":
                    target = destination.with_suffix(
                        {
                            "audio/mp4": ".m4a",
                            "audio/aac": ".aac",
                            "audio/x-wav": ".wav",
                            "audio/wav": ".wav",
                            "audio/ogg": ".ogg",
                        }.get(media_type, ".mp3")
                    )
                else:
                    with temporary.open("rb") as stream:
                        header = stream.read(64)
                    if b"ftyp" not in header:
                        raise DownloadError("The server did not return an MP4 video.")
                    target = destination
                os.replace(temporary, target)
                on_progress(written, total, time.monotonic() - started)
                return target
        except DownloadCancelled:
            raise
        except MediaRejectedError as exc:
            rejections.append(redact(str(exc)))
        except (requests.RequestException, OSError, ValueError, DownloadError) as exc:
            failures.append(f"{type(exc).__name__}: {redact(str(exc))}")
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
    if rejections and not failures:
        raise MediaRejectedError(rejections[-1])
    reason = failures[-1] if failures else "No downloadable addresses."
    raise DownloadError(f"All {len(urls)} media addresses failed. {reason}")
