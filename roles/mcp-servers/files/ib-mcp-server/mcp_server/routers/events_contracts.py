# events_contracts.py
from fastapi import APIRouter, Query
import httpx
from mcp_server.config import BASE_URL

router = APIRouter()

# --- Events Contracts Router Endpoints ---

@router.get(
    "/events/contracts",
    tags=["Events Contracts"],
    summary="Get Events Contracts",
    description="Returns a list of event contracts for the given conids."
)
async def get_events_contracts(
    conids: str = Query(..., description="A comma-separated list of contract IDs.")
):
    """
    Fetches event contracts for the specified conids. Event contracts are contracts that settle based on the outcome of a future event.
    """
    params = {"conids": conids}
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/events/contracts", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/events/show",
    tags=["Events Contracts"],
    summary="Show Event Contract",
    description="Returns the event contract for the given conid."
)
async def show_event_contract(
    conid: str = Query(..., description="A single contract ID.")
):
    """
    Retrieves the details for a specific event contract.
    """
    params = {"conid": conid}
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/events/show", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}
