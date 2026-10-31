"""Runs the bundled cloudflared. Quick tunnel (random URL) or a named tunnel (permanent URL)."""
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import CFG
from .security import log

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
NO_WINDOW = 0x08000000


def find_cloudflared():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "cloudflared.exe"
    if p.exists():
        return str(p)
    return shutil.which("cloudflared")


class Tunnel:
    def __init__(self, port: int):
        self.port = port
        self.url = ""
        self.status = "stopped"
        self._want = False
        self._proc = None
        self._thread = None

    def base_url(self) -> str:
        return (CFG.get("public_url") or "").rstrip("/") or self.url

    def start(self):
        if self._want:
            return
        self._want = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="tunnel")
        self._thread.start()

    def stop(self):
        self._want = False
        self.status = "stopped"
        self.url = ""
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def _run(self):
        exe = find_cloudflared()
        if not exe:
            self.status = "cloudflared not found"
            self._want = False
            return
        while self._want:
            named = bool(CFG.get("tunnel_token"))
            args = [exe, "tunnel", "--no-autoupdate"]
            args += ["run", "--token", CFG["tunnel_token"]] if named else ["--url", f"http://127.0.0.1:{self.port}"]
            self.status = "starting"
            try:
                self._proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                              encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
                for line in self._proc.stdout:
                    if not self._want:
                        break
                    m = URL_RE.search(line)
                    if m and not named:
                        self.url = m.group(0)
                        self.status = "online"
                        log("tunnel online")
                    elif named and "Registered tunnel connection" in line:
                        self.status = "online"
                        log("named tunnel online")
                self._proc.wait()
            except Exception as e:
                log(f"tunnel error: {e}")
            if self._want:
                self.status = "restarting"
                self.url = ""
                time.sleep(5)
        self.status = "stopped"
