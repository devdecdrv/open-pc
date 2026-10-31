"""Pure-ASGI auth gate in front of the MCP app. No Windows imports."""
import asyncio
import hmac
import json


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8", "ignore"), b.encode("utf-8", "ignore"))


async def _reply(send, status: int, obj: dict):
    body = json.dumps(obj).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class Gate:
    """Accepts /s/<token>/mcp  or  /mcp with 'Authorization: Bearer <token>' / 'x-api-key'.
    /health is open. /.well-known/* -> 404 (so clients don't start an OAuth flow we don't have).
    Everything else -> 403 after a short delay."""

    def __init__(self, app, get_token):
        self.app = app
        self.get_token = get_token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":          # lifespan etc.
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if path == "/health":
            return await _reply(send, 200, {"ok": True})
        if path.startswith("/.well-known/"):
            return await _reply(send, 404, {"error": "not found"})

        token = self.get_token()
        new_path = None
        if path.startswith("/s/"):
            parts = path.split("/", 3)       # ['', 's', token, 'mcp...']
            if len(parts) == 4 and _eq(parts[2], token):
                new_path = "/" + parts[3]
        else:
            h = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            bearer = h.get("authorization", "")
            if bearer.lower().startswith("bearer ") and _eq(bearer[7:].strip(), token):
                new_path = path
            elif "x-api-key" in h and _eq(h["x-api-key"], token):
                new_path = path

        if new_path is None:
            await asyncio.sleep(0.5)
            return await _reply(send, 403, {"error": "forbidden"})
        scope = dict(scope)
        scope["path"] = new_path
        scope["raw_path"] = new_path.encode()
        return await self.app(scope, receive, send)
