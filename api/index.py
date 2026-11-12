"""Vercel entry point for the Google Ads MCP server.

Exposes the FastMCP server as an ASGI app at /mcp (Streamable HTTP, stateless),
plus the OAuth routes FastMCP adds when GOOGLE_ADS_MCP_OAUTH_CLIENT_ID/SECRET
are set, and a /health route for quick checks.
"""

import asyncio
import contextlib
import os
import sys

# Make the ads_mcp package importable from the repo root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ads_mcp.coordinator import mcp  # noqa: E402

# Registers the resources on the shared `mcp` instance.
from ads_mcp.resources import (  # noqa: E402,F401
    discovery,
    metrics,
    release_notes,
    segments,
)

# Stateless mode: each request stands alone, so it doesn't matter which
# serverless instance answers it.
_mcp_app = mcp.http_app(stateless_http=True)

_lifespan_stack: contextlib.AsyncExitStack | None = None
_lifespan_lock = asyncio.Lock()
_platform_runs_lifespan = False


async def _ensure_started() -> None:
    """Starts FastMCP's session manager once, if the platform didn't."""
    global _lifespan_stack
    if _platform_runs_lifespan or _lifespan_stack is not None:
        return
    async with _lifespan_lock:
        if _lifespan_stack is None:
            stack = contextlib.AsyncExitStack()
            await stack.enter_async_context(
                _mcp_app.router.lifespan_context(_mcp_app)
            )
            _lifespan_stack = stack


async def _health(send) -> None:
    body = b'{"status":"ok","oauth":%s}' % (
        b"true"
        if os.environ.get("GOOGLE_ADS_MCP_OAUTH_CLIENT_ID")
        and os.environ.get("GOOGLE_ADS_MCP_OAUTH_CLIENT_SECRET")
        else b"false"
    )
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def app(scope, receive, send):
    global _platform_runs_lifespan
    if scope["type"] == "lifespan":
        _platform_runs_lifespan = True
        return await _mcp_app(scope, receive, send)
    if scope["type"] == "http" and scope.get("path") == "/health":
        return await _health(send)
    await _ensure_started()
    return await _mcp_app(scope, receive, send)
