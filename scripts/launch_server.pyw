import os
import sys
import traceback
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[1]
STDOUT_LOG = ROOT / "server.stdout.log"
STDERR_LOG = ROOT / "server.stderr.log"


class LineBufferedLog:
    def __init__(self, handle):
        self._handle = handle

    def write(self, data):
        if not data:
            return 0
        self._handle.write(data)
        self._handle.flush()
        return len(data)

    def flush(self):
        self._handle.flush()

    def isatty(self):
        return False


def main():
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    with STDOUT_LOG.open("w", encoding="utf-8") as stdout_handle, STDERR_LOG.open("w", encoding="utf-8") as stderr_handle:
        sys.stdout = LineBufferedLog(stdout_handle)
        sys.stderr = LineBufferedLog(stderr_handle)

        try:
            uvicorn.run(
                "main:app",
                host="127.0.0.1",
                port=8000,
                reload=False,
            )
        except Exception:
            traceback.print_exc(file=stderr_handle)
            stderr_handle.flush()
            raise


if __name__ == "__main__":
    main()
