"""Screen capture, change detection, short ring buffer ("look back"). Uses mss + Pillow only."""
import io
import threading
import time
from collections import deque

from PIL import Image, ImageChops, ImageDraw

LAST = {"left": 0, "top": 0, "scale": 1.0}   # geometry of the most recent screenshot
RING = deque(maxlen=90)                       # (timestamp, thumbnail)
_ring_lock = threading.Lock()
_started = False
SIG_W, SIG_H = 96, 54


def grab(monitor: int = 0, region=None):
    """Return (PIL image, left, top). monitor 0 = all screens, 1.. = single monitor."""
    import mss
    with mss.mss() as sct:
        if region:
            x, y, w, h = [int(v) for v in region]
            if w <= 0 or h <= 0:
                raise ValueError("region must be [x, y, width, height] with positive size")
            box = {"left": x, "top": y, "width": w, "height": h}
        else:
            mons = sct.monitors
            box = mons[monitor] if 0 <= monitor < len(mons) else mons[0]
        raw = sct.grab(box)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    return img, box["left"], box["top"]


def draw_cursor(img, left, top):
    try:
        import pyautogui
        x, y = pyautogui.position()
    except Exception:
        return
    x, y = x - left, y - top
    d = ImageDraw.Draw(img)
    pts = [(x, y), (x, y + 18), (x + 5, y + 14), (x + 9, y + 22), (x + 12, y + 20), (x + 8, y + 13), (x + 14, y + 13)]
    d.polygon(pts, fill=(255, 255, 255), outline=(0, 0, 0))


def encode(img, max_side=1568, quality=70):
    scale = 1.0
    if max_side and max(img.size) > max_side:
        scale = max_side / max(img.size)
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=max(20, min(95, int(quality))))
    return buf.getvalue(), scale


def signature(img):
    return img.convert("L").resize((SIG_W, SIG_H), Image.BILINEAR)


def diff(a, b, thresh=24):
    """Return (fraction of changed cells 0..1, bbox in signature cells or None)."""
    d = ImageChops.difference(a, b).point(lambda p: 255 if p > thresh else 0)
    changed = d.histogram()[255]
    return changed / float(SIG_W * SIG_H), d.getbbox()


def bbox_to_real(bbox, width, height, left, top):
    if not bbox:
        return None
    x0, y0, x1, y1 = bbox
    return [int(left + x0 / SIG_W * width), int(top + y0 / SIG_H * height),
            int(left + x1 / SIG_W * width), int(top + y1 / SIG_H * height)]


# ---- background ring buffer ---------------------------------------------------------
def _loop():
    prev_sig, last_store = None, 0.0
    while True:
        try:
            img, _, _ = grab(0)
            sig = signature(img)
            now = time.time()
            changed = prev_sig is None or diff(prev_sig, sig)[0] > 0.002
            if changed or now - last_store > 2.0:
                thumb = img.copy()
                thumb.thumbnail((400, 400))
                with _ring_lock:
                    RING.append((now, thumb))
                last_store = now
            prev_sig = sig
            time.sleep(0.3 if changed else 0.8)
        except Exception:
            time.sleep(2.0)


def start():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="vision-ring").start()


def contact_sheet(seconds=10, n=6):
    """Filmstrip of up to n recent frames from the last `seconds`, oldest first, labelled."""
    now = time.time()
    with _ring_lock:
        frames = [(t, im) for t, im in RING if now - t <= seconds]
    if not frames:
        return None
    n = max(1, min(int(n), 12))
    if len(frames) > n:
        step = (len(frames) - 1) / (n - 1) if n > 1 else 0
        frames = [frames[round(i * step)] for i in range(n)]
    cols = 3 if len(frames) > 2 else len(frames)
    rows = (len(frames) + cols - 1) // cols
    tw, th = frames[0][1].size
    sheet = Image.new("RGB", (cols * tw, rows * th), (20, 20, 20))
    for i, (t, im) in enumerate(frames):
        im = im.copy()
        ImageDraw.Draw(im).text((6, 4), f"-{now - t:.1f}s", fill=(255, 255, 0))
        sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    return encode(sheet, 1568, 70)[0]
