"""Permission model, path rules, command blocklist. No Windows-only imports (unit-testable anywhere)."""
import re
import tempfile
import time
from pathlib import Path

from .config import APP_DIR, CFG, LOG_FILE

VIEW, READ, ACT = 0, 1, 2
LEVEL_NAMES = {VIEW: "VIEW", READ: "READ", ACT: "ACT"}
MODES = ("SAFE", "ASK", "FULL")


class _State:
    mode = "SAFE"
    full_until = 0.0
    ask_fn = None   # callable(tool, detail) -> bool, set by the UI
    log_fn = None   # callable(line) -> None, set by the UI


STATE = _State()


def log(msg: str):
    line = time.strftime("%H:%M:%S ") + msg[:300]
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d ") + line + "\n")
    except Exception:
        pass
    if STATE.log_fn:
        try:
            STATE.log_fn(line)
        except Exception:
            pass


def current_mode() -> str:
    if STATE.mode == "FULL" and not CFG["never_expire"] and time.time() > STATE.full_until:
        STATE.mode = "SAFE"
        log("FULL mode expired -> SAFE")
    return STATE.mode


def set_mode(mode: str):
    if mode not in MODES:
        raise ValueError(mode)
    STATE.mode = mode
    if mode == "FULL":
        STATE.full_until = time.time() + 60 * int(CFG.get("full_minutes", 30))
    log(f"MODE -> {mode}")


def authorize(tool: str, level: int, detail: str = ""):
    """Raise PermissionError unless the current mode allows this tool."""
    mode = current_mode()
    tag = f"[{mode}] {tool} {detail}".strip()
    if level == VIEW:
        log(tag)
        return
    if mode == "SAFE":
        log("BLOCKED " + tag)
        raise PermissionError(
            f"'{tool}' needs {LEVEL_NAMES[level]} access but the PC is in SAFE mode. "
            "Ask the owner to switch to ASK or FULL in the app window."
        )
    if level == READ or mode == "FULL":
        log(tag)
        return
    # ASK mode + ACT: the owner must approve
    ok = False
    if STATE.ask_fn:
        try:
            ok = bool(STATE.ask_fn(tool, detail))
        except Exception:
            ok = False
    if not ok:
        log("DENIED " + tag)
        raise PermissionError(f"The owner did not approve '{tool}'.")
    log("ALLOWED " + tag)


# ---- command blocklist (a speed bump, NOT a sandbox) -------------------------------
_BLOCK = [
    r"\bformat(\.com)?\s+[a-z]:", r"\bdiskpart\b", r"\bbcdedit\b", r"\bcipher\s+/w",
    r"\bvssadmin\b.*\bdelete\b", r"\bwbadmin\b.*\bdelete\b", r"\bmanage-bde\b",
    r"\brm\s+-[a-z]*r[a-z]*f?\s+[\"']?[/\\]", r"\bdel\s+/[sfq].*\b[a-z]:\\\s*$",
    r"remove-item\b.*-recurse.*\b[a-z]:\\\s*$", r"\breg\s+delete\s+hk(lm|ey_local_machine)",
    r"\bset-mppreference\b.*disable", r"\bstop-computer\b", r"\bshutdown\b",
]
_BLOCK_RE = [re.compile(p, re.I) for p in _BLOCK]


def touches_protected_text(text: str) -> bool:
    t = text.lower().replace("/", "\\")
    return ".pc_mcp_server" in t


def check_command(cmd: str):
    if touches_protected_text(cmd):
        raise PermissionError("Commands may not touch the app's config folder.")
    if CFG["unrestricted"]:
        return
    for rx in _BLOCK_RE:
        if rx.search(cmd):
            raise PermissionError("Command blocked by the safety blocklist (owner can enable Unrestricted).")


# ---- file paths ---------------------------------------------------------------------
def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_path(p: str) -> Path:
    path = Path(p).expanduser().resolve()
    if path == APP_DIR.resolve() or _is_inside(path, APP_DIR.resolve()):
        raise PermissionError("The app's config folder is protected.")
    if CFG["unrestricted"]:
        return path
    roots = [Path.home().resolve(), Path(tempfile.gettempdir()).resolve()]
    if not any(_is_inside(path, r) for r in roots):
        raise PermissionError("Outside your user folder. Owner can enable Unrestricted to allow all drives.")
    return path
