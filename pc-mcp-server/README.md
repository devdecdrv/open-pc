# PC MCP Server (v3, rewritten from scratch)

Lets Claude (via a custom connector) see and control a Windows PC.
**Status: written blind, never run on a real PC. CI runs unit tests and a headless self-test; everything else is unverified.**

## Get it running (no PC tooling needed)
1. Create a private GitHub repo `pc-mcp-server`, upload everything in this zip (keep the folder structure, including `.github/workflows/build.yml`).
2. Actions tab -> wait for the `build` run to go green. **Read the log**: unit tests, self-test, cloudflared SHA256.
3. Releases -> download `PC-MCP-Server.exe` (or `PC-MCP-Server-Admin.exe`, asks for UAC at launch).
4. Run it, click **Start tunnel**, click **Show/Copy**, and paste the URL into Claude > Settings > Connectors > Add custom connector.
5. If nothing opens: look at `%USERPROFILE%\.pc_mcp_server\startup_error.txt` and `actions.log`. The launcher shows an error box for startup crashes.

## Layout
- `launcher.py`  PyInstaller entry; turns silent crashes into an error box + `startup_error.txt`
- `pcmcp/app.py`  wiring, single-instance lock, panic hotkey, `--selftest`
- `pcmcp/gate.py`  auth (URL secret or Bearer), `/health` open, `/.well-known` 404, else 403
- `pcmcp/security.py`  SAFE / ASK / FULL modes, command blocklist, path rules
- `pcmcp/tools.py`  all MCP tools
- `pcmcp/vision.py`  capture (mss), change detection, 45 s look-back buffer
- `pcmcp/uia.py`  UI Automation text view and click-by-name
- `pcmcp/tunnel.py`  cloudflared (quick or named tunnel, auto-restart)
- `pcmcp/ui.py`  Tk window

## Tools
VIEW (always): `screenshot`, `look_back`, `watch`, `screen_info`, `system_info`, `list_windows`, `read_screen`, `wait`
READ: `get_clipboard`, `list_directory`, `read_file`
ACT: `click`, `click_element`, `move_mouse`, `drag`, `scroll`, `type_text`, `press_key`, `open_app`, `focus_window`, `set_clipboard`, `run_command`, `write_file`

## Vision ("human eye") - what it really is
MCP is request/response; no Claude client takes a live video stream. This approximates it with:
`watch(until="change"|"idle")` (long-poll, returns screenshot + changed area), `look_back` (filmstrip of the last ~45 s),
and `read_screen` (text of the UI, cheaper and more reliable than pixels).

## Safety model
- SAFE (default): VIEW only. ASK: you approve every ACT. FULL: free, auto-expires after 30 min unless you tick "never expires".
- Options (opt-in): start in FULL, never expire, Unrestricted (all drives, blocklist off), Admin build.
- The app window and approval dialogs are excluded from screen capture, so the AI cannot read the token from a screenshot.
- Panic hotkey **Ctrl+Alt+Shift+K** -> SAFE + tunnel stop. The config folder `.pc_mcp_server` is always off-limits to tools.
- Honest limits: the blocklist is a speed bump, not a sandbox. In ASK mode an AI that can click blindly could in theory press "Allow";
  use FULL only when you accept that, and keep the kill switch handy. The Admin exe can change system settings - use it knowingly.

## Not built yet (next steps, in order)
1. Confirm CI is green and the exe opens on a real PC; fix what breaks.
2. Windows OCR + `watch(until="text:...")`; faster UIA via a persistent helper.
3. Browser control via Chrome DevTools Protocol.
4. Tray icon, OAuth 2.1, code signing, auto-update, installer.
5. Android app tunnel (separate repo `remote`, branch `tunnel`).
Kernel-mode ("ring 0") components are deliberately out of scope.
