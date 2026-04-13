# fa_allocation_management.py
from fastapi import APIRouter, Body
from typing import List
import httpx
from pydantic import BaseModel, Field, ConfigDict
from mcp_server.config import BASE_URL

router = APIRouter()

# --- Pydantic Models for FA Group Requests ---

class AccountAllocation(BaseModel):
    """Model representing a single account within an FA group."""
    id: str = Field(..., description="The account ID.")
    amount: float = Field(..., description="The allocation amount or percentage for this account.")

class FAGroup(BaseModel):
    """
    Model representing a Financial Advisor (FA) group for creation.
    """
    name: str = Field(..., description="The name of the new FA group.")
    method: str = Field(..., description="The allocation method. Valid values: 'NetLiq', 'Equal', 'PctChange', 'AvailableEquity', 'Ratio'.")
    accounts: List[AccountAllocation] = Field(..., description="A list of accounts and their allocations within the group.")

    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "name": "MyTestGroup",
                "method": "Ratio",
                "accounts": [
                    {"id": "DU123456", "amount": 60.0},
                    {"id": "DU123457", "amount": 40.0}
                ]
            }
        }
    )


# --- FA Allocation Management Router Endpoints ---

@router.get(
    "/fa/groups",
    tags=["FA Allocation Management"],
    summary="Get FA Groups",
    description="Returns a list of all Financial Advisor (FA) allocation groups for the currently connected financial advisor."
)
async def get_fa_groups():
    """
    Retrieves all FA groups for the advisor. These groups are used for trade allocation.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/fa/groups", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.post(
    "/fa/groups",
    tags=["FA Allocation Management"],
    summary="Create FA Group",
    description="Creates a new Financial Advisor (FA) allocation group. This endpoint requires the group name, allocation method, and a list of accounts."
)
async def create_fa_group(body: FAGroup = Body(...)):
    """
    Creates a new FA group with a specified allocation method and accounts.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            # The API documentation implies the list of accounts is sent directly as the body.
            # We'll structure it based on the Pydantic model, which aligns with common REST practices.
            # The actual JSON sent will be the list of FAGroup models if the API expects a list.
            # For a single group creation, sending the single object's dict is correct.
            response = await client.post(
                f"{BASE_URL}/fa/groups",
                json=[body.dict()], # The doc example suggests sending a list containing one group object
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}
