from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
OVERVIEW_PATH = ROOT / "docs" / "screenshots" / "overview.png"
WORKFLOW_PATH = ROOT / "docs" / "screenshots" / "workflow.png"
STDOUT_LOG = ROOT / "server.stdout.log"
STDERR_LOG = ROOT / "server.stderr.log"


def wait_for_server(url: str, attempts: int = 30, delay: float = 0.5) -> None:
    for _ in range(attempts):
        time.sleep(delay)
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
    raise RuntimeError("Server did not start in time")


def capture(chrome_path: Path, output_path: Path, url: str, window_size: str) -> None:
    subprocess.run(
        [
            str(chrome_path),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={window_size}",
            "--virtual-time-budget=4000",
            f"--screenshot={output_path}",
            url,
        ],
        check=True,
        cwd=ROOT,
    )


def main() -> None:
    if not CHROME_PATH.exists():
        raise FileNotFoundError(f"Chrome not found at {CHROME_PATH}")

    python_exe = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        python_exe = Path(sys.executable)

    with STDOUT_LOG.open("w", encoding="utf-8") as out, STDERR_LOG.open("w", encoding="utf-8") as err:
        server = subprocess.Popen(
            [
                str(python_exe),
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=ROOT,
            stdout=out,
            stderr=err,
        )

        try:
            wait_for_server("http://127.0.0.1:8000/")
            capture(CHROME_PATH, OVERVIEW_PATH, "http://127.0.0.1:8000/?demo=overview&theme=light", "1400,1320")
            capture(CHROME_PATH, WORKFLOW_PATH, "http://127.0.0.1:8000/?demo=workflow&theme=light", "1400,1480")
            print("Updated overview.png and workflow.png")
        finally:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    main()
