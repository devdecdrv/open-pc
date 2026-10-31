"""Persistent config in ~/.pc_mcp_server/config.json. Never logged, never readable by tools."""
import json
import secrets
import threading
from pathlib import Path

APP_DIR = Path.home() / ".pc_mcp_server"
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "actions.log"

DEFAULTS = {
    "token": "",
    "port": 8765,
    "start_full": False,      # start in FULL mode
    "never_expire": False,    # FULL mode does not time out
    "unrestricted": False,    # all drives + command blocklist off
    "full_minutes": 30,
    "tunnel_token": "",       # Cloudflare named-tunnel token (permanent address)
    "public_url": "",         # your fixed https URL for that named tunnel
}
CFG = dict(DEFAULTS)
_lock = threading.Lock()


def save():
    with _lock:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(CFG, indent=2), "utf-8")


def new_token():
    CFG["token"] = secrets.token_urlsafe(32)
    save()


def load():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            CFG.update(json.loads(CONFIG_FILE.read_text("utf-8")))
        except Exception:
            pass
    if not CFG.get("token"):
        new_token()
    return CFG
