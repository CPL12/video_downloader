import json
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Form, BackgroundTasks
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DOWNLOADS_DIR = STATIC_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Tracks background preparation tasks: {task_id: {status, progress, speed, filename, etc.}}
active_tasks = {}
active_tasks_lock = threading.Lock()

ALLOWED_AUDIO_QUALITIES = [128, 192, 256, 320]
ALLOWED_COOKIE_SOURCES = {"chrome"}
MAX_STDERR_BYTES = 65536
CHROME_COOKIE_LOCK = "Could not copy Chrome cookie database"

app = FastAPI(title="Local Media Downloader")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

def cleanup_old_downloads():
    """Remove files older than 1 hour from the downloads directory."""
    import time
    now = time.time()
    try:
        for f in DOWNLOADS_DIR.glob("*"):
            if f.is_file() and (now - f.stat().st_mtime) > 3600:
                f.unlink()
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
    cleaned = re.sub(r"[^a-zA-Z0-9 _.-]", "_", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "download"


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

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }
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

def background_downloader(task_id: str, url: str, format_id: str, filename: str, cookies: str | None, auto_close: bool):
    out_path = DOWNLOADS_DIR / filename
    temp_path = out_path.with_suffix(".tmp")
    
    # We use -f format+bestaudio to ensure merging
    # --concurrent-fragments 5 for speed
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", f"{format_id}+bestaudio/best",
        "--merge-output-format", "mp4",
        "--concurrent-fragments", "5",
        "--no-playlist",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        *cookie_args(cookies),
        "--postprocessor-args", "ffmpeg:-c:a aac -b:a 192k",
        "-o", str(out_path),
        url
    ]
    
    with active_tasks_lock:
        active_tasks[task_id]["status"] = "downloading"
        active_tasks[task_id]["filename"] = filename

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in proc.stdout:
            info = parse_download_progress(line)
            if info:
                with active_tasks_lock:
                    active_tasks[task_id].update(info)
        
        # After the download/progress loop ends, we're usually in the merging phase
        with active_tasks_lock:
            active_tasks[task_id]["status"] = "merging"
            active_tasks[task_id]["progress"] = 100.0

        proc.wait()
        if proc.returncode == 0 and out_path.exists():
            with active_tasks_lock:
                active_tasks[task_id]["status"] = "finished"
                active_tasks[task_id]["progress"] = 100.0
        else:
            with active_tasks_lock:
                active_tasks[task_id]["status"] = "error"
                active_tasks[task_id]["error"] = "yt-dlp failed to download or merge."
    except Exception as e:
        with active_tasks_lock:
            active_tasks[task_id]["status"] = "error"
            active_tasks[task_id]["error"] = str(e)

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

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return StreamingResponse(iterator(), media_type="video/mp4", headers=headers)




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
            safe_title = sanitize_filename(title)
            filename = f"{safe_title}_{format_id}.mp4"
            if (DOWNLOADS_DIR / filename).exists():
                active_tasks[task_id] = {
                    "status": "finished",
                    "progress": 100.0,
                    "speed": "cached",
                    "eta": "00:00",
                    "filename": filename
                }
            else:
                active_tasks[task_id] = {
                    "status": "pending",
                    "progress": 0.0,
                    "speed": "0 KiB/s",
                    "eta": "unknown",
                    "filename": filename
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
    height: str = Form(None),
    audio_quality: str = Form(None),
    cookies_from_browser: str = Form(None),
    auto_close_chrome: str = Form(None),
):
    normalized_url = normalize_url(url)
    dtype = type.lower()
    cookies_source = (cookies_from_browser or "").strip() or None
    should_close_chrome = parse_bool(auto_close_chrome)
    safe_title = sanitize_filename(title)

    if dtype == "mp4":
        if not format_id:
            raise HTTPException(status_code=400, detail="format_id is required for mp4.")
            
        # Check if we have a prepared file for this
        task_id = generate_task_id(normalized_url, str(format_id))
        filename = None
        
        with active_tasks_lock:
            task = active_tasks.get(task_id)
            if task and task["status"] == "finished":
                filename = task["filename"]
        
        # If not in active_tasks (e.g. server restart), we try to reconstruct the filename
        if not filename:
             filename = f"{safe_title}_{format_id}.mp4"
             
        if filename:
            file_path = DOWNLOADS_DIR / filename
            if file_path.exists():
                return FileResponse(
                    path=file_path,
                    filename=f"{safe_title}.mp4",
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
                return RedirectResponse(url=video_url, status_code=303)
                
            best_audio = max(audio_fmts, key=lambda f: f.get("tbr") or 0)
            audio_url = best_audio.get("url") or get_direct_url(
                normalized_url, best_audio["format_id"], cookies_source, should_close_chrome
            )
            
            height_val = target_fmt.get("height") or "highres"
            return stream_merging(video_url, audio_url, f"{safe_title}.mp4")
        else:
            # Progressive, just redirect
            direct = target_fmt.get("url") or get_direct_url(
                normalized_url, str(format_id), cookies_source, should_close_chrome
            )
            return RedirectResponse(url=direct, status_code=303)



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
        return stream_pipeline(ydl_cmd, ffmpeg_cmd, "audio/mpeg", f"{safe_title}.mp3")

    raise HTTPException(status_code=400, detail="type must be mp4 or mp3.")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
