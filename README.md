# 抖音素材下载小工具

作者：**dxy** · 版本：**1.0.0** · 许可证：**MIT**

支持抖音视频、图文图片、可获取的背景音乐，以及图文合成 MP4。
接受短链接、视频和图文长链接、整段分享文案及 `modal_id` 类链接。

> 仅供学习研究使用，请勿用于任何违法行为。使用者应遵守一切适用的法律法规、平台规则，
> 尊重著作权、隐私权及其他合法权益。请仅下载和使用自己拥有权利或已获授权的素材。
> MIT 许可证仅适用于软件代码，不授予任何抖音素材的使用权。

## Windows 使用

从 [Releases](https://github.com/jeesoul/douyin-downloader/releases) 下载 Windows 压缩包，
解压后双击 `DouyinDownloader.exe`，粘贴链接，选择画质与图文导出模式，点击 Download。

- 无需安装 Python。首次使用下载 Chromium；首次图文 MP4 导出另下载 FFmpeg（约 31 MB），均可后续复用。
- 默认 `Originals + MP4` 同时保存图片、可获取的配乐和合成视频；`Originals` 只保存素材。
- 视频按可用画质下载。指定画质不存在时会显示降级提示。
- 解析、下载和合成均显示状态；失败提示保留，可点击 Retry 重试。
- 默认保存到程序同目录的 `downloads/<作者_标题_作品ID>/`，Open Folder 可打开目录。
- 正式文件只有校验通过才保存；中断不会产生被误认为成功的半个 MP4。
- 无 Content-Length 时仍显示已下载大小和速度。

图文导出的 MP4 是图片轮播：有配乐时跟随实际音频时长，没有配乐时默认每张 3 秒。
可获取的 Live Photo 视频另存为 `live_*.mp4`，合成视频不复刻网页动画。
配乐缺失或附属素材不可获取时，会显示警告并记录到 `metadata.json`。

## 无水印规则

图片优先使用网页的 `url_list`。平台 `download_url_list` 可能添加抖音号水印，不能直接当成原图。
视频优先选择原始 CDN 流，排除已识别的水印模板、带水印参数、播放接口及重定向地址。
没有可用的无水印地址时明确失败，不用已知带水印的地址兜底。

保存平台实际提供的图片格式，例如 WebP、JPEG、PNG，不裁切、不模糊水印、不修改签名地址。
平台地址筛选不能证明所有画面天然无标识；作者已嵌入到画面中的文字或标识无法仅靠地址识别，
工具不宣称能移除这类内容。

## 源码运行

需要 Python 3.10 或更高版本及 Tk。建议使用虚拟环境：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe douyin_download.py
```

macOS/Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install --no-deps -e .
chmod +x douyin_download.sh
./douyin_download.sh "https://www.douyin.com/video/作品ID"
```

Linux 桌面 GUI 需要系统 Tk 支持；Chromium 也需要对应系统库，缺失时按 Playwright 的提示安装。
本地独立包验收针对 Windows；其他系统的源码测试由 CI 执行，实际平台验证结果以 CI 为准。

命令行参数：

```bash
python douyin_download.py "分享文案或链接" --quality 720
python douyin_download.py "图文链接" --photo-mode both
python douyin_download.py "图文链接" --photo-mode originals
python douyin_download.py "链接" --output ./materials --show
python douyin_download.py "图文链接" --slide-seconds 5
python douyin_download.py --version
```

## 开发与构建

```powershell
.venv\Scripts\python.exe -m pip install '.[build,dev]'
.venv\Scripts\python.exe -m ruff check src tests scripts douyin_download.py
.venv\Scripts\python.exe -m ruff format --check src tests scripts douyin_download.py
$env:RUN_GUI_TESTS = '1'
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts/build_release.py
```

构建输出位于 `dist/`：Windows 独立程序、Windows zip、源码 zip 和 `SHA256SUMS`。
Windows 程序必须在 Windows 构建；其他平台可用 `--source-only` 生成源码归档。
GitHub Actions 在 CI 中校验；推送与项目版本一致的 `v1.0.0` 标签会触发 Windows 构建和 Release 发布。

```text
src/douyin_downloader/
  domain/          内容、选项、结果和异常
  application/     下载流程编排
  adapters/douyin/ 链接及网页数据解析
  adapters/        文件传输、FFmpeg 媒体适配
  infrastructure/  运行环境、进程、日志、FFmpeg 下载
  presentation/    GUI 和 CLI
tests/             解析、传输、合成、缓存和窗口测试
scripts/           构建工具及打包 hook
docs/              架构和发布说明
```

详见 [工程结构](docs/ARCHITECTURE.md)、[变更记录](CHANGELOG.md) 和
[第三方组件声明](THIRD_PARTY_NOTICES.md)。本地指导文件、素材、Cookie、日志、备份及虚拟环境不会进入源码包。

## 故障诊断

失败窗口保留错误详情，Open Log 打开日志。日志通常位于程序目录的 `logs/downloader.log`；
目录不可写时使用系统临时目录。日志中的链接会脱敏，元数据不保存 Cookie 或媒体签名地址。
作品私密、删除、地区限制或平台验证可能阻止获取；显示浏览器时可手动完成平台验证。
网络恢复后可重试，已完成素材经 SHA-256 校验后复用。

维护问题请提交到 [Issues](https://github.com/jeesoul/douyin-downloader/issues)，描述操作步骤和脱敏错误。
