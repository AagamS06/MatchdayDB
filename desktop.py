"""Double-click entry point: run MatchdayDB without a terminal.

This is the file a packaged build's launcher (``MatchdayDB.exe`` on Windows,
``MatchdayDB`` inside ``MatchdayDB.app`` on macOS) actually runs, and it also
works unpackaged with plain ``python desktop.py`` -- handy for testing the
desktop experience before spending time on a PyInstaller build.

It does three things `python app.py` on its own doesn't:
1. Picks a free port instead of failing if 8000 is already taken.
2. Opens the dashboard in the user's default browser once the server is up.
3. Writes a log file next to the database (see config.DATA_ROOT) so a
   packaged build -- which has no visible console to read errors from on
   some platforms -- still leaves a trail if something goes wrong.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from app import create_app
from config import DATA_ROOT, Settings, load_env_file

HOST = "127.0.0.1"
PREFERRED_PORT = 8000
LOG_FILE = DATA_ROOT / "matchdaydb.log"

# Keeps the ctypes callback below alive for the life of the process --
# without a reference somewhere, Python can garbage-collect it and Windows
# silently stops calling it.
_console_close_handler = None


def _install_windows_close_handler() -> None:
    """Make closing the console window actually stop the server.

    On Windows, clicking a console's X button sends CTRL_CLOSE_EVENT, which
    Python doesn't turn into a KeyboardInterrupt the way it does Ctrl+C.
    Left alone, the OS just gives the process up to ~5 seconds to exit on
    its own -- and if anything blocks during that window (a logging call
    writing to the stdout handle the closing console just invalidated,
    uvicorn's graceful-shutdown sequence waiting on an open connection),
    the process can be left stuck: still bound to the port, still "running"
    with no window to see or control it, which is what looks like
    localhost "freezing" instead of the app actually stopping. Registering
    an explicit handler that exits immediately on close sidesteps all of
    that -- there's nothing left to hang.
    """
    global _console_close_handler
    if sys.platform != "win32":
        return
    import ctypes

    handler_routine = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

    def handler(event: int) -> bool:
        if event in (2, 5, 6):  # CTRL_CLOSE, CTRL_LOGOFF, CTRL_SHUTDOWN
            os._exit(0)
        return False

    _console_close_handler = handler_routine(handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_close_handler, True)


def find_free_port(preferred: int = PREFERRED_PORT) -> int:
    """Use the preferred port if it's free, otherwise let the OS pick one."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((HOST, port))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise RuntimeError("Could not find a free port to listen on.")


def open_browser_when_ready(url: str, stop: threading.Event) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not stop.is_set():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            try:
                probe.connect((HOST, int(url.rsplit(":", 1)[1].rstrip("/"))))
            except OSError:
                time.sleep(0.2)
                continue
        webbrowser.open(url)
        return
    logging.getLogger("desktop").warning("Server didn't come up in time; not opening a browser tab.")


def main() -> None:
    _install_windows_close_handler()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log = logging.getLogger("desktop")

    load_env_file()
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        log.error("Configuration error: %s", exc)
        print(f"\nMatchdayDB couldn't start: {exc}\n")
        input("Press Enter to close this window...")
        return

    port = find_free_port()
    url = f"http://{HOST}:{port}/"
    print(f"\nMatchdayDB is starting at {url}")
    print("Your browser will open automatically. Close this window to stop the server.\n")
    log.info("Data directory: %s", DATA_ROOT)

    stop = threading.Event()
    opener = threading.Thread(target=open_browser_when_ready, args=(url, stop), daemon=True)
    opener.start()

    try:
        uvicorn.run(
            create_app(settings, bootstrap=True),
            host=HOST,
            port=port,
            access_log=False,
            log_config=None,
        )
    except OSError as exc:
        log.error("Server failed to start: %s", exc)
        print(f"\nMatchdayDB couldn't start: {exc}\n")
        input("Press Enter to close this window...")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
