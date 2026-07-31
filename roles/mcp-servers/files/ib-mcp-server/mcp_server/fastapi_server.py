import os
from fastapi import FastAPI
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
