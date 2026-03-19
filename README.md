# Local YouTube/Bilibili Downloader

This is a local FastAPI app that lets you paste a YouTube or Bilibili link, choose MP4 resolution or MP3 quality, and download directly in your browser.

这是一个本地 FastAPI 应用，你可以粘贴 YouTube 或 Bilibili 链接，选择 MP4 分辨率或 MP3 音质，然后直接在浏览器中下载。

## Prerequisites

- Python 3.10+
- FFmpeg installed and available on PATH

## 环境要求

- Python 3.10+
- 已安装 FFmpeg，并且已加入 PATH

## Setup (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 安装步骤（PowerShell）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

Then open `http://127.0.0.1:8000` in your browser.

## 运行

```powershell
python main.py
```

然后在浏览器中打开 `http://127.0.0.1:8000`。

## Notes

- MP4 options list formats that include both video and audio for streaming.
- MP3 downloads are transcoded with FFmpeg at the selected bitrate.
- If YouTube shows a "confirm you're not a bot" error, enable "Use Chrome cookies". Chrome must be closed; you can also enable "Auto-close Chrome".
- Use only content you own or are authorized to download.

## 说明

- MP4 选项会列出同时包含视频和音频、可直接播放的格式。
- MP3 下载会通过 FFmpeg 按所选比特率进行转码。
- 如果 YouTube 显示 "confirm you're not a bot" 错误，请启用 "Use Chrome cookies"。Chrome 必须先关闭；你也可以启用 "Auto-close Chrome"。
- 仅下载你拥有版权或已获得授权的内容。
