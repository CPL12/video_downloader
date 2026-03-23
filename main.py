import json
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI, HTTPException, Request, Form, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DOWNLOADS_DIR = STATIC_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DOWNLOADS_DIR = DOWNLOADS_DIR / ".prep"
TEMP_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Tracks background preparation tasks: {task_id: {status, progress, speed, filename, etc.}}
active_tasks = {}
active_tasks_lock = threading.Lock()

ALLOWED_AUDIO_QUALITIES = [128, 192, 256, 320]
ALLOWED_COOKIE_SOURCES = {"chrome"}
MAX_STDERR_BYTES = 65536
CHROME_COOKIE_LOCK = "Could not copy Chrome cookie database"
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}
MAX_FILENAME_STEM_LENGTH = 180

app = FastAPI(title="Local Media Downloader")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

def cleanup_old_downloads():
    """Remove files older than 1 hour from the downloads directory."""
    now = time.time()
    try:
        for f in DOWNLOADS_DIR.glob("*"):
            if f.is_file() and (now - f.stat().st_mtime) > 3600:
                f.unlink()
            elif f.is_dir() and (now - f.stat().st_mtime) > 3600:
                shutil.rmtree(f, ignore_errors=True)
    except Exception:
        pass

@app.on_event("startup")
async def startup_event():
    # Run cleanup on startup
    cleanup_old_downloads()



class StderrCapture:
    def __init__(self, pipe):
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._drain, args=(pipe,), daemon=True)
        self._thread.start()

    def _drain(self, pipe):
        while True:
            data = pipe.read(1024)
            if not data:
                break
            sys.stderr.buffer.write(data)
            sys.stderr.buffer.flush()
            with self._lock:
                self._buf += data
                if len(self._buf) > MAX_STDERR_BYTES:
                    self._buf = self._buf[-MAX_STDERR_BYTES:]

    def text(self):
        with self._lock:
            return self._buf.decode("utf-8", errors="ignore").strip()


def normalize_url(raw_url: str) -> str:
    if not raw_url:
        raise HTTPException(status_code=400, detail="URL is required.")
    url = raw_url.strip()
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="Paste a valid http(s) media URL supported by yt-dlp.",
        )
    return url


def sanitize_filename(value: str) -> str:
    cleaned = unicodedata.normalize("NFKC", value or "")
    cleaned = re.sub(r"[\x00-\x1f]", "", cleaned)
    cleaned = re.sub(r'[<>:"/\\|?*]+', " - ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned[:MAX_FILENAME_STEM_LENGTH].rstrip(" .")
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned or "download"


def ascii_filename(value: str) -> str:
    cleaned = unicodedata.normalize("NFKD", value or "")
    cleaned = cleaned.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r'[^a-zA-Z0-9 _.-]+', " - ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "download"


def build_attachment_headers(filename: str) -> dict[str, str]:
    fallback = ascii_filename(filename)
    encoded = quote(filename, safe="")
    return {
        "Content-Disposition": f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}',
        "Cache-Control": "no-store",
    }


def build_quality_label(height: str | int | None = None, audio_quality: int | None = None) -> str | None:
    if height:
        height_text = str(height).strip()
        if height_text.lower().endswith("p"):
            height_text = height_text[:-1]
        if height_text:
            return f"{height_text}p"
    if audio_quality:
        return f"{audio_quality}kbps"
    return None


def build_download_filename(title: str, extension: str, quality_label: str | None = None) -> str:
    base = sanitize_filename(title)
    ext = extension.lstrip(".").lower() or "bin"
    if quality_label:
        return f"{base} ({sanitize_filename(quality_label)}).{ext}"
    return f"{base}.{ext}"


def build_cached_mp4_filename(title: str, format_id: str, height: str | None = None) -> str:
    base = sanitize_filename(title)
    format_label = sanitize_filename(format_id).replace(" ", "_")
    quality_label = build_quality_label(height=height)
    parts = [base]
    if quality_label:
        parts.append(f"({quality_label})")
    parts.append(f"[{format_label}]")
    return f"{' '.join(parts)}.mp4"


def parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def close_chrome_processes():
    if sys.platform != "win32":
        return
    subprocess.run(
        ["taskkill", "/F", "/IM", "chrome.exe", "/T"],
        capture_output=True,
        text=True,
    )


def normalize_ydl_error(message: str) -> str:
    if CHROME_COOKIE_LOCK in message:
        return (
            "Chrome is running and its cookie database is locked. "
            "Close Chrome completely (including background processes) or "
            "enable Auto-close Chrome, then try again."
        )
    lowered = message.lower()
    if "unsupported url" in lowered or "no suitable extractor" in lowered:
        return "This URL is not supported by the installed yt-dlp build."
    return message


def cookie_args(cookie_source: str | None) -> list[str]:
    if not cookie_source:
        return []
    source = cookie_source.strip().lower()
    if source not in ALLOWED_COOKIE_SOURCES:
        raise HTTPException(status_code=400, detail="Only Chrome is supported for cookies.")
    return ["--cookies-from-browser", source]


def run_yt_dlp_json(
    url: str,
    cookie_source: str | None = None,
    auto_close_chrome: bool = False,
) -> dict:
    if cookie_source and auto_close_chrome:
        close_chrome_processes()
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-J",
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        *cookie_args(cookie_source),
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        message = err[-1] if err else "Failed to fetch formats."
        raise HTTPException(status_code=400, detail=normalize_ydl_error(message))
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Failed to parse format data.") from exc


def pick_mp4_formats(formats: list[dict]) -> list[dict]:
    best_by_height: dict[int, dict] = {}
    for fmt in formats:
        if fmt.get("ext") != "mp4":
            continue
        vcodec = fmt.get("vcodec")
        if vcodec == "none" or not vcodec:
            continue
        
        # Check protocol
        protocol = (fmt.get("protocol") or "").lower()
        if protocol in ("m3u8", "m3u8_native", "http_dash_segments"):
            continue
            
        height = fmt.get("height")
        if not height:
            continue
            
        is_progressive = fmt.get("acodec") != "none"
        
        current = best_by_height.get(height)
        if not current:
            # Prefer progressive if available, otherwise take what we have
            best_by_height[height] = fmt
            continue
            
        curr_progressive = current.get("acodec") != "none"
        
        # If current is not progressive but this one is, take it!
        if is_progressive and not curr_progressive:
            best_by_height[height] = fmt
            continue
            
        # If both are same progressive status, take higher bitrate
        if is_progressive == curr_progressive:
            if (fmt.get("tbr") or 0) > (current.get("tbr") or 0):
                best_by_height[height] = fmt


    results = []
    for height in sorted(best_by_height.keys()):
        fmt = best_by_height[height]
        results.append(
            {
                "format_id": fmt.get("format_id"),
                "height": height,
                "fps": fmt.get("fps"),
                "tbr": fmt.get("tbr"),
                "filesize": fmt.get("filesize") or fmt.get("filesize_approx"),
                "url": fmt.get("url"),
                "need_merge": fmt.get("acodec") == "none",
            }
        )
    return results


def get_direct_url(
    url: str,
    format_id: str,
    cookie_source: str | None = None,
    auto_close_chrome: bool = False,
) -> str:
    """Use yt-dlp to extract the direct CDN download URL for a given format."""
    if cookie_source and auto_close_chrome:
        close_chrome_processes()
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-f",
        str(format_id),
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--get-url",
        *cookie_args(cookie_source),
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        message = err[-1] if err else "Failed to get download URL."
        raise HTTPException(status_code=400, detail=normalize_ydl_error(message))
    direct_url = (proc.stdout or "").strip()
    if not direct_url:
        raise HTTPException(status_code=500, detail="Could not extract download URL.")
    return direct_url


def stream_pipeline(ydl_cmd: list[str], ffmpeg_cmd: list[str], media_type: str, filename: str):
    ydl_proc = subprocess.Popen(ydl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1048576)
    ydl_err = StderrCapture(ydl_proc.stderr)
    
    ffmpeg_proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=ydl_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1048576,
    )
    ffmpeg_err = StderrCapture(ffmpeg_proc.stderr)

    # Allow a small buffer read to see if it starts successfully
    first_chunk = ffmpeg_proc.stdout.read(64 * 1024)
    if not first_chunk:
        ffmpeg_proc.kill()
        ydl_proc.kill()
        msg = ffmpeg_err.text() or ydl_err.text() or "Streaming failed."
        raise HTTPException(status_code=400, detail=normalize_ydl_error(msg))

    def iterator():
        try:
            yield first_chunk
            while True:
                chunk = ffmpeg_proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                ffmpeg_proc.stdout.close()
            except Exception:
                pass
            try:
                ffmpeg_proc.wait(timeout=5)
            except Exception:
                pass
            try:
                ydl_proc.wait(timeout=5)
            except Exception:
                pass

    headers = build_attachment_headers(filename)
    return StreamingResponse(iterator(), media_type=media_type, headers=headers)


def generate_task_id(url: str, format_id: str) -> str:
    import hashlib
    return hashlib.md5(f"{url}_{format_id}".encode()).hexdigest()

def parse_download_progress(line: str):
    """
    Parse yt-dlp progress line: [download]  12.4% of 77.16MiB at 329.54KiB/s ETA 03:29
    """
    try:
        if "[download]" not in line:
            return None
        
        res = {}
        # Match percentage
        percent_match = re.search(r"(\d+\.\d+)%", line)
        if percent_match:
            res["progress"] = float(percent_match.group(1))
            
        # Match speed
        speed_match = re.search(r"at\s+([\d\.]+[KMG]iB/s)", line)
        if speed_match:
            res["speed"] = speed_match.group(1)
            
        # Match ETA
        eta_match = re.search(r"ETA\s+([\d:]+)", line)
        if eta_match:
            res["eta"] = eta_match.group(1)
            
        return res if res else None
    except Exception:
        return None


def update_task(task_id: str, **fields):
    with active_tasks_lock:
        if task_id in active_tasks:
            active_tasks[task_id].update(fields)


def run_download_step(
    task_id: str,
    url: str,
    format_selector: str,
    output_template: Path,
    cookies: str | None,
    label: str,
):
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", format_selector,
        "--no-playlist",
        "--newline",
        "--concurrent-fragments", "5",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        *cookie_args(cookies),
        "-o", str(output_template),
        url,
    ]

    update_task(
        task_id,
        status="downloading",
        phase="download",
        phase_label=f"Downloading {label}",
        progress=0.0,
        speed="",
        eta="unknown",
        message=f"Downloading {label.lower()}...",
    )

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    last_info = {"progress": 0.0, "speed": "", "eta": "unknown"}
    try:
        for line in proc.stdout:
            info = parse_download_progress(line)
            if not info:
                continue
            last_info.update(info)
            update_task(
                task_id,
                progress=last_info.get("progress", 0.0),
                speed=last_info.get("speed", ""),
                eta=last_info.get("eta", "unknown"),
                message=f"Downloading {label.lower()}...",
            )
    finally:
        proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed while downloading {label.lower()}.")

    update_task(
        task_id,
        progress=100.0,
        speed="",
        eta="00:00",
        message=f"{label} download complete.",
    )


def find_downloaded_file(task_dir: Path, stem: str) -> Path:
    matches = [path for path in task_dir.glob(f"{stem}.*") if path.is_file()]
    if not matches:
        raise FileNotFoundError(f"Could not locate downloaded {stem} file.")
    return max(matches, key=lambda path: path.stat().st_mtime)


def get_media_duration_seconds(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        proc = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            try:
                duration = float((proc.stdout or "").strip())
                if duration > 0:
                    return duration
            except ValueError:
                pass

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None

    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    )
    output = (proc.stderr or "") + "\n" + (proc.stdout or "")
    match = re.search(r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def get_media_stream_codec(path: Path, stream_selector: str) -> str | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None

    proc = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-select_streams", stream_selector,
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    codec = (proc.stdout or "").strip().lower()
    return codec or None


def parse_ffmpeg_progress(line: str, total_duration: float | None):
    if "=" not in line:
        return None
    key, value = line.strip().split("=", 1)
    if key not in {"out_time_ms", "out_time_us", "out_time"}:
        return None

    elapsed = None
    if key == "out_time":
        match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", value)
        if match:
            hours, minutes, seconds = match.groups()
            elapsed = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    else:
        try:
            raw_elapsed = float(value)
            if key == "out_time_us":
                elapsed = raw_elapsed / 1_000_000
            elif total_duration and raw_elapsed > total_duration * 1_000:
                elapsed = raw_elapsed / 1_000_000
            else:
                elapsed = raw_elapsed / 1_000
        except ValueError:
            return None

    if elapsed is None:
        return None

    progress = None
    if total_duration and total_duration > 0:
        progress = max(0.0, min((elapsed / total_duration) * 100, 100.0))

    return {"merge_progress": progress}


def merge_streams_with_progress(task_id: str, video_path: Path, audio_path: Path, out_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH.")

    durations = [duration for duration in (
        get_media_duration_seconds(video_path),
        get_media_duration_seconds(audio_path),
    ) if duration]
    total_duration = max(durations) if durations else None
    audio_codec = get_media_stream_codec(audio_path, "a:0")
    can_copy_audio = audio_codec == "aac"

    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "copy" if can_copy_audio else "aac",
        *(["-b:a", "192k"] if not can_copy_audio else []),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-progress", "pipe:1",
        "-nostats",
        str(out_path),
    ]

    update_task(
        task_id,
        status="merging",
        phase="merge",
        phase_label="Merging Video and Audio",
        progress=0.0,
        speed="",
        eta="unknown",
        message="Merging video and audio..." if can_copy_audio else "Merging video and converting audio to AAC...",
    )

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stderr_capture = StderrCapture(proc.stderr)

    try:
        for line in proc.stdout:
            info = parse_ffmpeg_progress(line, total_duration)
            if not info:
                continue
            update_task(
                task_id,
                progress=info["merge_progress"] if info["merge_progress"] is not None else 0.0,
                speed="",
                eta="unknown",
                message="Merging video and audio..." if can_copy_audio else "Merging video and converting audio to AAC...",
            )
    finally:
        proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(stderr_capture.text() or "ffmpeg failed while merging streams.")

    update_task(
        task_id,
        progress=100.0,
        speed="",
        eta="00:00",
        message="Merge complete. Finalizing file...",
    )

def background_downloader(task_id: str, url: str, format_id: str, filename: str, cookies: str | None, auto_close: bool):
    out_path = DOWNLOADS_DIR / filename
    task_dir = TEMP_DOWNLOADS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    video_template = task_dir / "video.%(ext)s"
    audio_template = task_dir / "audio.%(ext)s"

    with active_tasks_lock:
        active_tasks[task_id].update(
            {
                "status": "downloading",
                "phase": "download",
                "phase_label": "Downloading Video",
                "filename": filename,
                "message": "Downloading video...",
            }
        )

    try:
        if cookies and auto_close:
            close_chrome_processes()

        run_download_step(task_id, url, format_id, video_template, cookies, "Video")
        run_download_step(
            task_id,
            url,
            "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio/best",
            audio_template,
            cookies,
            "Audio",
        )

        video_path = find_downloaded_file(task_dir, "video")
        audio_path = find_downloaded_file(task_dir, "audio")
        merge_streams_with_progress(task_id, video_path, audio_path, out_path)

        if out_path.exists():
            update_task(
                task_id,
                status="finished",
                phase="finished",
                phase_label="Ready",
                progress=100.0,
                speed="",
                eta="00:00",
                message="File is ready to save.",
            )
        else:
            update_task(task_id, status="error", error="Prepared file was not created.")
    except Exception as e:
        update_task(task_id, status="error", phase="error", phase_label="Error", error=str(e))
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)

def stream_merging(video_url: str, audio_url: str, filename: str):
    """
    Merge video and audio streams on-the-fly using ffmpeg and stream to browser.
    Uses fragmented MP4 for streamability.
    """
    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=500, detail="ffmpeg not found on PATH.")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i", video_url,
        "-i", audio_url,
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-f", "mp4",
        "-movflags", "frag_keyframe+empty_moov",
        "pipe:1"
    ]
    
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1048576)
    stderr_capture = StderrCapture(proc.stderr)

    def iterator():
        try:
            while True:
                chunk = proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass

    headers = build_attachment_headers(filename)
    return StreamingResponse(iterator(), media_type="video/mp4", headers=headers)


def stream_remote_file(download_url: str, media_type: str, filename: str):
    try:
        upstream = urlopen(UrlRequest(download_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
    except HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream download failed with HTTP {exc.code}.") from exc
    except URLError as exc:
        reason = exc.reason if isinstance(exc.reason, str) else str(exc.reason)
        raise HTTPException(status_code=502, detail=f"Upstream download failed: {reason}") from exc

    headers = build_attachment_headers(filename)
    content_length = upstream.headers.get("Content-Length")
    if content_length:
        headers["Content-Length"] = content_length

    def iterator():
        with upstream:
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    resolved_media_type = media_type or upstream.headers.get_content_type() or "application/octet-stream"
    return StreamingResponse(iterator(), media_type=resolved_media_type, headers=headers)




@app.delete("/api/clear_temp")
def clear_temp():
    """Remove all files from the downloads directory and clear active tasks."""
    try:
        # Clear files on disk
        for f in DOWNLOADS_DIR.glob("*"):
            if f.is_file():
                try:
                    f.unlink()
                except Exception:
                    pass
            elif f.is_dir():
                try:
                    shutil.rmtree(f)
                except Exception:
                    pass
        
        # Clear memory state
        with active_tasks_lock:
            active_tasks.clear()
            
        return {"status": "success", "message": "Temporary files and active tasks cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear temp files: {str(e)}")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/formats")
def get_formats(
    url: str,
    cookies_from_browser: str | None = None,
    auto_close_chrome: bool = False,
):
    normalized = normalize_url(url)
    cookies_from_browser = (cookies_from_browser or "").strip() or None
    data = run_yt_dlp_json(normalized, cookies_from_browser, auto_close_chrome)

    mp4_formats = pick_mp4_formats(data.get("formats") or [])
    title = data.get("title") or "download"

    return {
        "title": title,
        "mp4": mp4_formats,
        "mp3_qualities": ALLOWED_AUDIO_QUALITIES,
    }


@app.get("/api/download_url")
def download_url(
    url: str,
    format_id: str,
    cookies_from_browser: str | None = None,
    auto_close_chrome: bool = False,
):
    """Get a fresh direct CDN URL for a given format."""
    normalized = normalize_url(url)
    cookies_from_browser = (cookies_from_browser or "").strip() or None
    direct = get_direct_url(
        normalized,
        format_id,
        cookies_from_browser,
        auto_close_chrome,
    )
    return {"url": direct}


@app.get("/api/prepare")
def prepare(
    url: str,
    format_id: str,
    background_tasks: BackgroundTasks,
    title: str = "video",
    height: str | None = None,
    cookies_from_browser: str | None = None,
    auto_close_chrome: str | None = None
):
    normalized = normalize_url(url)
    task_id = generate_task_id(normalized, format_id)
    should_close = parse_bool(auto_close_chrome)
    cookies_source = (cookies_from_browser or "").strip() or None
    
    with active_tasks_lock:
        if task_id in active_tasks:
            # Check if it's finished but file is gone
            if active_tasks[task_id]["status"] == "finished":
                filename = active_tasks[task_id].get("filename")
                if not (DOWNLOADS_DIR / filename).exists():
                    del active_tasks[task_id]
        
        # PERSISTENCE CHECK: If not in active_tasks, check if file already exists on disk
        if task_id not in active_tasks:
            filename = build_cached_mp4_filename(title, format_id, height)
            if (DOWNLOADS_DIR / filename).exists():
                active_tasks[task_id] = {
                    "status": "finished",
                    "phase": "finished",
                    "phase_label": "Ready",
                    "progress": 100.0,
                    "speed": "",
                    "eta": "00:00",
                    "filename": filename,
                    "message": "File is ready to save.",
                }
            else:
                active_tasks[task_id] = {
                    "status": "pending",
                    "phase": "pending",
                    "phase_label": "Queued",
                    "progress": 0.0,
                    "speed": "",
                    "eta": "unknown",
                    "filename": filename,
                    "message": "Waiting to start preparation...",
                }
                background_tasks.add_task(
                    background_downloader,
                    task_id, normalized, format_id, filename,
                    cookies_source, should_close
                )

            
        return active_tasks[task_id]


@app.post("/api/download")
def download(
    url: str = Form(...),
    type: str = Form(...),
    title: str = Form("download"),
    format_id: str = Form(None),
    height: str | None = Form(None),
    audio_quality: str = Form(None),
    cookies_from_browser: str = Form(None),
    auto_close_chrome: str = Form(None),
):
    normalized_url = normalize_url(url)
    dtype = type.lower()
    cookies_source = (cookies_from_browser or "").strip() or None
    should_close_chrome = parse_bool(auto_close_chrome)
    if dtype == "mp4":
        if not format_id:
            raise HTTPException(status_code=400, detail="format_id is required for mp4.")
        download_filename = build_download_filename(title, "mp4", build_quality_label(height=height))
            
        # Check if we have a prepared file for this
        task_id = generate_task_id(normalized_url, str(format_id))
        filename = None
        
        with active_tasks_lock:
            task = active_tasks.get(task_id)
            if task and task["status"] == "finished":
                filename = task["filename"]
        
        # If not in active_tasks (e.g. server restart), we try to reconstruct the filename
        if not filename:
            filename = build_cached_mp4_filename(title, format_id, height)
             
        if filename:
            file_path = DOWNLOADS_DIR / filename
            if file_path.exists():
                return FileResponse(
                    path=file_path,
                    filename=download_filename,
                    media_type="video/mp4"
                )


        # Fallback/Default: Get format info to decide
        full_data = run_yt_dlp_json(normalized_url, cookies_source, should_close_chrome)
        formats = full_data.get("formats") or []
        target_fmt = next((f for f in formats if f.get("format_id") == str(format_id)), None)
        
        if not target_fmt:
            raise HTTPException(status_code=400, detail="Format not found.")
            
        is_dash = target_fmt.get("acodec") == "none"
        
        if is_dash:
            # For DASH, we really want them to use /api/prepare first.
            # But if they click directly, we'll use the slow stream_merging as fallback
            # OR better: inform them to wait. For now, keep the old logic but prioritize preparation.
            video_url = target_fmt.get("url") or get_direct_url(
                normalized_url, str(format_id), cookies_source, should_close_chrome
            )
            audio_fmts = [f for f in formats if f.get("vcodec") == "none" and f.get("ext") == "m4a"]
            if not audio_fmts:
                audio_fmts = [f for f in formats if f.get("vcodec") == "none"]
            
            if not audio_fmts:
                return stream_remote_file(video_url, "video/mp4", download_filename)
                
            best_audio = max(audio_fmts, key=lambda f: f.get("tbr") or 0)
            audio_url = best_audio.get("url") or get_direct_url(
                normalized_url, best_audio["format_id"], cookies_source, should_close_chrome
            )
            
            return stream_merging(video_url, audio_url, download_filename)
        else:
            direct = target_fmt.get("url") or get_direct_url(
                normalized_url, str(format_id), cookies_source, should_close_chrome
            )
            return stream_remote_file(direct, target_fmt.get("mime_type") or "video/mp4", download_filename)



    if dtype == "mp3":
        try:
            quality = int(audio_quality)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="audio_quality must be a number.")
        if quality not in ALLOWED_AUDIO_QUALITIES:
            raise HTTPException(status_code=400, detail="Invalid audio quality.")
        if not shutil.which("ffmpeg"):
            raise HTTPException(status_code=500, detail="ffmpeg was not found on PATH.")

        if cookies_source and should_close_chrome:
            close_chrome_processes()
        ydl_cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "-f",
            "bestaudio/best",
            "--no-playlist",
            "--no-part",
            "--no-progress",
            "--js-runtimes",
            "node",
            "--remote-components",
            "ejs:github",
            *cookie_args(cookies_source),
            "-o",
            "-",
            normalized_url,
        ]
        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-vn",
            "-acodec",
            "libmp3lame",
            "-b:a",
            f"{quality}k",
            "-f",
            "mp3",
            "pipe:1",
        ]
        download_filename = build_download_filename(title, "mp3", build_quality_label(audio_quality=quality))
        return stream_pipeline(ydl_cmd, ffmpeg_cmd, "audio/mpeg", download_filename)

    raise HTTPException(status_code=400, detail="type must be mp4 or mp3.")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
