# portfolio.py
from fastapi import APIRouter, Body, Path, Query
from typing import List, Optional
import httpx
from pydantic import BaseModel, Field
from mcp_server.config import BASE_URL

router = APIRouter()

# --- Pydantic Models ---

class AccountAllocationRequest(BaseModel):
    """Request model for fetching portfolio allocation across multiple accounts."""
    acctIds: List[str] = Field(..., description="List of account IDs to retrieve allocation for.")


# --- Router Endpoints ---

@router.get(
    "/portfolio/accounts",
    tags=["Portfolio"],
    summary="Portfolio Accounts",
    description="In non-tiered account structures, returns a list of accounts for which the user can view position and account information. This endpoint must be called prior to calling other /portfolio endpoints for those accounts."
)
async def get_portfolio_accounts():
    """
    Fetches the list of available portfolio accounts.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/portfolio/accounts", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/portfolio/subaccounts",
    tags=["Portfolio"],
    summary="Portfolio Subaccounts",
    description="Used in tiered account structures (such as Financial Advisor and IBroker) to return a list of up to 100 sub-accounts for which the user can view position and account-related information. This endpoint must be called prior to calling other /portfolio endpoints for those sub-accounts."
)
async def get_portfolio_subaccounts():
    """
    Retrieves a list of subaccounts for the portfolio, primarily for tiered account structures.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/portfolio/subaccounts", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/portfolio/subaccounts2",
    tags=["Portfolio"],
    summary="Portfolio Subaccounts (Large Account Structures)",
    description="Used in large tiered account structures to return a list of sub-accounts for which the user can view position and account-related information. This endpoint must be called prior to calling other /portfolio endpoints for those sub-accounts."
)
async def get_portfolio_subaccounts_large():
    """
    Retrieves a list of subaccounts for large portfolio structures.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            # Note: The documentation suggests this might be a GET, but a POST with a body might be needed in practice for large lists.
            # Assuming GET based on the doc for now.
            response = await client.get(f"{BASE_URL}/portfolio/subaccounts2", timeout=30) # Longer timeout for potentially large responses
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/portfolio/{accountId}/meta",
    tags=["Portfolio"],
    summary="Specific Account's Portfolio Information",
    description="Returns information about the account, including the account's name, currency, and other metadata."
)
async def get_account_meta(
    accountId: str = Path(..., description="The account ID.")
):
    """
    Fetches metadata for a specific portfolio account.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/portfolio/{accountId}/meta", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/portfolio/{accountId}/allocation",
    tags=["Portfolio"],
    summary="Portfolio Allocation (Single)",
    description="Returns a list of positions and their allocation by asset class, industry, and category for a single account."
)
async def get_account_allocation(
    accountId: str = Path(..., description="The account ID.")
):
    """
    Fetches portfolio allocation for a single specified account.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/portfolio/{accountId}/allocation", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/portfolio/{accountId}/combo/positions",
    tags=["Portfolio"],
    summary="Combination Positions",
    description="Returns a list of combination positions for a single account."
)
async def get_combo_positions(
    accountId: str = Path(..., description="The account ID.")
):
    """
    Retrieves combination positions (e.g., complex options strategies) for an account.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/portfolio/{accountId}/combo/positions", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.post(
    "/portfolio/allocation",
    tags=["Portfolio"],
    summary="Portfolio Allocation (All)",
    description="Returns portfolio allocation information for multiple accounts combined. The accounts are specified in the request body."
)
async def get_all_accounts_allocation(body: AccountAllocationRequest = Body(...)):
    """
    Fetches combined portfolio allocation for a list of specified accounts.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/portfolio/allocation",
                json=body.dict(),
                timeout=20
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/portfolio/{accountId}/positions/{pageId}",
    tags=["Portfolio"],
    summary="Positions",
    description="Returns a list of positions for the given account. The endpoint is paginated by page ID."
)
async def get_positions(
    accountId: str = Path(..., description="The account ID."),
    pageId: int = Path(..., description="The page ID for pagination. Starts at 0."),
    model: Optional[str] = Query(None, description="The model to query positions for."),
    sort: Optional[str] = Query(None, description="The field to sort by."),
    direction: Optional[str] = Query(None, description="The sort direction: 'a' for ascending, 'd' for descending."),
    period: Optional[str] = Query(None, description="The period for which to retrieve positions.")
):
    """
    Fetches paginated positions for a specific account.
    """
    params = {}
    if model:
        params["model"] = model
    if sort:
        params["sort"] = sort
    if direction:
        params["direction"] = direction
    if period:
        params["period"] = period
        
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/portfolio/{accountId}/positions/{pageId}", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/portfolio/{acctId}/position/{conid}",
    tags=["Portfolio"],
    summary="Positions by Conid",
    description="Returns a list of all positions matching the given contract ID (conid)."
)
async def get_position_by_conid(
    acctId: str = Path(..., description="The account ID."),
    conid: int = Path(..., description="The contract ID.")
):
    """
    Retrieves all positions for a specific contract within a given account.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/portfolio/{acctId}/position/{conid}", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.post(
    "/portfolio/{accountId}/positions/invalidate",
    tags=["Portfolio"],
    summary="Invalidate Backend Portfolio Cache",
    description="Invalidates the backend portfolio cache for the specified account, forcing a refresh of portfolio data."
)
async def invalidate_portfolio_cache(
    accountId: str = Path(..., description="The account ID.")
):
    """
    Clears the cached portfolio data on the server side for the specified account.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(f"{BASE_URL}/portfolio/{accountId}/positions/invalidate", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/portfolio/{accountId}/summary",
    tags=["Portfolio"],
    summary="Portfolio Summary",
    description="Returns a summary of account information and portfolio positions."
)
async def get_account_summary(
    accountId: str = Path(..., description="The account ID.")
):
    """
    Fetches a summary of the specified account's portfolio.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/portfolio/{accountId}/summary", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/portfolio/{accountId}/ledger",
    tags=["Portfolio"],
    summary="Portfolio Ledger",
    description="Returns the cash balance and other ledger information for the specified account."
)
async def get_account_ledger(
    accountId: str = Path(..., description="The account ID.")
):
    """
    Retrieves the ledger for a specific account, showing cash balances and other financial details.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/portfolio/{accountId}/ledger", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/portfolio/positions/{conid}",
    tags=["Portfolio"],
    summary="Position & Contract Info",
    description="Returns a list of all positions matching the conid, along with the contract information."
)
async def get_all_positions_by_conid(
    conid: int = Path(..., description="The contract ID.")
):
    """
    Fetches all positions for a given contract ID across all portfolio accounts.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/portfolio/positions/{conid}", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}