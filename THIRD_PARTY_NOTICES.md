# 第三方组件

本项目原创代码由 dxy 以 MIT 许可证发布；第三方组件保留其各自许可证与版权。

| 组件 | 用途 | 许可证及来源 |
| --- | --- | --- |
| Python | 运行时 | [PSF License](https://docs.python.org/3/license.html) |
| Tcl/Tk | 桌面界面 | [Tcl/Tk License](https://www.tcl-lang.org/software/tcltk/license.html) |
| Playwright | 浏览器自动化 | [Apache-2.0](https://github.com/microsoft/playwright-python) |
| Node.js | Playwright 驱动 | [MIT 及第三方声明](https://github.com/nodejs/node/blob/main/LICENSE) |
| Requests | HTTP 请求 | [Apache-2.0](https://github.com/psf/requests) |
| Pillow | 图片读取与合成 | [HPND](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| imageio-ffmpeg | FFmpeg Python 适配 | [BSD-2-Clause](https://github.com/imageio/imageio-ffmpeg) |
| PyInstaller | 打包引导程序 | [GPL-2.0-or-later 和引导程序例外](https://pyinstaller.org/en/stable/license.html) |

Chromium 由 Playwright 首次运行时下载，保留其原有许可证，不包含在本项目发布包中。

## FFmpeg

图文 MP4 导出通过独立子进程调用 FFmpeg。当前 imageio-ffmpeg 0.6.0 的 Windows 运行时使用
FFmpeg 7.1 GPLv3 构建，不能以本项目的 MIT 许可证替代其许可证。

Windows 发布包不包含 FFmpeg 编码器二进制。首次导出时从 PyPI 的 imageio-ffmpeg 0.6.0
官方 wheel 下载，校验 PyPI 提供的 SHA-256，保存到用户缓存中。也可通过
`IMAGEIO_FFMPEG_EXE` 指定自行安装的 FFmpeg。

使用和再次分发 FFmpeg 时，应遵守其自身许可证。有关许可证及源码请参阅
[FFmpeg 官方说明](https://ffmpeg.org/legal.html)、[FFmpeg 源码](https://ffmpeg.org/download.html#sources)
和 [imageio-ffmpeg 上游构建来源](https://github.com/imageio/imageio-ffmpeg)。
