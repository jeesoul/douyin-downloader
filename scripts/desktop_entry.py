#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立桌面程序入口；配置打包后的 Tcl/Tk，再启动统一 CLI/GUI。"""

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
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


if __name__ == "__main__":
    prepare_runtime()
    from douyin_downloader.presentation.cli import main

    raise SystemExit(main())
