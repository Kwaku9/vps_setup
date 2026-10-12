import hmac
import os
from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from fastmcp import FastMCP
from fastmcp.server.openapi import RouteMap, MCPType
from mcp_server.config import MCP_SERVER_HOST, MCP_SERVER_PORT, MCP_TRANSPORT_PROTOCOL, FINAL_DESCRIPTION, EXCLUDED_TAGS_SET

# Import Router Files
import alerts
import contract
import events_contracts
import fa_allocation_management
import fyis_and_notifications
import market_data
import options_chains
import order_monitoring
import orders
import portfolio
import scanner
import session
import watchlists


app = FastAPI(
    title="IBKR API",
    description=FINAL_DESCRIPTION,
    version="1.0.0"
)

app.include_router(alerts.router)
app.include_router(contract.router)
app.include_router(events_contracts.router)
app.include_router(fa_allocation_management.router)
app.include_router(fyis_and_notifications.router)
app.include_router(market_data.router)
app.include_router(options_chains.router)
app.include_router(order_monitoring.router)
app.include_router(orders.router)
app.include_router(portfolio.router)
app.include_router(scanner.router)
app.include_router(session.router)
app.include_router(watchlists.router)


route_maps_list = []

if EXCLUDED_TAGS_SET:    
    for tag_ in EXCLUDED_TAGS_SET:
        route_maps_list.append(RouteMap(tags={tag_}, mcp_type=MCPType.EXCLUDE))


mcp = FastMCP.from_fastapi(
    app=app,
    route_maps = route_maps_list,
    )

class BearerAuth:
    """Require `Authorization: Bearer <AUTH_TOKEN>` on every HTTP request.

    Added 2026-10-02. Until then nothing read AUTH_TOKEN, so anything that
    could reach :5002 could list and call every tool on a live brokerage
    account. Pure ASGI so it wraps the whole FastMCP app, streams included.
    """

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            header = dict(scope.get("headers") or []).get(b"authorization", b"").decode("latin-1")
            if not (header.startswith("Bearer ") and hmac.compare_digest(header[7:], self.token)):
                resp = PlainTextResponse("Unauthorized", status_code=401, headers={"WWW-Authenticate": "Bearer"})
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


if __name__ == "__main__":
    # FastMCP 2.13 accepts ONLY {"stdio", "http", "sse", "streamable-http"} as a
    # transport name. Statelessness is a separate boolean parameter, NOT a transport.
    #
    # This bit the project twice. MCP_TRANSPORT_PROTOCOL=stateless-http was set to
    # fix persistent HTTP sessions expiring mid-conversation and silently dropping
    # the MCP client — but it crash-loops the server with
    #   ValueError: Unknown transport: stateless-http
    # so it was reverted to plain streamable-http (63159d2), which boots but brings
    # the session-drop bug straight back. Both values are wrong on their own.
    #
    # Translate the setting into what FastMCP actually wants: streamable-http
    # transport PLUS stateless_http=True.
    transport = MCP_TRANSPORT_PROTOCOL
    run_kwargs = {}
    # Fail closed: an HTTP transport without a token would be an open door to a
    # brokerage account. stdio is host-local (podman exec) and needs none.
    token = os.environ.get("AUTH_TOKEN", "")
    if transport != "stdio":
        if not token:
            raise SystemExit("ib-mcp-server: AUTH_TOKEN is required for HTTP transports")
        run_kwargs["middleware"] = [Middleware(BearerAuth, token=token)]
    if transport == "stateless-http":
        transport = "streamable-http"
        run_kwargs["stateless_http"] = True

    mcp.run(
        transport=transport,
        host=MCP_SERVER_HOST,
        port=MCP_SERVER_PORT,
        log_level="DEBUG",
        **run_kwargs,
    )
