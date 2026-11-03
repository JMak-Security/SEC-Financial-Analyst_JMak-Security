"""Start the local Streamlit app, open it when ready, and clean up on exit."""

from __future__ import annotations

import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PROJECT_DIR = Path(__file__).resolve().parent
APP_PATH = PROJECT_DIR / "app.py"
PORT = 8501
URL = f"http://127.0.0.1:{PORT}"
HEALTH_URL = f"{URL}/_stcore/health"


def wait_until_ready(server: subprocess.Popen[bytes], timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        exit_code = server.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"Streamlit exited before becoming ready (exit code {exit_code})."
            )
        try:
            with urlopen(HEALTH_URL, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for Streamlit at {URL}.")


def main() -> int:
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_PATH),
        "--server.headless",
        "true",
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(PORT),
        "--browser.gatherUsageStats",
        "false",
    ]
    server = subprocess.Popen(command, cwd=PROJECT_DIR)
    try:
        wait_until_ready(server)
        print(f"SEC Financial Analyst is ready at {URL}", flush=True)
        if not webbrowser.open_new_tab(URL):
            print(f"Could not open a browser automatically. Visit {URL}", flush=True)
        return server.wait()
    except KeyboardInterrupt:
        print("\nStopping the SEC Financial Analyst...", flush=True)
        return 130
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
