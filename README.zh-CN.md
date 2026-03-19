# Local YouTube/Bilibili Downloader

语言： [English](README.md) | 简体中文

<p align="center">
  <img src="docs/screenshots/banner.png" alt="本地 YouTube 和 Bilibili 下载器横幅图" width="100%" />
</p>

这是一个本地化的 YouTube 和 Bilibili 下载工具。你只需要粘贴链接、读取可用格式，然后就可以直接在浏览器中下载 MP4 视频或 MP3 音频。

## 为什么做这个项目

- 完全在你的电脑本地运行，不需要依赖第三方下载网站。
- 用一个简洁的浏览器界面同时处理 YouTube 和 Bilibili 链接。
- 同时支持 MP4 下载、MP3 转码，以及需要合并音视频时的高质量准备流程。
- 会显示准备进度，用户可以清楚知道大文件当前处理到哪里。
- 技术栈简单直接，核心依赖就是 FastAPI、yt-dlp 和 FFmpeg。

## 功能亮点

- 支持 YouTube 和 Bilibili
- 支持 MP4 视频和 MP3 音频下载
- 提供分辨率、码率、体积等格式信息
- 支持需要合并音视频时的高分辨率准备流程
- 可选 Chrome cookies 导入，用于受限视频
- 内置临时文件清理功能

## 截图

<p align="center">
  <img src="docs/screenshots/overview.png" alt="本地媒体下载器概览界面" width="49%" />
  <img src="docs/screenshots/workflow.png" alt="格式选择与高质量下载准备流程" width="49%" />
</p>

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
