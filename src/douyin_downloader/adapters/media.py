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
) -> Path:
    """按实际配乐时长均分图片轮播；无配乐时使用每张图片的指定时长。"""
    if not images:
        raise DownloadError("No images available for video export.")
    if slide_seconds <= 0:
        raise DownloadError("Slide duration must be greater than zero.")
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
