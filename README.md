# Local YouTube/Bilibili Downloader

Language: English | [简体中文](README.zh-CN.md)

This is a local FastAPI app that lets you paste a YouTube or Bilibili link, choose MP4 resolution or MP3 quality, and download directly in your browser.

## Prerequisites

- Python 3.10+
- FFmpeg installed and available on PATH

## Setup (PowerShell)

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

## Notes

- MP4 options list formats that include both video and audio for streaming.
- MP3 downloads are transcoded with FFmpeg at the selected bitrate.
- If YouTube shows a "confirm you're not a bot" error, enable "Use Chrome cookies". Chrome must be closed; you can also enable "Auto-close Chrome".
- Use only content you own or are authorized to download.
