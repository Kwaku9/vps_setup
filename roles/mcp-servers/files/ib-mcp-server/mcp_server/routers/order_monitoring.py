# order_monitoring.py
from fastapi import APIRouter, Query, Path
from typing import Optional
import httpx
from mcp_server.config import BASE_URL

router = APIRouter()

# --- Order Monitoring Router Endpoints ---

@router.get(
    "/iserver/account/orders",
    tags=["Order Monitoring"],
    summary="Live Orders",
    description="Retrieves a list of live orders, including filled, cancelled, and submitted orders for the current brokerage session."
)
async def get_live_orders(
    filters: Optional[str] = Query(
        default=None,
        description="Filter results by a comma-separated list of order statuses. Valid values: Inactive, PendingSubmit, PreSubmitted, Submitted, Filled, PendingCancel, Cancelled, WarnState, SortByTime.",
    ),
    force: Optional[bool] = Query(
        default=False,
        description="Set to true to clear the cache of orders and fetch an updated list."
    )
):
    """
    Fetches all live orders from the IBKR API. This endpoint provides a comprehensive view of order activity.
    """
    params = {}
    if filters:
        params["filters"] = filters
    if force:
        params["force"] = str(force).lower()

    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/account/orders", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/iserver/account/order/status/{orderId}",
    tags=["Order Monitoring"],
    summary="Order Status",
    description="Retrieves the status of a single order by its order ID."
)
async def get_order_status(
    orderId: str = Path(..., description="The order ID of the order to check.")
):
    """
    Fetches the latest status for a specific order. This is useful for tracking the lifecycle of an individual order.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/account/order/status/{orderId}", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/iserver/account/trades",
    tags=["Order Monitoring"],
    summary="List of Trades",
    description="Returns a list of trades for the currently selected account for the current and previous six days."
)
async def get_trades(
    days: Optional[str] = Query(None, description="Number of days to retrieve trades for, up to a maximum of 7.")
):
    """
    Retrieves a list of recent trades, providing a history of executed orders.
    """
    params = {}
    if days:
        params["days"] = days
        
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/account/trades", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}
