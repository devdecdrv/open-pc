import asyncio

import pytest

from pcmcp import security as sec
from pcmcp.config import CFG
from pcmcp.gate import Gate


def test_blocklist():
    CFG["unrestricted"] = False
    for bad in ["format c:", "diskpart", "vssadmin delete shadows /all", "shutdown /s", "type x > ~/.pc_mcp_server/config.json"]:
        with pytest.raises(PermissionError):
            sec.check_command(bad)
    sec.check_command("Get-Process")


def test_unrestricted_still_protects_config_dir():
    CFG["unrestricted"] = True
    try:
        sec.check_command("format c:")  # allowed when unrestricted
        with pytest.raises(PermissionError):
            sec.check_command("cat $HOME\\.pc_mcp_server\\config.json")
    finally:
        CFG["unrestricted"] = False


def test_paths(tmp_path):
    CFG["unrestricted"] = False
    with pytest.raises(PermissionError):
        sec.resolve_path("C:/Windows/System32" if __import__("os").name == "nt" else "/etc/passwd")
    from pcmcp.config import APP_DIR
    with pytest.raises(PermissionError):
        sec.resolve_path(str(APP_DIR / "config.json"))


def test_permission_modes():
    sec.STATE.ask_fn = None
    sec.set_mode("SAFE")
    sec.authorize("screenshot", sec.VIEW)
    with pytest.raises(PermissionError):
        sec.authorize("read_file", sec.READ)
    sec.set_mode("ASK")
    sec.authorize("read_file", sec.READ)
    with pytest.raises(PermissionError):
        sec.authorize("click", sec.ACT)
    sec.STATE.ask_fn = lambda t, d: True
    sec.authorize("click", sec.ACT)
    sec.set_mode("FULL")
    sec.STATE.ask_fn = None
    sec.authorize("click", sec.ACT)
    sec.set_mode("SAFE")


def _call(path, headers=()):
    seen, out = {}, []

    async def app(scope, receive, send):
        seen["path"] = scope["path"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(m):
        out.append(m)

    async def run():
        await Gate(app, lambda: "TOK")({"type": "http", "path": path, "headers": list(headers)}, None, send)

    asyncio.run(run())
    return out[0]["status"], seen.get("path")


def test_gate():
    assert _call("/health")[0] == 200
    assert _call("/.well-known/oauth-authorization-server")[0] == 404
    assert _call("/s/TOK/mcp") == (200, "/mcp")
    assert _call("/s/WRONG/mcp")[0] == 403
    assert _call("/mcp")[0] == 403
    assert _call("/mcp", [(b"authorization", b"Bearer TOK")]) == (200, "/mcp")
    assert _call("/mcp", [(b"x-api-key", b"TOK")]) == (200, "/mcp")
    assert _call("/mcp", [(b"authorization", b"Bearer nope")])[0] == 403
