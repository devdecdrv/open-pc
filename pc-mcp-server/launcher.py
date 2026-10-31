"""PyInstaller entry point. Makes startup failures visible instead of silent."""
import os
import sys
import threading
import traceback
from pathlib import Path

APP_DIR = Path.home() / ".pc_mcp_server"


def _report(exc_text: str):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        (APP_DIR / "startup_error.txt").write_text(exc_text, "utf-8")
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "PC MCP Server failed to start.\n\nDetails saved to:\n%s\n\n%s" % (APP_DIR / "startup_error.txt", exc_text[-1200:]),
            "PC MCP Server", 0x10)
    except Exception:
        pass


def main():
    # --noconsole builds have no stdout/stderr; libraries that print would crash.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    sys.excepthook = lambda *a: _report("".join(traceback.format_exception(*a)))
    threading.excepthook = lambda a: _report("".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))
    try:
        from pcmcp.app import main as run
        run()
    except SystemExit:
        raise
    except BaseException:
        _report(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
