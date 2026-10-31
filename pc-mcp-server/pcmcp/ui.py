"""Tk control window: connector URL, tunnel, mode, options, activity log, panic button."""
import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import security as sec
from .config import CFG, new_token, save


def hide_from_capture(win):
    """Exclude a window from screen capture so the AI cannot read tokens or see approval buttons."""
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)  # WDA_EXCLUDEFROMCAPTURE
    except Exception:
        pass


class UI:
    def __init__(self, port, tunnel, is_admin, on_quit):
        self.port, self.tunnel, self.on_quit = port, tunnel, on_quit
        self.logq, self.askq = queue.Queue(), queue.Queue()
        self.dialog_open = False
        self.show_secret = False
        r = self.root = tk.Tk()
        r.title("PC MCP Server" + ("  [ADMINISTRATOR]" if is_admin else ""))
        r.geometry("720x640")
        r.protocol("WM_DELETE_WINDOW", self.quit)
        pad = {"padx": 8, "pady": 3}
        if is_admin:
            tk.Label(r, text="RUNNING AS ADMINISTRATOR - the AI can change system settings",
                     bg="#b00020", fg="white", font=("Segoe UI", 10, "bold")).pack(fill="x")

        f = ttk.LabelFrame(r, text="Connector URL (paste into Claude > Settings > Connectors)")
        f.pack(fill="x", **pad)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(f, textvariable=self.url_var, state="readonly", show="\u2022")
        self.url_entry.pack(side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(f, text="Show", command=self.toggle_show).pack(side="left")
        ttk.Button(f, text="Copy", command=self.copy_url).pack(side="left", padx=4)
        self.tunnel_lbl = ttk.Label(r, text="")
        self.tunnel_lbl.pack(anchor="w", **pad)
        b = ttk.Frame(r)
        b.pack(fill="x", **pad)
        ttk.Button(b, text="Start tunnel", command=self.tunnel.start).pack(side="left")
        ttk.Button(b, text="Stop tunnel", command=self.tunnel.stop).pack(side="left", padx=6)
        ttk.Button(b, text="New token", command=self.regen).pack(side="left")
        if not is_admin:
            ttk.Button(b, text="Relaunch as administrator", command=self.relaunch_admin).pack(side="left", padx=6)

        m = ttk.LabelFrame(r, text="Permission mode")
        m.pack(fill="x", **pad)
        self.mode_var = tk.StringVar(value=sec.current_mode())
        for mode, txt in (("SAFE", "SAFE - view only"), ("ASK", "ASK - you approve every action"),
                          ("FULL", "FULL - AI acts freely")):
            ttk.Radiobutton(m, text=txt, value=mode, variable=self.mode_var, command=self.mode_changed).pack(anchor="w", padx=8)
        self.timer_lbl = ttk.Label(m, text="")
        self.timer_lbl.pack(anchor="w", padx=8, pady=2)

        o = ttk.LabelFrame(r, text="Owner options (opt-in)")
        o.pack(fill="x", **pad)
        self.opts = {}
        for key, txt in (("start_full", "Start in FULL mode"), ("never_expire", "FULL mode never expires (default 30 min)"),
                         ("unrestricted", "Unrestricted: all drives, command blocklist OFF")):
            v = tk.BooleanVar(value=bool(CFG[key]))
            self.opts[key] = v
            ttk.Checkbutton(o, text=txt, variable=v, command=lambda k=key: self.opt_changed(k)).pack(anchor="w", padx=8)

        p = ttk.LabelFrame(r, text="Permanent address (optional): Cloudflare named tunnel")
        p.pack(fill="x", **pad)
        self.tt_var, self.pu_var = tk.StringVar(value=CFG["tunnel_token"]), tk.StringVar(value=CFG["public_url"])
        ttk.Label(p, text="Tunnel token").grid(row=0, column=0, sticky="w", padx=6)
        ttk.Entry(p, textvariable=self.tt_var, show="\u2022").grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Label(p, text="Public URL").grid(row=1, column=0, sticky="w", padx=6)
        ttk.Entry(p, textvariable=self.pu_var).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(p, text="Save", command=self.save_perm).grid(row=0, column=2, rowspan=2, padx=6)
        p.columnconfigure(1, weight=1)

        self.log = tk.Text(r, height=10, state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, **pad)
        tk.Button(r, text="STOP && QUIT   (hotkey: Ctrl+Alt+Shift+K = panic -> SAFE)", bg="#b00020", fg="white",
                  command=self.quit).pack(fill="x", padx=8, pady=6)

        sec.STATE.log_fn = self.logq.put
        sec.STATE.ask_fn = self.ask
        hide_from_capture(r)
        self.root.after(200, self.poll)

    # --- actions
    def run(self):
        self.root.mainloop()

    def quit(self):
        self.on_quit()

    def full_url(self):
        base = self.tunnel.base_url() or f"http://127.0.0.1:{self.port}"
        return f"{base}/s/{CFG['token']}/mcp"

    def toggle_show(self):
        self.show_secret = not self.show_secret
        self.url_entry.config(show="" if self.show_secret else "\u2022")

    def copy_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.full_url())

    def regen(self):
        if messagebox.askyesno("New token", "Create a new token? The old connector URL stops working."):
            new_token()

    def mode_changed(self):
        mode = self.mode_var.get()
        if mode == "FULL" and not messagebox.askyesno("FULL mode", "Let the AI act on this PC without asking?"):
            self.mode_var.set(sec.current_mode())
            return
        sec.set_mode(mode)

    def opt_changed(self, key):
        val = self.opts[key].get()
        if key == "unrestricted" and val and not messagebox.askyesno(
                "Unrestricted", "Allow ALL drives and turn the command blocklist OFF?"):
            self.opts[key].set(False)
            return
        CFG[key] = val
        save()

    def save_perm(self):
        CFG["tunnel_token"], CFG["public_url"] = self.tt_var.get().strip(), self.pu_var.get().strip()
        save()
        messagebox.showinfo("Saved", "Restart the tunnel to apply.")

    def relaunch_admin(self):
        if not messagebox.askyesno("Administrator", "Relaunch with administrator rights?"):
            return
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, ""
        else:
            exe, params = sys.executable, f'"{os.path.abspath(sys.argv[0])}"'
        if ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1) > 32:
            self.quit()

    # --- thread-safe bridges
    def ask(self, tool, detail):
        ev, box = threading.Event(), {"ok": False}
        self.askq.put((tool, detail, ev, box))
        ev.wait(60)
        return box["ok"]

    def poll(self):
        try:
            while True:
                line = self.logq.get_nowait()
                self.log.config(state="normal")
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.config(state="disabled")
        except queue.Empty:
            pass
        if not self.dialog_open and not self.askq.empty():
            self.show_dialog(*self.askq.get())
        self.url_var.set(self.full_url())
        self.tunnel_lbl.config(text=f"Tunnel: {self.tunnel.status}   |   local port {self.port}")
        cur = sec.current_mode()
        if self.mode_var.get() != cur:
            self.mode_var.set(cur)
        if cur == "FULL" and not CFG["never_expire"]:
            self.timer_lbl.config(text=f"FULL expires in {max(0, int(sec.STATE.full_until - time.time())) // 60 + 1} min")
        else:
            self.timer_lbl.config(text="")
        self.root.after(200, self.poll)

    def show_dialog(self, tool, detail, ev, box):
        self.dialog_open = True
        d = tk.Toplevel(self.root)
        d.title("Approve action?")
        d.attributes("-topmost", True)
        d.geometry("460x190")
        tk.Label(d, text=f"The AI wants to run:\n{tool}", font=("Segoe UI", 11, "bold")).pack(pady=8)
        tk.Label(d, text=detail[:300], wraplength=430, justify="left").pack(padx=10)

        def done(ok):
            box["ok"] = ok
            ev.set()
            self.dialog_open = False
            d.destroy()

        bf = tk.Frame(d)
        bf.pack(side="bottom", pady=10)
        tk.Button(bf, text="Allow", width=12, command=lambda: done(True)).pack(side="left", padx=10)
        tk.Button(bf, text="Deny", width=12, command=lambda: done(False)).pack(side="left", padx=10)
        d.protocol("WM_DELETE_WINDOW", lambda: done(False))
        d.after(60000, lambda: done(False) if self.dialog_open else None)
        hide_from_capture(d)
