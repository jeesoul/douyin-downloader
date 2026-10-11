"""素材完整性及人工确认的不合格媒体记录，不修改原始画面。"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from ..domain.models import DownloadError, MediaRejectedError


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validation_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "douyin-downloader" / "asset-validation.json"


def _read_validation() -> dict[str, str]:
    path = validation_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data["rejected_sha256"]
        if not isinstance(records, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in records.items()
        ):
            raise ValueError("Invalid rejection records")
        return records
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DownloadError("Cannot read local media validation records.") from exc


def require_accepted_asset(digest: str):
    reason = _read_validation().get(digest)
    if reason is not None:
        raise MediaRejectedError(f"Verified embedded watermark in source media. {reason}")


def record_rejected_asset(path: Path, reason: str):
    """只登记已核验的文件指纹及原因，不保留作品链接或会话数据。"""
    catalog = validation_path()
    records = _read_validation()
    records[sha256(path)] = reason
    catalog.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".validation-", suffix=".part", dir=catalog.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"rejected_sha256": records}, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, catalog)
    finally:
        if os.path.exists(name):
            os.remove(name)
