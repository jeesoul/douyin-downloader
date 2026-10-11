import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..adapters.douyin.browser import capture_content
from ..adapters.douyin.links import resolve_link
from ..adapters.media import compose_slideshow
from ..adapters.transfer import download_asset, safe_name
from ..domain.models import (
    DownloadCancelled,
    DownloadError,
    DownloadOptions,
    DownloadResult,
    ExportCallback,
    StatusCallback,
    TransferCallback,
)
from ..infrastructure.assets import require_accepted_asset, sha256
from ..infrastructure.ffmpeg import ensure_ffmpeg
from ..infrastructure.runtime import check_cancel, redact

LOGGER = logging.getLogger(__name__)
SOURCE_POLICY = "watermark-free-1"


def save_metadata(path: Path, data: dict):
    descriptor, name = tempfile.mkstemp(prefix=".metadata-", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.remove(name)


def run_download(
    options: DownloadOptions,
    cancel: threading.Event | None = None,
    on_status: StatusCallback = lambda _: None,
    on_progress: TransferCallback = lambda *_: None,
    on_export: ExportCallback = lambda *_: None,
) -> DownloadResult:
    """编排解析、下载与图文导出；UI 只接收状态回调，失败保留已校验的素材。"""
    if options.photo_mode not in {"both", "originals"}:
        raise DownloadError("Unsupported photo export mode.")
    if options.slide_seconds <= 0:
        raise DownloadError("Slide duration must be greater than zero.")
    check_cancel(cancel)
    on_status("Parsing share link...")
    resolved = resolve_link(options.link)
    check_cancel(cancel)
    content, cookies = capture_content(resolved, options.show_browser, cancel, on_status)
    check_cancel(cancel)
    folder = (
        options.output_dir
        / f"{safe_name(content.author + '_' + content.title, 60)}_{content.aweme_id}"
    )
    folder.mkdir(parents=True, exist_ok=True)
    metadata_path = folder / "metadata.json"
    previous = {}
    prior_metadata = {}
    if metadata_path.is_file():
        try:
            prior_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(prior_metadata, dict):
                prior_metadata = {}
            if prior_metadata.get("source_policy") == SOURCE_POLICY:
                previous = {
                    item["name"]: item
                    for item in prior_metadata.get("files", [])
                    if isinstance(item, dict) and isinstance(item.get("name"), str)
                }
        except (ValueError, KeyError, TypeError):
            pass
    files = []
    warnings = []
    metadata = {
        "version": __version__,
        "aweme_id": content.aweme_id,
        "kind": content.kind,
        "title": content.title,
        "author": content.author,
        "files": list(previous.values()),
        "warnings": warnings,
        "state": "in_progress",
        "source_policy": SOURCE_POLICY,
    }
    save_metadata(metadata_path, metadata)

    def complete():
        check_cancel(cancel)
        metadata["state"] = "completed"
        metadata["warnings"] = warnings
        save_metadata(metadata_path, metadata)
        return DownloadResult(files, warnings)

    def remember(path: Path):
        if path not in files:
            files.append(path)
        record = {"name": path.name, "size": path.stat().st_size, "sha256": sha256(path)}
        metadata["files"] = [entry for entry in metadata["files"] if entry["name"] != path.name] + [
            record
        ]
        metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_metadata(metadata_path, metadata)
        return path

    def cached(stem: str) -> Path | None:
        for name, record in previous.items():
            if Path(name).name != name or Path(name).stem != stem:
                continue
            candidate = folder / name
            if (
                candidate.is_file()
                and candidate.stat().st_size == record.get("size")
                and sha256(candidate) == record.get("sha256")
            ):
                require_accepted_asset(record["sha256"])
                return remember(candidate)
        return None

    def obtain(addresses, stem, suffix, kind):
        check_cancel(cancel)
        result = cached(stem)
        if result:
            on_status(f"Already downloaded: {result.name}")
            return result
        on_status(f"Downloading {stem}...")
        return remember(
            download_asset(addresses, folder / (stem + suffix), cookies, kind, cancel, on_progress)
        )

    if content.kind == "video":
        targets = content.qualities
        if options.quality:
            matching = [q for q in targets if options.quality.lower() in q.name.lower()]
            if matching:
                targets = matching
            else:
                warnings.append(
                    f"Requested quality {options.quality} is unavailable; using the best available stream."
                )
        errors = []
        for quality in targets:
            try:
                obtain(quality.urls, "video_" + safe_name(quality.name), ".mp4", "video")
                return complete()
            except DownloadCancelled:
                raise
            except DownloadError as exc:
                errors.append(redact(str(exc)))
        raise DownloadError(errors[-1] if errors else "No downloadable video stream.")

    images = [
        obtain(addresses, f"image_{index + 1:03d}", ".image", "image")
        for index, addresses in enumerate(content.images)
    ]
    image_videos = {}
    for index, addresses in content.image_videos.items():
        try:
            image_videos[index] = obtain(addresses, f"live_{index + 1:03d}", ".mp4", "video")
        except DownloadCancelled:
            raise
        except DownloadError as exc:
            raise DownloadError(
                f"Dynamic photo {index + 1} failed: {redact(str(exc))}. "
                "Motion cannot be preserved without its video stream."
            ) from exc
    music = None
    if content.music_urls:
        try:
            music = obtain(content.music_urls, "music", ".mp3", "audio")
        except DownloadCancelled:
            raise
        except DownloadError as exc:
            warnings.append(f"Music could not be downloaded: {redact(str(exc))}")
    else:
        warnings.append("No downloadable background music is available for this post.")
    if options.photo_mode == "both":
        ensure_ffmpeg(cancel, on_status, on_progress)
        on_status("Exporting photo slideshow...")
        # 原图和配乐先落盘，合成失败时保留素材并允许重试，绝不把静音导出伪装成完整成功。
        stem = "slideshow" if music else "slideshow_silent"
        inputs = {
            "images": [sha256(image) for image in images],
            "motion": {str(index): sha256(video) for index, video in image_videos.items()},
            "audio": sha256(music) if music else None,
            "slide_seconds": options.slide_seconds,
            "version": __version__,
        }
        output = cached(stem) if prior_metadata.get("export_inputs") == inputs else None
        if not output:
            remember(
                compose_slideshow(
                    images,
                    music,
                    folder / (stem + ".mp4"),
                    options.slide_seconds,
                    cancel,
                    on_export,
                    videos=image_videos,
                )
            )
        metadata["export_inputs"] = inputs
    return complete()
