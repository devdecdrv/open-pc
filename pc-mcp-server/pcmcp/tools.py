"""All MCP tools. Every tool calls authorize() first. Levels: VIEW < READ < ACT."""
import asyncio
import ctypes
import os
import platform
import subprocess
import time

import pyautogui
import pyperclip
from mcp.server.fastmcp import FastMCP, Image

from . import security as sec
from . import uia, vision
from .security import ACT, READ, VIEW

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.02
MAXOUT = 20000
NO_WINDOW = 0x08000000


def _clip(text: str) -> str:
    return text if len(text) <= MAXOUT else text[:MAXOUT] + f"\n...[truncated, {len(text)} chars total]"


def _real(x, y, space="shot"):
    """Convert screenshot-image coordinates ('shot') or real pixels ('screen') to real pixels."""
    if space == "screen":
        return int(x), int(y)
    s = vision.LAST
    return int(s["left"] + x / s["scale"]), int(s["top"] + y / s["scale"])


def _windows():
    user32 = ctypes.windll.user32
    from ctypes import wintypes
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                r = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                out.append({"hwnd": int(hwnd), "title": buf.value, "rect": [r.left, r.top, r.right, r.bottom]})
        return True

    user32.EnumWindows(cb, 0)
    return out


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def register(mcp: FastMCP):
    # ------------------------------------------------------------------ VIEW tools
    @mcp.tool()
    def screenshot(monitor: int = 0, region: list[int] | None = None, max_side: int = 1568,
                   quality: int = 70, with_cursor: bool = True):
        """Take a screenshot. monitor 0 = all screens, 1.. = one monitor. region = [x, y, width, height]
        in real pixels. Returned image is scaled to max_side; click()/drag() use image coordinates by default."""
        sec.authorize("screenshot", VIEW)
        img, left, top = vision.grab(monitor, region)
        if with_cursor:
            vision.draw_cursor(img, left, top)
        data, scale = vision.encode(img, max_side, quality)
        vision.LAST.update(left=left, top=top, scale=scale)
        w, h = img.size
        cap = (f"Image {int(w * scale)}x{int(h * scale)} = {w}x{h} real px x {scale:.3f}; origin ({left},{top}). "
               "click/drag/move_mouse default to coordinates of THIS image (space='shot'); use space='screen' for real pixels.")
        return [Image(data=data, format="jpeg"), cap]

    @mcp.tool()
    def look_back(seconds: int = 10, n: int = 6):
        """Filmstrip of recent screen frames (oldest first, labelled with age) - shows what just happened."""
        sec.authorize("look_back", VIEW)
        data = vision.contact_sheet(seconds, n)
        if not data:
            return "No frames buffered yet."
        return [Image(data=data, format="jpeg"), f"Up to {n} frames from the last {seconds}s; labels show age."]

    @mcp.tool()
    async def watch(until: str = "change", timeout: float = 15.0, region: list[int] | None = None,
                    max_side: int = 1280):
        """Wait (long-poll) then return a screenshot. until='change' returns when the screen/region changes;
        until='idle' returns when it has been still for ~0.8 s (e.g. page finished loading).
        Also returns the real-pixel bounding box of what changed."""
        sec.authorize("watch", VIEW, until)
        if until not in ("change", "idle"):
            return "Unsupported 'until'. Use 'change' or 'idle' (text:<string> needs OCR - not built yet)."
        timeout = max(0.5, min(float(timeout), 60.0))
        end = time.time() + timeout
        img, left, top = vision.grab(0, region)
        prev = vision.signature(img)
        stable_since, bbox_real, reason = time.time(), None, "timeout"
        while time.time() < end:
            await asyncio.sleep(0.2)
            img, left, top = vision.grab(0, region)
            sig = vision.signature(img)
            frac, bbox = vision.diff(prev, sig)
            moved = frac > 0.002
            if moved:
                bbox_real = vision.bbox_to_real(bbox, img.width, img.height, left, top)
                stable_since = time.time()
                if until == "change":
                    reason = "changed"
                    break
            elif until == "idle" and time.time() - stable_since >= 0.8:
                reason = "idle"
                break
            prev = sig
        data, scale = vision.encode(img, max_side, 70)
        vision.LAST.update(left=left, top=top, scale=scale)
        return [Image(data=data, format="jpeg"),
                f"watch result: {reason}. changed area (real px): {bbox_real}. coords follow this image."]

    @mcp.tool()
    def screen_info():
        """Monitors (real pixels), cursor position, current permission mode."""
        sec.authorize("screen_info", VIEW)
        import mss
        with mss.mss() as sct:
            mons = [dict(m) for m in sct.monitors]
        return {"monitors": mons, "cursor": list(pyautogui.position()), "mode": sec.current_mode()}

    @mcp.tool()
    def system_info():
        """OS, CPU count, admin status, permission mode."""
        sec.authorize("system_info", VIEW)
        return {"os": platform.platform(), "cpus": os.cpu_count(), "admin": is_admin(),
                "mode": sec.current_mode(), "unrestricted": sec.CFG["unrestricted"]}

    @mcp.tool()
    def list_windows():
        """Visible top-level windows with titles and rectangles."""
        sec.authorize("list_windows", VIEW)
        return _windows()

    @mcp.tool()
    def read_screen(window_only: bool = True, max_items: int = 150):
        """Text view of the UI via Windows UI Automation: element names, types, click centers (real pixels).
        Faster and more reliable than reading pixels. window_only=False reads the whole desktop."""
        sec.authorize("read_screen", VIEW)
        return uia.read_screen(window_only, max_items)

    @mcp.tool()
    def wait(seconds: float = 1.0):
        """Sleep up to 30 s."""
        sec.authorize("wait", VIEW)
        time.sleep(max(0.0, min(float(seconds), 30.0)))
        return "ok"

    # ------------------------------------------------------------------ ACT tools (input)
    @mcp.tool()
    def focus_window(title: str):
        """Bring the first window whose title contains `title` to the front."""
        sec.authorize("focus_window", ACT, title)
        u = ctypes.windll.user32
        for w in _windows():
            if title.lower() in w["title"].lower():
                u.keybd_event(0x12, 0, 0, 0)          # ALT trick so SetForegroundWindow is allowed
                u.ShowWindow(w["hwnd"], 9)
                u.SetForegroundWindow(w["hwnd"])
                u.keybd_event(0x12, 0, 2, 0)
                return f"focused: {w['title']}"
        return "no matching window"

    @mcp.tool()
    def click(x: int, y: int, button: str = "left", clicks: int = 1, space: str = "shot"):
        """Click. space='shot' = last screenshot's image coordinates, 'screen' = real pixels."""
        rx, ry = _real(x, y, space)
        sec.authorize("click", ACT, f"{button} x{clicks} at {rx},{ry}")
        pyautogui.moveTo(rx, ry, duration=0.12, tween=pyautogui.easeInOutQuad)
        pyautogui.click(button=button, clicks=max(1, min(clicks, 3)), interval=0.08)
        return f"clicked real px ({rx},{ry})"

    @mcp.tool()
    def click_element(name: str, control_type: str | None = None, exact: bool = False, window_only: bool = True):
        """Find a UI element by (partial) name via UI Automation and click its center."""
        sec.authorize("click_element", ACT, name)
        hits = uia.find(name, control_type, exact, window_only)
        if not hits:
            return f"no element matching '{name}'"
        h = hits[0]
        pyautogui.moveTo(h["x"], h["y"], duration=0.12)
        pyautogui.click()
        return f"clicked '{h['name']}' ({h['type']}) at {h['x']},{h['y']}; other matches: {len(hits) - 1}"

    @mcp.tool()
    def move_mouse(x: int, y: int, space: str = "shot"):
        """Move the pointer."""
        rx, ry = _real(x, y, space)
        sec.authorize("move_mouse", ACT, f"{rx},{ry}")
        pyautogui.moveTo(rx, ry, duration=0.12)
        return "ok"

    @mcp.tool()
    def drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5, space: str = "shot"):
        """Press at (x1,y1), drag to (x2,y2), release."""
        a, b = _real(x1, y1, space), _real(x2, y2, space)
        sec.authorize("drag", ACT, f"{a}->{b}")
        pyautogui.moveTo(*a, duration=0.1)
        pyautogui.dragTo(*b, duration=max(0.1, duration), button="left")
        return "ok"

    @mcp.tool()
    def scroll(amount: int, x: int | None = None, y: int | None = None, space: str = "shot"):
        """Scroll wheel; positive = up, negative = down."""
        sec.authorize("scroll", ACT, str(amount))
        if x is not None and y is not None:
            pyautogui.moveTo(*_real(x, y, space), duration=0.05)
        pyautogui.scroll(int(amount))
        return "ok"

    @mcp.tool()
    def type_text(text: str):
        """Type text into the focused control. Long or non-ASCII text is pasted via the clipboard."""
        sec.authorize("type_text", ACT, f"{len(text)} chars")
        if text.isascii() and len(text) <= 200 and "\n" not in text:
            pyautogui.write(text, interval=0.01)
        else:
            old = None
            try:
                old = pyperclip.paste()
            except Exception:
                pass
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)
            if old is not None:
                pyperclip.copy(old)
        return "typed"

    @mcp.tool()
    def press_key(keys: str, presses: int = 1):
        """Press a key or combo, e.g. 'enter', 'ctrl+c', 'alt+tab', 'win+r'."""
        sec.authorize("press_key", ACT, keys)
        parts = [k.strip().lower() for k in keys.split("+") if k.strip()]
        for _ in range(max(1, min(presses, 20))):
            pyautogui.hotkey(*parts) if len(parts) > 1 else pyautogui.press(parts[0])
        return "ok"

    @mcp.tool()
    def open_app(target: str):
        """Open an app, file, folder or URL (like Win+R)."""
        sec.authorize("open_app", ACT, target)
        os.startfile(target)  # noqa: S606
        return "opened"

    @mcp.tool()
    def set_clipboard(text: str):
        """Replace clipboard text."""
        sec.authorize("set_clipboard", ACT, f"{len(text)} chars")
        pyperclip.copy(text)
        return "ok"

    @mcp.tool()
    def run_command(command: str, shell: str = "powershell", timeout: int = 30, background: bool = False):
        """Run a PowerShell (default) or cmd command. Output truncated. background=True returns immediately."""
        sec.authorize("run_command", ACT, command[:200])
        sec.check_command(command)
        args = ["cmd.exe", "/c", command] if shell == "cmd" else \
               ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
        if background:
            p = subprocess.Popen(args, creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"started pid {p.pid}"
        try:
            r = subprocess.run(args, capture_output=True, timeout=max(1, min(timeout, 300)), creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            return "timed out"
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        return _clip(f"exit {r.returncode}\n{out}")

    @mcp.tool()
    def write_file(path: str, content: str, append: bool = False):
        """Write a text file."""
        p = sec.resolve_path(path)
        sec.authorize("write_file", ACT, str(p))
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a" if append else "w", encoding="utf-8", newline="") as f:
            f.write(content)
        return f"wrote {len(content)} chars to {p}"

    # ------------------------------------------------------------------ READ tools
    @mcp.tool()
    def get_clipboard():
        """Read clipboard text."""
        sec.authorize("get_clipboard", READ)
        return _clip(pyperclip.paste())

    @mcp.tool()
    def list_directory(path: str = "~"):
        """List a folder."""
        p = sec.resolve_path(path)
        sec.authorize("list_directory", READ, str(p))
        items = []
        for e in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))[:500]:
            try:
                items.append({"name": e.name, "dir": e.is_dir(), "size": e.stat().st_size if e.is_file() else None})
            except OSError:
                items.append({"name": e.name, "dir": e.is_dir(), "size": None})
        return items

    @mcp.tool()
    def read_file(path: str, max_bytes: int = 100000):
        """Read a text file (UTF-8, errors replaced)."""
        p = sec.resolve_path(path)
        sec.authorize("read_file", READ, str(p))
        with open(p, "rb") as f:
            data = f.read(max(1, min(max_bytes, 2_000_000)))
        return _clip(data.decode("utf-8", "replace"))
