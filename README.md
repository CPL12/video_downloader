# Local Media Downloader

Language: English | [简体中文](README.zh-CN.md)

A clean local downloader for yt-dlp-compatible media URLs. Paste a link, fetch available formats, and save a single video or an entire playlist as MP4 or MP3 directly from your browser.

<p align="center">
  <img src="docs/screenshots/banner.png" alt="Banner image for the local media downloader project" width="100%" />
</p>

## Why This Project

- Runs locally on your machine instead of sending requests through a third-party website.
- Gives you a simple browser workflow for multiple video platforms in one place.
- Supports direct MP4 downloads, MP3 conversion, ZIP-packaged playlist downloads, and high-quality preparation for formats that need merging.
- Exposes progress clearly so the user can see when a large download is being prepared.
- Keeps the stack small and understandable with FastAPI, yt-dlp, and FFmpeg.

## Highlights

- Clean local browser workflow for yt-dlp-compatible URLs
- MP4 video and MP3 audio downloads
- Playlist downloads packaged as ZIP archives
- Two-column format picker with resolution, bitrate, and size hints
- High-resolution preparation flow for formats that require video/audio merging
- Optional Chrome cookie import for restricted videos
- Built-in temporary file cleanup controls

## Latest Screenshots

<p align="center">
  <img src="docs/screenshots/overview.png" alt="Current overview screen of the local media downloader" width="100%" />
</p>

<p align="center">
  <em>Landing screen with the URL field, fetch action, and the single-video or playlist download entry point.</em>
</p>

<p align="center">
  <img src="docs/screenshots/workflow.png" alt="Current high-quality preparation workflow of the local media downloader" width="100%" />
</p>

<p align="center">
  <em>Single-video workflow with format selection, preparation progress, and the final save step.</em>
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

- Single-video MP4 options list formats that include both video and audio for streaming.
- Playlist downloads are packaged as ZIP archives after yt-dlp finishes downloading the full collection.
- MP3 downloads are transcoded with FFmpeg at the selected bitrate.
- The backend may also work with other yt-dlp-compatible URLs that are not explicitly called out in the UI.
- If YouTube shows a "confirm you're not a bot" error, enable "Use Chrome cookies". Chrome must be closed; you can also enable "Auto-close Chrome".
- Use only content you own or are authorized to download.
