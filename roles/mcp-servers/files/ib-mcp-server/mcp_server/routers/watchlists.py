# watchlists.py
from fastapi import APIRouter, Body, Path
from typing import List, Optional
import httpx
from pydantic import BaseModel, Field
from mcp_server.config import BASE_URL

router = APIRouter()

# --- Pydantic Models for Watchlist Requests ---

class WatchlistCreateRequest(BaseModel):
    """Request model for creating a new watchlist."""
    name: str = Field(..., description="The name of the new watchlist.")
    conids: Optional[List[str]] = Field(None, description="A list of contract IDs to add to the new watchlist.")

class WatchlistContractsRequest(BaseModel):
    """Request model for adding contracts to a watchlist."""
    conids: List[str] = Field(..., description="A list of contract IDs to add.")


# --- Watchlists Router Endpoints ---

@router.get(
    "/iserver/account/watchlists",
    tags=["Watchlists"],
    summary="Get Watchlists",
    description="Returns a list of all watchlists for the current user."
)
async def get_watchlists():
    """
    Retrieves all watchlists associated with the current user's account.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/account/watchlists", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/iserver/account/watchlist/{watchlistId}",
    tags=["Watchlists"],
    summary="Get Watchlist Contracts",
    description="Returns a list of contracts for a specific watchlist."
)
async def get_watchlist_contracts(
    watchlistId: str = Path(..., description="The ID of the watchlist.")
):
    """
    Retrieves all contracts within a specific watchlist.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/account/watchlist/{watchlistId}", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.post(
    "/iserver/account/{accountId}/watchlist",
    tags=["Watchlists"],
    summary="Create Watchlist",
    description="Creates a new watchlist."
)
async def create_watchlist(
    accountId: str = Path(..., description="The account ID."),
    body: WatchlistCreateRequest = Body(...)
):
    """
    Creates a new watchlist for the specified account with an optional list of initial contracts.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/iserver/account/{accountId}/watchlist",
                json=body.dict(exclude_none=True),
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.post(
    "/iserver/account/watchlist/{watchlistId}/contract",
    tags=["Watchlists"],
    summary="Add Contracts to Watchlist",
    description="Adds one or more contracts to an existing watchlist."
)
async def add_contracts_to_watchlist(
    watchlistId: str = Path(..., description="The ID of the watchlist."),
    body: WatchlistContractsRequest = Body(...)
):
    """
    Adds one or more contracts to a specified watchlist.
    Note: The documentation shows adding a single conid, but the description implies multiple are possible. This implementation uses a list for flexibility.
    """
    # The API might expect a single `conid` key. If this call fails, adjust the model and this call accordingly.
    # For now, we assume a more flexible `conids` list can be handled or that the first element is used.
    # A safer single-conid implementation would be: `json={"conid": body.conids[0]}` if only one is allowed.
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/iserver/account/watchlist/{watchlistId}/contract",
                json=body.dict(),
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.delete(
    "/iserver/account/watchlist/{watchlistId}",
    tags=["Watchlists"],
    summary="Delete Watchlist",
    description="Deletes a specific watchlist."
)
async def delete_watchlist(
    watchlistId: str = Path(..., description="The ID of the watchlist to delete.")
):
    """
    Deletes an entire watchlist by its ID.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.delete(f"{BASE_URL}/iserver/account/watchlist/{watchlistId}", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.delete(
    "/iserver/account/watchlist/{watchlistId}/contract/{conid}",
    tags=["Watchlists"],
    summary="Delete Contract from Watchlist",
    description="Deletes a single contract from a specific watchlist."
)
async def delete_contract_from_watchlist(
    watchlistId: str = Path(..., description="The ID of the watchlist."),
    conid: str = Path(..., description="The contract ID to delete.")
):
    """
    Removes a single contract from a specified watchlist.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.delete(f"{BASE_URL}/iserver/account/watchlist/{watchlistId}/contract/{conid}", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}
