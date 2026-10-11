import json
import re
from collections import deque
from urllib.parse import parse_qs, unquote, urlsplit

from ...domain.models import Content, DownloadError, Quality
from .addresses import is_watermarked_url


def normalize(data):
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", key)
            key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower()
            result[key] = normalize(value)
        return result
    if isinstance(data, list):
        return [normalize(value) for value in data]
    return None if data == "$undefined" else data


def find_aweme(data, aweme_id: str) -> dict | None:
    """只接受目标作品 ID，避免误下载页面同时返回的推荐素材。"""
    pending = deque([data])
    while pending:
        value = pending.popleft()
        if isinstance(value, dict):
            identity = value.get("aweme_id") or value.get("awemeId")
            if str(identity) == aweme_id:
                nested = value.get("aweme")
                if isinstance(nested, dict) and isinstance(nested.get("detail"), dict):
                    return normalize(nested["detail"])
                if value.get("video") or value.get("images"):
                    return normalize(value)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return None


def decode_page_data(render_data: str | None, flight_data: list) -> list:
    decoded = []
    if render_data:
        try:
            decoded.append(json.loads(unquote(render_data)))
        except (ValueError, TypeError):
            pass
    # 当前网页同时存在旧 RENDER_DATA 和 React Flight 行，逐行交给 JSON 解析器。
    for entry in flight_data or []:
        if not isinstance(entry, list) or len(entry) < 2 or not isinstance(entry[1], str):
            continue
        for line in entry[1].splitlines():
            match = re.match(r"^[0-9a-fA-F]+:(.+)$", line)
            if match:
                try:
                    decoded.append(json.loads(match[1]))
                except ValueError:
                    pass
    return decoded


def urls_from(value) -> tuple[str, ...]:
    if isinstance(value, dict):
        value = value.get("url_list") or value.get("download_url_list") or []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    return tuple(
        dict.fromkeys(
            u
            for u in value
            if isinstance(u, str)
            and urlsplit(u).scheme in {"http", "https"}
            and not is_watermarked_url(u)
        )
    )


def video_urls(value) -> tuple[str, ...]:
    urls = []
    for url in urls_from(value):
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        query = parse_qs(parsed.query)
        if query.get("watermark", ["0"])[0] == "1" or "playwm" in parsed.path:
            continue
        # 带签名的 CDN 原始流优先，明确带水印的播放接口不作为降级候选。
        if (
            host in {"douyin.com", "www.douyin.com", "www.iesdouyin.com"}
            and "/aweme/v1/play" in parsed.path
        ):
            continue
        urls.append(url)
    urls.sort(key=lambda u: not (urlsplit(u).hostname or "").endswith("douyinvod.com"))
    return tuple(urls)


def quality_list(video: dict) -> list[Quality]:
    result = []
    for entry in video.get("bit_rate") or video.get("bit_rate_list") or []:
        if not isinstance(entry, dict):
            continue
        addresses = video_urls(entry.get("play_addr"))
        if not addresses:
            addresses = video_urls(entry.get("download_addr"))
        if addresses:
            name = entry.get("gear_name") or entry.get("quality_type") or "original"
            result.append(Quality(str(name), int(entry.get("bit_rate") or 0), addresses))
    result.sort(key=lambda q: ("hdr" in q.name.lower(), -q.bitrate))
    fallback = video_urls(video.get("play_addr")) or video_urls(video.get("play_addr_h265"))
    if fallback and not any(q.urls == fallback for q in result):
        result.append(Quality("original", 0, fallback))
    return result


def parse_content(aweme: dict, aweme_id: str) -> Content:
    data = normalize(aweme)
    images = []
    image_videos = {}
    for index, item in enumerate(data.get("images") or []):
        # download_url_list 实测是平台加水印的导出版本，网页 url_list 才是无平台水印图片。
        addresses = urls_from(item.get("url_list")) or urls_from(item.get("download_url_list"))
        if not addresses:
            raise DownloadError(
                f"Photo {index + 1} has no watermark-free address. Watermarked sources are not allowed."
            )
        images.append(addresses)
        video = item.get("video") or {}
        live = video_urls(video.get("play_addr"))
        if live and float(video.get("duration") or 0) > 0:
            image_videos[index] = live
    author = data.get("author") or data.get("author_info") or {}
    music = data.get("music") or {}
    return Content(
        aweme_id=aweme_id,
        title=data.get("desc") or data.get("item_title") or aweme_id,
        author=author.get("nickname") or "unknown",
        qualities=quality_list(data.get("video") or {}) if not images else [],
        images=images,
        image_videos=image_videos,
        music_urls=urls_from(music.get("play_url")),
        music_duration=float(music.get("duration") or 0),
    )
