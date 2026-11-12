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

# The Vercel Redis integration names its variables <PREFIX>_REDIS_URL /
# <PREFIX>_KV_URL. Map them to the name ads_mcp reads, unless it is already set.
if not os.environ.get("GOOGLE_ADS_MCP_STORAGE_REDIS_URL"):
    for _name in (
        "GOOGLE_ADS_MCP_STORAGE_REDIS_REDIS_URL",
        "GOOGLE_ADS_MCP_STORAGE_REDIS_KV_URL",
        "REDIS_URL",
        "KV_URL",
    ):
        if os.environ.get(_name):
            os.environ["GOOGLE_ADS_MCP_STORAGE_REDIS_URL"] = os.environ[_name]
            break

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
    def flag(*names: str) -> bytes:
        return b"true" if all(os.environ.get(n) for n in names) else b"false"

    body = b'{"status":"ok","oauth":%s,"redis":%s,"developer_token":%s}' % (
        flag("GOOGLE_ADS_MCP_OAUTH_CLIENT_ID", "GOOGLE_ADS_MCP_OAUTH_CLIENT_SECRET"),
        flag("GOOGLE_ADS_MCP_STORAGE_REDIS_URL"),
        flag("GOOGLE_ADS_DEVELOPER_TOKEN"),
    )
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


_PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:680px;margin:48px auto;padding:0 20px;line-height:1.6;color:#222}}</style>
</head><body>{body}</body></html>"""

_HOME = _PAGE.format(
    title="Google Ads MCP",
    body="""<h1>Google Ads MCP</h1>
<p>Servidor MCP privado que permite a assistentes de IA autorizados consultar dados
de contas do Google Ads por meio da Google Ads API, em nome do usuário que fez login.</p>
<p>Endpoint MCP: <code>/mcp</code> &middot; <a href="/privacy">Política de privacidade</a></p>""",
)

_PRIVACY = _PAGE.format(
    title="Política de privacidade · Google Ads MCP",
    body="""<h1>Política de privacidade</h1>
<p>Este serviço é de uso privado e conecta um assistente de IA à Google Ads API.</p>
<h2>Dados acessados</h2>
<p>Com a autorização do usuário via login do Google, o serviço acessa o e-mail e o perfil
básico da conta e os dados das contas do Google Ads às quais o usuário tem acesso
(escopo <code>https://www.googleapis.com/auth/adwords</code>).</p>
<h2>Uso</h2>
<p>Os dados são usados somente para responder às consultas feitas pelo próprio usuário
no assistente de IA conectado. Não são vendidos, compartilhados com terceiros para
publicidade nem usados para outra finalidade.</p>
<h2>Armazenamento</h2>
<p>O serviço guarda apenas os tokens de autenticação, criptografados, pelo tempo
necessário para manter a sessão. Os dados do Google Ads não são armazenados.</p>
<h2>Revogação</h2>
<p>O acesso pode ser revogado a qualquer momento em
<a href="https://myaccount.google.com/permissions">myaccount.google.com/permissions</a>.</p>
<p>O uso de informações recebidas das APIs do Google segue a
<a href="https://developers.google.com/terms/api-services-user-data-policy">Política de dados
do usuário dos serviços de API do Google</a>, incluindo os requisitos de uso limitado.</p>""",
)


async def _html(send, html: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/html; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": html.encode()})


async def _json(send, status: int, data: dict) -> None:
    import json

    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json; charset=utf-8")],
        }
    )
    await send(
        {"type": "http.response.body", "body": json.dumps(data, ensure_ascii=False, indent=2).encode()}
    )


async def _diagnose(send) -> None:
    """Checks Redis storage and a client registration, returning any error text."""
    import time
    import traceback

    result: dict = {"redis_url_set": bool(os.environ.get("GOOGLE_ADS_MCP_STORAGE_REDIS_URL"))}

    # 1. Raw Redis round trip through the same storage ads_mcp uses.
    try:
        from ads_mcp.auth_storage import create_client_storage

        store = create_client_storage()
        result["storage_class"] = type(store).__name__ if store is not None else None
        if store is not None:
            t = time.monotonic()
            await store.put(key="diag", value={"ok": True}, collection="diagnose", ttl=60)
            got = await store.get(key="diag", collection="diagnose")
            result["redis_roundtrip"] = "ok" if got else f"unexpected: {got!r}"
            result["redis_ms"] = round((time.monotonic() - t) * 1000)
    except Exception as e:  # noqa: BLE001
        result["redis_error"] = f"{type(e).__name__}: {e}"
        result["redis_traceback"] = traceback.format_exc()[-2000:]

    # 2. A client registration exactly like Claude's, through the real app.
    try:
        import json
        from urllib.parse import urlparse

        await _ensure_started()
        body = json.dumps(
            {
                "client_name": "diagnose",
                "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            }
        ).encode()
        host = urlparse(os.environ.get("GOOGLE_ADS_MCP_BASE_URL", "http://localhost")).netloc
        req_scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/register",
            "raw_path": b"/register",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", host.encode()),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
            "client": ("127.0.0.1", 0),
            "server": (host, 443),
        }
        sent = False
        out: dict = {"status": None, "body": b""}

        async def _receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def _send(message):
            if message["type"] == "http.response.start":
                out["status"] = message["status"]
            elif message["type"] == "http.response.body":
                out["body"] += message.get("body", b"")

        await _mcp_app(req_scope, _receive, _send)
        result["register_status"] = out["status"]
        result["register_body"] = out["body"].decode(errors="replace")[:1500]
    except Exception as e:  # noqa: BLE001
        result["register_error"] = f"{type(e).__name__}: {e}"
        result["register_traceback"] = traceback.format_exc()[-2000:]

    await _json(send, 200, result)


async def app(scope, receive, send):
    global _platform_runs_lifespan
    if scope["type"] == "lifespan":
        _platform_runs_lifespan = True
        return await _mcp_app(scope, receive, send)
    if scope["type"] == "http" and scope.get("path") == "/health":
        return await _health(send)
    if scope["type"] == "http" and scope.get("path") in ("/", "/privacy"):
        return await _html(send, _HOME if scope["path"] == "/" else _PRIVACY)
    if scope["type"] == "http" and scope.get("path") == "/diagnose":
        return await _diagnose(send)
    await _ensure_started()
    try:
        return await _mcp_app(scope, receive, send)
    except Exception:
        # Make crashes visible in Vercel's runtime logs.
        import traceback

        print(f"ERROR on {scope.get('method')} {scope.get('path')}:\n{traceback.format_exc()}", flush=True)
        raise
