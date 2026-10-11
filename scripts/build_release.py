#!/usr/bin/env python3
"""生成 Windows 独立程序、源码归档及校验文件；只收录显式允许的源码路径。"""

import argparse
import hashlib
import importlib.metadata
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from douyin_downloader import __version__

ROOT = Path(__file__).resolve().parents[1]

SOURCE_PATHS = (
    "src",
    "scripts",
    "tests",
    "docs/ARCHITECTURE.md",
    ".github",
    "pyproject.toml",
    "requirements.txt",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "THIRD_PARTY_NOTICES.md",
    ".gitignore",
    ".gitattributes",
)


def source_files():
    for name in SOURCE_PATHS:
        path = ROOT / name
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        for candidate in candidates:
            if (
                candidate.is_file()
                and "__pycache__" not in candidate.parts
                and not any(part.endswith(".egg-info") for part in candidate.parts)
                and candidate.suffix not in {".pyc", ".pyo"}
            ):
                yield candidate


def third_party_licenses():
    packages = (
        "requests",
        "urllib3",
        "charset-normalizer",
        "certifi",
        "idna",
        "playwright",
        "Pillow",
        "imageio-ffmpeg",
        "greenlet",
        "pyee",
        "typing-extensions",
        "cffi",
        "cryptography",
        "bcrypt",
        "h2",
        "hpack",
        "hyperframe",
        "setuptools",
        "packaging",
        "pyinstaller",
    )
    for name in packages:
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        for entry in distribution.files or []:
            filename = entry.name.lower()
            if filename.startswith(
                ("license", "copying", "notice", "thirdpartynotice")
            ) and entry.suffix.lower() not in {".py", ".pyc"}:
                path = Path(distribution.locate_file(entry))
                if path.is_file():
                    relative = entry.as_posix().replace("../", "")
                    yield path, f"THIRD_PARTY_LICENSES/{name}/{relative}"
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        yield python_license, "THIRD_PARTY_LICENSES/Python/LICENSE.txt"


def build_windows(destination: Path) -> Path:
    if sys.platform != "win32":
        raise RuntimeError("Windows executable must be built on Windows.")
    import tkinter

    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    version = tuple(int(part) for part in __version__.split(".")) + (0,)
    work = ROOT / ".build" / "pyinstaller"
    work.mkdir(parents=True, exist_ok=True)
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=version,
            prodvers=version,
            mask=0x3F,
            flags=0,
            OS=0x40004,
            fileType=1,
            subtype=0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "dxy"),
                            StringStruct("FileDescription", "Douyin Material Downloader"),
                            StringStruct("FileVersion", __version__),
                            StringStruct("ProductVersion", __version__),
                            StringStruct("ProductName", "Douyin Material Downloader"),
                            StringStruct("LegalCopyright", "Copyright (c) 2026 dxy. MIT License."),
                            StringStruct("OriginalFilename", "DouyinDownloader.exe"),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
    version_file = work / "version.txt"
    version_file.write_text(str(version_info), encoding="utf-8")
    tk = tkinter.Tcl()
    tcl_path = Path(tk.eval("info library"))
    tk_path = tcl_path.parent / tcl_path.name.replace("tcl", "tk", 1)
    if not (tcl_path / "init.tcl").is_file() or not (tk_path / "tk.tcl").is_file():
        raise RuntimeError("Complete Tcl/Tk runtime was not found.")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--windowed",
            "--exclude-module",
            "numpy",
            "--name",
            "DouyinDownloader",
            "--paths",
            str(ROOT / "src"),
            "--distpath",
            str(destination),
            "--workpath",
            str(work / "work"),
            "--specpath",
            str(work),
            "--version-file",
            str(version_file),
            "--collect-all",
            "playwright",
            "--additional-hooks-dir",
            str(ROOT / "scripts" / "pyinstaller_hooks"),
            "--hidden-import",
            "tkinter",
            "--hidden-import",
            "tkinter.ttk",
            "--hidden-import",
            "tkinter.font",
            "--hidden-import",
            "tkinter.messagebox",
            "--add-data",
            f"{tcl_path};tcl8/8.6",
            "--add-data",
            f"{tk_path};_tk_data",
            str(ROOT / "scripts" / "desktop_entry.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    return destination / "DouyinDownloader.exe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument(
        "--legacy-copy", action="store_true", help="Refresh the original local executable filename"
    )
    args = parser.parse_args()
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = f"## {__version__}\n"
    if heading not in changelog:
        raise RuntimeError("The current version is missing from CHANGELOG.md.")
    changes = changelog.split(heading, 1)[1].split("\n## ", 1)[0].strip()
    notes = (
        f"# 抖音素材下载小工具 {__version__}\n\n"
        f"{changes}\n\n"
        f"Windows 包：`douyin-downloader-{__version__}-windows-x64.zip`，解压后运行 `DouyinDownloader.exe`。\n"
        "无需安装 Python；首次使用联网初始化 Chromium，图文导出按需下载 FFmpeg。\n\n"
        "作者：dxy。原创代码采用 MIT 许可证，第三方组件保留其各自许可证。\n\n"
        "仅供学习研究，请勿违法使用。请遵守适用法律法规和平台规则，尊重版权、隐私及其他合法权益。\n"
    )
    (dist / "RELEASE_NOTES.md").write_text(notes, encoding="utf-8")
    artifacts = []
    if not args.source_only:
        executable = build_windows(dist)
        package = dist / f"douyin-downloader-{__version__}-windows-x64.zip"
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in [
                executable,
                ROOT / "README.md",
                ROOT / "LICENSE",
                ROOT / "CHANGELOG.md",
                ROOT / "THIRD_PARTY_NOTICES.md",
            ]:
                archive.write(item, item.name)
            for path, name in third_party_licenses():
                archive.write(path, name)
        artifacts.append(package)
        if args.legacy_copy:
            shutil.copy2(executable, ROOT / "抖音视频下载.exe")
    source = dist / f"douyin-downloader-{__version__}-source.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files():
            archive.write(
                path, f"douyin-downloader-{__version__}/{path.relative_to(ROOT).as_posix()}"
            )
    artifacts.append(source)
    checksums = []
    for path in artifacts:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        checksums.append(f"{digest.hexdigest()}  {path.name}")
        print(f"Built: {path.name} ({path.stat().st_size} bytes)")
    (dist / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
