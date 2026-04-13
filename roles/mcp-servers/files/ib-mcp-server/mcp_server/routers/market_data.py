# market_data.py
from fastapi import APIRouter, Query, Body, Path
from typing import List, Dict, Any, Union, Optional
import httpx
from pydantic import BaseModel, Field
from mcp_server.config import BASE_URL

router = APIRouter()

# --- Pydantic Models ---

class UnsubscribeRequest(BaseModel):
    """Request model for unsubscribing from a market data conid."""
    conid: str = Field(..., description="The contract ID to unsubscribe from.")


# --- Market Data Field and Availability Information ---

MARKET_DATA_FIELDS = [
    {"field_code": "31", "type": "String", "name": "Last Price"},
    # ... (omitted for brevity, same as before)
    {"field_code": "7633", "type": "String", "name": "VWAP"},
]

MARKET_DATA_AVAILABILITY = {
    "L": {"name": "Live", "description": "Real-time streaming data. Requires Market Data subscription."},
    # ... (omitted for brevity, same as before)
    "d": {"name": "Delayed Snapshot", "description": "A static snapshot of delayed market data."}
}

# --- Specific Rules for History Endpoints ---

HMDS_HISTORY_RULES = {
    "period_units": {
        "S": "Seconds",
        "d": "Day",
        "w": "Week",
        "m": "Month",
        "y": "Year"
    },
    "bar_units_by_period": {
        "60S": "secs, mins (1 secs -> 1 mins)",
        "3600S": "secs, mins, hrs (5 secs -> 1 hour)",
        "14400S": "secs, mins, hrs (10 secs -> 4 hrs)",
        "28800S": "secs, mins, hrs (30 secs -> 8 hrs)",
        "1d": "mins, hrs, d (1 min -> 1 day)",
        "1w": "mins, hrs, d, w (3 mins -> 1 week)",
        "1m": "mins, d, w (30 mins -> 1 month)",
        "1y": "d, w, m (1 day -> 1 month)"
    }
}

ISERVER_HISTORY_RULES = {
    "period_format": "{1-30}min, {1-8}h, {1-1000}d, {1-792}w, {1-182}m, {1-15}y",
    "bar_values": "1min, 2min, 3min, 5min, 10min, 15min, 30min, 1h, 2h, 3h, 4h, 8h, 1d, 1w, 1m",
    "step_size": {
        "period": ["1min", "1h", "1d", "1w", "1m", "3m", "6m", "1y", "2y", "3y", "15y"],
        "bar_range": ["1min", "1min – 8h", "1min – 8h", "10min – 1w", "1h – 1m", "2h – 1m", "4h – 1m", "8h – 1m", "1d – 1m", "1d – 1m", "1w – 1m"],
        "default_bar": ["1min", "1min", "1min", "15min", "30min", "1d", "1d", "1d", "1d", "1w", "1w"]
    }
}


# --- Market Data Router Endpoints ---

@router.get(
    "/iserver/marketdata/fields",
    tags=["Market Data"],
    summary="Available Market Data Fields",
    description="Returns a list of all available fields for the Market Data Snapshot endpoint."
)
async def get_available_fields() -> List[Dict[str, str]]:
    return MARKET_DATA_FIELDS

@router.get(
    "/iserver/marketdata/availability",
    tags=["Market Data"],
    summary="Market Data Availability Codes",
    description="Returns a dictionary explaining the codes used in the 'Market Data Availability' field (6509)."
)
async def get_availability_codes() -> Dict[str, Dict[str, str]]:
    return MARKET_DATA_AVAILABILITY

@router.get(
    "/hmds/history/rules",
    tags=["Market Data"],
    summary="Get HMDS History Rules",
    description="Returns the valid period and bar size units for the /hmds/history endpoint."
)
async def get_hmds_history_rules() -> Dict[str, Any]:
    return HMDS_HISTORY_RULES

@router.get(
    "/iserver/marketdata/history/rules",
    tags=["Market Data"],
    summary="Get iServer History Rules",
    description="Returns the valid period, bar, and step-size rules for the /iserver/marketdata/history endpoint."
)
async def get_iserver_history_rules() -> Dict[str, Any]:
    return ISERVER_HISTORY_RULES


@router.get(
    "/iserver/marketdata/snapshot",
    tags=["Market Data"],
    summary="Live Market Data Snapshot",
    description="Get a snapshot of market data for one or more contracts."
)
async def get_marketdata_snapshot(
    conids: str = Query(..., description="A comma-separated list of contract IDs."),
    fields: str = Query(..., description="A comma-separated list of field codes.")
) -> List[Dict[str, Any]]:
    """
    ### Get Market Data Snapshot
    Fetches a snapshot of market data. This endpoint is called twice internally to ensure data retrieval.
    """
    params = {"conids": conids, "fields": fields}
    async with httpx.AsyncClient(verify=False) as client:
        try:
            await client.get(f"{BASE_URL}/iserver/marketdata/snapshot", params=params, timeout=10)
            response = await client.get(f"{BASE_URL}/iserver/marketdata/snapshot", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/md/snapshot",
    tags=["Market Data"],
    summary="Market Data Snapshot (Streaming Alternative)",
    description="Get a snapshot of market data for a list of conids."
)
async def get_md_snapshot(
    conids: str = Query(..., description="A comma-separated list of contract IDs."),
    fields: Optional[str] = Query(None, description="A comma-separated list of field codes.")
):
    params = {"conids": conids}
    if fields:
        params["fields"] = fields
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/md/snapshot", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/iserver/marketdata/history",
    tags=["Market Data"],
    summary="Market Data History (iServer)",
    description="Get historical market data for a contract. Use `/iserver/marketdata/history/rules` for valid parameters."
)
async def get_marketdata_history(
    conid: str = Query(..., description="The contract ID."),
    period: str = Query(..., description="The time period for the request, e.g., '1d', '2w'."),
    bar: Optional[str] = Query(None, description="The bar size, e.g., '1min', '1h'."),
    exchange: Optional[str] = Query(None, description="The exchange to query."),
    outsideRth: Optional[bool] = Query(False, description="Set to true to include data outside regular trading hours."),
    barType: Optional[str] = Query("trades", description="The type of data to return, e.g., 'trades', 'midpoint'.")
):
    params = {
        "conid": conid,
        "period": period,
        "outsideRth": str(outsideRth).lower()
    }
    if bar:
        params["bar"] = bar
    if exchange:
        params["exchange"] = exchange
    if barType:
        params["barType"] = barType
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/marketdata/history", params=params, timeout=20)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/hmds/history",
    tags=["Market Data"],
    summary="Deeper Market Data History (HMDS)",
    description="Get historical market data from the HMDS. Use `/hmds/history/rules` for valid parameters."
)
async def get_hmds_history(
    conid: str = Query(..., description="The contract ID."),
    period: str = Query(..., description="The time period. Note: units are case-sensitive."),
    bar: Optional[str] = Query(None, description="The bar size. Note: allowed units depend on the period."),
    outsideRth: Optional[bool] = Query(False, description="Set to true to include data outside regular trading hours."),
    barType: Optional[str] = Query("trades", description="The type of data to return."),
    startTime: Optional[str] = Query(None, description="Specify the start time of the query in 'YYYYMMDD-hh:mm:ss' format.")
):
    """
    Fetches deeper historical market data using the HMDS. It first calls /hmds/auth/init to authenticate the session.
    """
    params = {
        "conid": conid,
        "period": period,
        "outsideRth": str(outsideRth).lower()
    }
    if bar:
        params["bar"] = bar
    if barType:
        params["barType"] = barType
    if startTime:
        params["startTime"] = startTime
    async with httpx.AsyncClient(verify=False) as client:
        try:
            await client.get(f"{BASE_URL}/hmds/auth/init", timeout=10)
            response = await client.get(f"{BASE_URL}/hmds/history", params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.post(
    "/iserver/marketdata/unsubscribe",
    tags=["Market Data"],
    summary="Unsubscribe from Market Data",
    description="Unsubscribes from a specific market data feed."
)
async def unsubscribe_market_data(body: UnsubscribeRequest = Body(...)):
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(f"{BASE_URL}/iserver/marketdata/unsubscribe", json=body.dict(), timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.post(
    "/iserver/marketdata/unsubscribeall",
    tags=["Market Data"],
    summary="Unsubscribe from All Market Data",
    description="Unsubscribes from all current market data subscriptions."
)
async def unsubscribe_all_market_data():
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(f"{BASE_URL}/iserver/marketdata/unsubscribeall", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}
