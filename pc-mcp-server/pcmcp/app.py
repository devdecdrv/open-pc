"""App wiring: server thread, tunnel, UI, single-instance lock, panic hotkey, --selftest."""
import ctypes
import json
import os
import socket
import sys
import threading
import time
import urllib.request

from . import __version__
from . import config
from . import security as sec
from .config import APP_DIR, CFG
from .gate import Gate

_mutex = None


def build_asgi():
    from mcp.server.fastmcp import FastMCP
    from . import tools
    kw = dict(json_response=True, stateless_http=True)   # quick tunnels have no SSE
    try:
        from mcp.server.transport_security import TransportSecuritySettings
        kw["transport_security"] = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    except ImportError:
        pass
    mcp = FastMCP("PC MCP Server", **kw)
    tools.register(mcp)
    return Gate(mcp.streamable_http_app(), lambda: CFG["token"])


class ServerThread(threading.Thread):
    def __init__(self, app, port):
        super().__init__(daemon=True, name="uvicorn")
        import uvicorn

        class _S(uvicorn.Server):
            def install_signal_handlers(self):  # we run in a non-main thread
                pass

        self.server = _S(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False))

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True


def _port_free(p):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", p)) != 0


def pick_port(preferred):
    for p in range(preferred, preferred + 11):
        if _port_free(p):
            return p
    raise RuntimeError("No free port near %d" % preferred)


def single_instance(wait=6.0):
    """Named mutex. Waits a few seconds so 'relaunch as admin' can take over."""
    global _mutex
    end = time.time() + wait
    while True:
        h = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\PC_MCP_Server_Singleton")
        if ctypes.windll.kernel32.GetLastError() != 183:
            _mutex = h
            return True
        ctypes.windll.kernel32.CloseHandle(h)
        if time.time() > end:
            return False
        time.sleep(0.4)


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def panic_hotkey(on_panic):
    """Ctrl+Alt+Shift+K -> back to SAFE and stop the tunnel."""
    from ctypes import wintypes
    u = ctypes.windll.user32
    if not u.RegisterHotKey(None, 1, 0x0001 | 0x0002 | 0x0004, 0x4B):
        sec.log("could not register panic hotkey")
        return
    msg = wintypes.MSG()
    while u.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == 0x0312:
            on_panic()


def _post(url, payload):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def selftest() -> int:
    """Headless check used by CI: server starts, gate works, MCP lists tools."""
    lines, ok = [], True

    def rec(name, passed, extra=""):
        nonlocal ok
        ok = ok and passed
        lines.append(f"{'PASS' if passed else 'FAIL'} {name} {extra}")

    try:
        port = pick_port(18765)
        srv = ServerThread(build_asgi(), port)
        srv.start()
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/health", timeout=1).read()
                break
            except Exception:
                time.sleep(0.2)
        rec("health", True)
        try:
            urllib.request.urlopen(base + "/mcp", timeout=5)
            rec("unauth rejected", False)
        except urllib.error.HTTPError as e:
            rec("unauth rejected", e.code == 403, str(e.code))
        url = f"{base}/s/{CFG['token']}/mcp"
        _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "selftest", "version": "1"}}})
        body = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        rec("tools/list", "screenshot" in body and "read_screen" in body, f"{len(body)} bytes")
        try:
            from . import vision
            img, _, _ = vision.grab(0)
            rec("capture", img.width > 0, f"{img.size}")
        except Exception as e:
            rec("capture (non-fatal on headless runners)", True, repr(e))
        srv.stop()
    except Exception as e:
        import traceback
        rec("exception", False, traceback.format_exc())
    (APP_DIR / "selftest.txt").write_text("\n".join(lines), "utf-8")
    return 0 if ok else 1


def main():
    enable_dpi_awareness()
    config.load()
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if not single_instance():
        import tkinter.messagebox as mb
        mb.showerror("PC MCP Server", "Another copy is already running (check the taskbar / Task Manager).")
        return
    from . import tools, vision
    from .tunnel import Tunnel
    from .ui import UI

    port = pick_port(int(CFG["port"]))
    server = ServerThread(build_asgi(), port)
    server.start()
    vision.start()
    tunnel = Tunnel(port)
    if CFG["start_full"]:
        sec.set_mode("FULL")

    def quit_all():
        sec.log("quitting")
        tunnel.stop()
        server.stop()
        os._exit(0)

    ui = UI(port, tunnel, tools.is_admin(), quit_all)
    threading.Thread(target=panic_hotkey, args=(lambda: (sec.set_mode("SAFE"), tunnel.stop(), sec.log("PANIC")),),
                     daemon=True).start()
    sec.log(f"PC MCP Server {__version__} started on port {port} (admin={tools.is_admin()})")
    ui.run()
