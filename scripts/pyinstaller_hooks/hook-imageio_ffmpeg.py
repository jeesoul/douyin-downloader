"""保留 Python 适配代码，排除依赖 wheel 携带的 GPL FFmpeg 二进制。"""

hiddenimports = ["imageio_ffmpeg.binaries"]
datas = []
binaries = []
