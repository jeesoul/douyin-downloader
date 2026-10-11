# 抖音素材下载小工具

[![CI](https://github.com/jeesoul/douyin-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/jeesoul/douyin-downloader/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/jeesoul/douyin-downloader)](https://github.com/jeesoul/douyin-downloader/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

用于下载抖音公开视频及图文素材的桌面工具，支持分享链接解析、画质选择和 Live Photo 动态图文导出。
提供 Windows 独立程序，以及可在 Windows、macOS 和 Linux 运行的 Python 源码。

## 下载与使用

前往 [最新 Release](https://github.com/jeesoul/douyin-downloader/releases/latest)，下载
Windows x64 压缩包，解压后运行 `DouyinDownloader.exe`。粘贴分享链接或完整分享文案，选择导出模式后点击 **Download**。

Windows 程序无需安装 Python。首次使用会下载 Chromium，首次合成 MP4 时按需下载 FFmpeg。
默认保存位置为程序目录下的 `downloads/`，每条作品使用独立文件夹。

| 内容类型 | 保存结果 |
| --- | --- |
| 普通视频 | 所选画质的原始 MP4 |
| 静态图文 | 图片、可获取的配乐、图片轮播 MP4 |
| Live Photo 动态图文 | 图片、原始动态短片、配乐、保留动态画面的 MP4 |

`Originals + MP4` 同时保存素材并合成视频；`Originals` 只保存素材。
有配乐时，动态短片按配乐时长循环播放；无配乐时保留动态短片原始时长。
解析、下载与合成均显示进度，失败后保留错误详情并支持重试。

动态源无法取得合格原流时，图片和配乐仍会保存。`Originals` 模式明确提示部分完成；
`Originals + MP4` 模式显示来源不可用并停止合成，不会用静态封面伪装成原动图。
出现 `Source rejected` 表示源内容被水印策略拒绝，不是网络连接失败，可用 Open Folder 查看已保存素材。

## 源码运行

需要 Python 3.10 或更高版本。桌面界面需要 Tk，浏览器运行需要 Playwright 对应的系统依赖。

```bash
python -m venv .venv
```

激活虚拟环境后安装并启动：

```bash
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python -m douyin_downloader
```

Windows 可使用 `.venv\Scripts\activate` 激活环境，macOS/Linux 使用 `source .venv/bin/activate`。

命令行使用同一下载流程：

```bash
douyin-downloader "分享链接或文案" --quality 720
douyin-downloader "图文链接" --photo-mode both
douyin-downloader "图文链接" --photo-mode originals --output ./materials
douyin-downloader "链接" --show
```

所有参数见 `douyin-downloader --help`。`--slide-seconds` 仅控制无配乐静态图片的展示时长。
命令行退出码：`0` 完整完成、`1` 下载失败、`2` 部分保存、`3` 内容策略拒绝、`130` 取消。

## 工作方式与限制

- 通过 Playwright 读取目标作品的接口或页面数据，按作品 ID 匹配，筛选无水印媒体地址。
- 原始图片与动态短片分别保存，合成视频不会用静态封面代替已识别的动态素材。
- 已识别的水印模板、播放地址及重定向地址会被拒绝；不裁切、模糊或抹除画面中的标识。
- 作品中的作者原生文字或标识无法仅凭地址识别，工具不提供通用视觉去水印能力。
- 登录验证、内容删除、访问限制及签名过期可能导致下载失败。动态流获取失败会明确报错。
- 原始素材保留上游格式和编码；合成 MP4 使用 H.264/AAC。配乐不可获取时会明确提示。

失败详情可在窗口或 `logs/downloader.log` 查看。日志中的链接会脱敏，Cookie 和签名地址不写入作品元数据。

## 开发

```bash
python -m pip install '.[build,dev]'
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m unittest discover -s tests -v
python scripts/build_release.py
```

独立 Windows 程序必须在 Windows 构建。构建输出位于 `dist/`，包含 Windows 包、源码包及 `SHA256SUMS`。
可通过 `--output` 指定独立输出目录，避免覆盖正在运行的旧包。
桌面环境下设置 `RUN_GUI_TESTS=1` 可执行 GUI 生命周期测试。

代码按领域模型、流程编排、平台适配和界面分层。详见 [架构说明](docs/ARCHITECTURE.md)。
提交问题时请提供复现步骤与脱敏错误：[Issues](https://github.com/jeesoul/douyin-downloader/issues)。

## 许可证与使用声明

作者：**dxy**。原创代码采用 [MIT License](LICENSE)，第三方组件遵循各自许可证，见
[第三方声明](THIRD_PARTY_NOTICES.md)。

**仅供学习研究，请勿违法使用。** 请遵守适用法律法规和平台规则，尊重著作权、隐私权及其他合法权益，
仅下载自己拥有权利或已获授权的素材。软件许可证不授予任何素材的使用权。
