"""筛选平台提供的无水印地址，不篡改签名，也不使用带水印地址兜底。"""

from urllib.parse import parse_qs, unquote, urlsplit


def is_watermarked_url(url: str) -> bool:
    parsed = urlsplit(url)
    path = unquote(parsed.path).lower()
    if any(marker in path for marker in ("tplv-dy-water", "watermark", "playwm")):
        return True
    query = {key.lower(): values for key, values in parse_qs(parsed.query).items()}
    return any(value.lower() not in {"0", "false", "no"} for value in query.get("watermark", []))
