import os
import tempfile
import threading
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageOps

from ..domain.models import DownloadError, ExportCallback
from ..infrastructure.runtime import check_cancel, run_process


def audio_duration(path: Path, cancel=None) -> float:
    values = {}

    def update(line):
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value

    run_process(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-sn",
            "-f",
            "null",
            "-",
            "-progress",
            "pipe:1",
            "-nostats",
        ],
        cancel,
        update,
    )
    duration = float(values.get("out_time_us", 0)) / 1_000_000
    if duration <= 0:
        raise DownloadError("Cannot determine music duration.")
    return duration


def compose_slideshow(
    images: list[Path],
    audio: Path | None,
    destination: Path,
    slide_seconds: float = 3.0,
    cancel: threading.Event | None = None,
    on_progress: ExportCallback = lambda *_: None,
    *,
    videos: dict[int, Path] | None = None,
) -> Path:
    """导出图文；有配乐时均分展示时长，动态图片使用原视频流循环播放。"""
    if not images:
        raise DownloadError("No images available for video export.")
    if slide_seconds <= 0:
        raise DownloadError("Slide duration must be greater than zero.")
    if videos:
        if any(index < 0 or index >= len(images) for index in videos):
            raise DownloadError("Dynamic photo index is out of range.")
        return _compose_motion_slideshow(
            images, videos, audio, destination, slide_seconds, cancel, on_progress
        )
    duration = audio_duration(audio, cancel) if audio else len(images) * slide_seconds
    seconds_per_image = duration / len(images)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".slideshow-", dir=destination.parent) as workspace:
        workspace = Path(workspace)
        with Image.open(images[0]) as first:
            size = ImageOps.exif_transpose(first).size
        factor = min(1.0, 1080 / size[0], 1920 / size[1])
        width = max(2, int(size[0] * factor) // 2 * 2)
        height = max(2, int(size[1] * factor) // 2 * 2)
        normalized = []
        for index, source in enumerate(images):
            check_cancel(cancel)
            with Image.open(source) as image:
                frame = ImageOps.contain(
                    ImageOps.exif_transpose(image).convert("RGB"), (width, height)
                )
                canvas = Image.new("RGB", (width, height), "black")
                canvas.paste(frame, ((width - frame.width) // 2, (height - frame.height) // 2))
                filename = workspace / f"{index:04d}.png"
                canvas.save(filename)
                normalized.append(filename)
        # 使用相对且可控的文件名，避开 Windows 路径、中文和单引号的 concat 转义问题。
        listing = workspace / "slides.txt"
        listing.write_text(
            "".join(f"file '{p.name}'\nduration {seconds_per_image:.8f}\n" for p in normalized)
            + f"file '{normalized[-1].name}'\n",
            encoding="utf-8",
        )
        temporary = workspace / "output.mp4"
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
        ]
        if audio:
            command += [
                "-i",
                str(audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
            ]
        command += [
            "-t",
            f"{duration:.8f}",
            "-vf",
            "fps=25",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(temporary),
        ]

        def update(line):
            key, separator, value = line.partition("=")
            if separator and key == "out_time_us":
                on_progress(max(0, float(value) / 1_000_000), duration)

        on_progress(0, duration)
        run_process(command, cancel, update)
        check_cancel(cancel)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise DownloadError("Video export produced an empty file.")
        os.replace(temporary, destination)
        on_progress(duration, duration)
    return destination


def _video_duration(path: Path) -> float:
    reader = imageio_ffmpeg.read_frames(str(path))
    try:
        duration = float(next(reader).get("duration") or 0)
    finally:
        reader.close()
    if duration <= 0:
        raise DownloadError("Dynamic photo video has no valid duration.")
    return duration


def _compose_motion_slideshow(
    images: list[Path],
    videos: dict[int, Path],
    audio: Path | None,
    destination: Path,
    slide_seconds: float,
    cancel: threading.Event | None,
    on_progress: ExportCallback,
) -> Path:
    """统一片段编码后拼接；动态短片只循环画面，整段配乐在最后单独封装。"""
    check_cancel(cancel)
    if audio:
        duration = audio_duration(audio, cancel)
        durations = [duration / len(images)] * len(images)
    else:
        durations = [
            _video_duration(videos[index]) if index in videos else slide_seconds
            for index in range(len(images))
        ]
        duration = sum(durations)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(images[0]) as first:
        width, height = ImageOps.exif_transpose(first).size
    factor = min(1.0, 1080 / width, 1920 / height)
    width = max(2, int(width * factor) // 2 * 2)
    height = max(2, int(height * factor) // 2 * 2)
    geometry = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25,format=yuv420p"
    )
    on_progress(0, duration)
    with tempfile.TemporaryDirectory(prefix=".slideshow-", dir=destination.parent) as folder:
        workspace = Path(folder)
        parts = []
        elapsed = 0.0
        for index, seconds in enumerate(durations):
            check_cancel(cancel)
            command = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error"]
            if index in videos:
                command += ["-stream_loop", "-1", "-i", str(videos[index])]
            else:
                source = workspace / f"image-{index:04d}.png"
                with Image.open(images[index]) as image:
                    ImageOps.exif_transpose(image).convert("RGB").save(source)
                command += ["-loop", "1", "-i", str(source)]
            part = workspace / f"part-{index:04d}.mp4"
            command += [
                "-an",
                "-t",
                f"{seconds:.8f}",
                "-vf",
                geometry,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-progress",
                "pipe:1",
                "-nostats",
                str(part),
            ]

            def segment_progress(line, offset=elapsed, length=seconds):
                key, separator, value = line.partition("=")
                if separator and key == "out_time_us":
                    current = max(0, min(length, float(value) / 1_000_000))
                    on_progress((offset + current) * 0.9, duration)

            run_process(command, cancel, segment_progress)
            elapsed += seconds
            on_progress(elapsed * 0.9, duration)
            parts.append(part)
        # concat 文件名完全由本程序生成，各片段尺寸、帧率及编码一致。
        listing = workspace / "parts.txt"
        listing.write_text("".join(f"file '{part.name}'\n" for part in parts), encoding="utf-8")
        temporary = workspace / "output.mp4"
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
        ]
        if audio:
            command += ["-i", str(audio)]
        command += ["-map", "0:v:0", "-c:v", "copy"]
        if audio:
            command += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
        command += [
            "-t",
            f"{duration:.8f}",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(temporary),
        ]

        def finish_progress(line):
            key, separator, value = line.partition("=")
            if separator and key == "out_time_us":
                current = max(0, min(duration, float(value) / 1_000_000))
                on_progress(duration * 0.9 + current * 0.1, duration)

        run_process(command, cancel, finish_progress)
        check_cancel(cancel)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise DownloadError("Dynamic video export produced an empty file.")
        os.replace(temporary, destination)
        on_progress(duration, duration)
    return destination
