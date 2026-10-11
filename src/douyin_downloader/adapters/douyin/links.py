import re
from urllib.parse import parse_qs, urlsplit

import requests

from ...domain.models import DownloadError, ResolvedLink

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
HOSTS = {"douyin.com", "www.douyin.com", "v.douyin.com", "iesdouyin.com", "www.iesdouyin.com"}
URL_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:v\.douyin\.com|douyin\.com|iesdouyin\.com)(?=[/:?\s]|$)[^\s<>\"，。；！）】]*",
    re.IGNORECASE,
)


def extract_url(text: str) -> str | None:
    for match in URL_PATTERN.finditer(text or ""):
        url = match.group(0).rstrip(".,;!)]}")
        if urlsplit(url).hostname in HOSTS:
            return url
    return None


def parse_url(url: str) -> ResolvedLink | None:
    parsed = urlsplit(url)
    if parsed.hostname not in HOSTS:
        return None
    match = re.fullmatch(r"/(?:share/)?(video|note)/(\d+)/?", parsed.path)
    if match:
        return ResolvedLink(match[2], match[1])
    query = parse_qs(parsed.query)
    for key in ("modal_id", "aweme_id", "item_id"):
        value = query.get(key, [""])[0]
        if value.isdigit():
            return ResolvedLink(value)
    return None


def resolve_link(text: str) -> ResolvedLink:
    url = extract_url(text)
    if not url:
        raise DownloadError("No supported Douyin link found.")
    resolved = parse_url(url)
    if resolved:
        return resolved
    try:
        with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(10, 20)) as response:
            response.raise_for_status()
            resolved = parse_url(response.url)
            if not resolved:
                for candidate in URL_PATTERN.findall(response.text):
                    resolved = parse_url(candidate)
                    if resolved:
                        break
    except requests.RequestException as exc:
        raise DownloadError(f"Cannot resolve share link: {exc}") from exc
    if not resolved:
        raise DownloadError(
            "Cannot find a video or photo post ID. The share link may have expired."
        )
    return resolved
