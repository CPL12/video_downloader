# Local YouTube/Bilibili Downloader

语言： [English](README.md) | 简体中文

这是一个本地 FastAPI 应用，你可以粘贴 YouTube 或 Bilibili 链接，选择 MP4 分辨率或 MP3 音质，然后直接在浏览器中下载。

## 使用的开源项目

- [FastAPI](https://github.com/fastapi/fastapi)：用于本地 Web 应用和 API。
- [Uvicorn](https://github.com/encode/uvicorn)：作为 ASGI 服务器运行应用。
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：用于提取视频和音频格式并处理下载。
- [FFmpeg](https://ffmpeg.org/)：用于媒体处理和 MP3 转码。
- [python-multipart](https://github.com/Kludex/python-multipart)：用于 FastAPI 中的表单数据处理。

## 环境要求

- Python 3.10+
- 已安装 FFmpeg，并且已加入 PATH

## 安装步骤（PowerShell）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 运行

```powershell
python main.py
```

然后在浏览器中打开 `http://127.0.0.1:8000`。

## 说明

- MP4 选项会列出同时包含视频和音频、可直接播放的格式。
- MP3 下载会通过 FFmpeg 按所选比特率进行转码。
- 如果 YouTube 显示 "confirm you're not a bot" 错误，请启用 "Use Chrome cookies"。Chrome 必须先关闭；你也可以启用 "Auto-close Chrome"。
- 仅下载你拥有版权或已获得授权的内容。
