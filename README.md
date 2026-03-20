# Local Media Downloader

Language: English | [简体中文](README.zh-CN.md)

<p align="center">
  <img src="docs/screenshots/banner.png" alt="Banner for the local media downloader" width="100%" />
</p>

A clean local downloader for YouTube, Bilibili, and other yt-dlp-supported platforms. Paste a link, fetch available formats, and save MP4 video or MP3 audio directly from your browser.

## Why This Project

- Runs locally on your machine instead of sending requests through a third-party website.
- Gives you a simple browser workflow for multiple video platforms in one place.
- Supports direct MP4 downloads, MP3 conversion, and high-quality preparation for formats that need merging.
- Exposes progress clearly so the user can see when a large download is being prepared.
- Keeps the stack small and understandable with FastAPI, yt-dlp, and FFmpeg.

## Highlights

- YouTube, Bilibili, and other yt-dlp-supported platforms
- MP4 video and MP3 audio downloads
- Format picker with resolution, bitrate, and size hints
- High-resolution preparation flow for formats that require video/audio merging
- Optional Chrome cookie import for restricted videos
- Built-in temporary file cleanup controls

## Screenshots

<p align="center">
  <img src="docs/screenshots/overview.png" alt="Overview screen of the local media downloader" width="49%" />
  <img src="docs/screenshots/workflow.png" alt="Format selection and high-quality download preparation" width="49%" />
</p>

## Open Source Projects Used

- [FastAPI](https://github.com/fastapi/fastapi) for the local web application and API.
- [Uvicorn](https://github.com/encode/uvicorn) as the ASGI server.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for extracting video and audio formats and handling downloads.
- [FFmpeg](https://ffmpeg.org/) for media processing and MP3 transcoding.
- [python-multipart](https://github.com/Kludex/python-multipart) for form-data handling in FastAPI uploads/forms.

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
- Platform availability depends on the installed `yt-dlp` version and the source site's current extractor support.
- If YouTube shows a "confirm you're not a bot" error, enable "Use Chrome cookies". Chrome must be closed; you can also enable "Auto-close Chrome".
- Use only content you own or are authorized to download.
