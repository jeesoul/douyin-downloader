from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

StatusCallback = Callable[[str], None]
TransferCallback = Callable[[int, int, float], None]
ExportCallback = Callable[[float, float], None]


class DownloadError(RuntimeError):
    pass


class DownloadCancelled(DownloadError):
    pass


@dataclass(frozen=True)
class ResolvedLink:
    aweme_id: str
    kind: Literal["video", "note"] = "video"

    @property
    def page_url(self) -> str:
        return f"https://www.douyin.com/{self.kind}/{self.aweme_id}"


@dataclass(frozen=True)
class Quality:
    name: str
    bitrate: int
    urls: tuple[str, ...]


@dataclass
class Content:
    aweme_id: str
    title: str
    author: str
    qualities: list[Quality] = field(default_factory=list)
    images: list[tuple[str, ...]] = field(default_factory=list)
    image_videos: dict[int, tuple[str, ...]] = field(default_factory=dict)
    music_urls: tuple[str, ...] = ()
    music_duration: float = 0

    @property
    def kind(self) -> str:
        return "note" if self.images else "video"


@dataclass(frozen=True)
class DownloadOptions:
    link: str
    output_dir: Path
    quality: str | None = None
    photo_mode: Literal["both", "originals"] = "both"
    slide_seconds: float = 3.0
    show_browser: bool = False


@dataclass
class DownloadResult:
    files: list[Path]
    warnings: list[str] = field(default_factory=list)
