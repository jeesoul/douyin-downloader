#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保留原启动文件名；业务实现位于 src/douyin_downloader。"""

import os
import sys
from pathlib import Path


def prepare_runtime():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
        if sys.platform == "win32":
            import ctypes

            buffer = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.kernel32.GetLongPathNameW(str(base), buffer, len(buffer)):
                base = Path(buffer.value)
        for variable, relative in (("TCL_LIBRARY", "tcl8/8.6"), ("TK_LIBRARY", "_tk_data")):
            location = base / relative
            if location.is_dir():
                os.environ[variable] = str(location)
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


if __name__ == "__main__":
    prepare_runtime()
    from douyin_downloader.presentation.cli import main

    raise SystemExit(main())
