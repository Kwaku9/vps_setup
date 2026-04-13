# alerts.py
from fastapi import APIRouter, Query, Body, Path
from typing import List, Optional, Any
import httpx
from pydantic import BaseModel, Field, ConfigDict
from mcp_server.config import BASE_URL

router = APIRouter()

# --- Pydantic Models for Alert Requests ---

class ConditionModel(BaseModel):
    """Model for a single alert condition."""
    type: int = Field(..., description="The condition type. 3 for Price, 5 for Time, 6 for Margin.")
    conidex: str = Field(..., description="Contract identifier and exchange, e.g., '265598@SMART'.")
    operator: str = Field(..., description="The comparison operator, e.g., '>=' or '<='.")
    value: str = Field(..., description="The threshold value for the condition.")
    logicBind: str = Field("and", description="The logical operator to link conditions: 'and' or 'or'.")
    timeZone: Optional[str] = Field(None, description="The timezone for time-based conditions.")
    triggerMethod: Optional[str] = Field(None, description="The trigger method.")


class AlertRequest(BaseModel):
    """
    Request model for creating or modifying an alert.
    """
    orderId: Optional[int] = Field(None, description="The order ID. Required for modifications, omit for new alerts.")
    alertName: str = Field(..., description="The name of the alert.")
    alertMessage: str = Field(..., description="The message to be sent when the alert is triggered.")
    alertActive: int = Field(..., description="Set to 1 to make the alert active, 0 to make it inactive.")
    conditions: List[ConditionModel] = Field(..., description="A list of conditions that trigger the alert.")
    tif: str = Field("GTC", description="The time in force for the alert, e.g., 'GTC' for Good-Til-Cancelled.")
    outsideRth: bool = Field(False, description="Set to true to allow the alert to trigger outside regular trading hours.")
    iTtif: bool = Field(False, description="Set to true to allow the alert to trigger during extended trading hours.")

    class ConfigDict:
        json_schema_extra = {
            "example": {
                "alertName": "Price Alert for IBM",
                "alertMessage": "IBM crossed 175",
                "alertActive": 1,
                "conditions": [{
                    "type": 3,
                    "conidex": "265598@SMART",
                    "operator": ">=",
                    "value": "175",
                    "logicBind": "and"
                }],
                "tif": "GTC"
            }
        }

class AlertActivationRequest(BaseModel):
    """Request model for activating or deactivating an alert."""
    alertId: int = Field(..., description="The ID of the alert to activate or deactivate.")
    alertActive: int = Field(..., description="Set to 1 to activate, 0 to deactivate.")


# --- Alerts Router Endpoints ---

@router.get(
    "/iserver/account/{accountId}/alerts",
    tags=["Alerts"],
    summary="Get Alerts",
    description="Returns a list of alerts for the specified account."
)
async def get_alerts(
    accountId: str = Path(..., description="The account ID.")
):
    """
    Retrieves all alerts associated with a given account.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/account/{accountId}/alerts", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.post(
    "/iserver/account/{accountId}/alert",
    tags=["Alerts"],
    summary="Create or Modify Alert",
    description="Create a new alert or modify an existing one. To modify, include the `orderId` in the request body."
)
async def create_or_modify_alert(
    accountId: str = Path(..., description="The account ID."),
    body: AlertRequest = Body(...)
):
    """
    Creates a new alert or modifies an existing one for the specified account.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/iserver/account/{accountId}/alert",
                json=body.dict(exclude_none=True),
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.delete(
    "/iserver/account/{accountId}/alert/{alertId}",
    tags=["Alerts"],
    summary="Delete Alert",
    description="Deletes a single alert for the given account."
)
async def delete_alert(
    accountId: str = Path(..., description="The account ID."),
    alertId: str = Path(..., description="The ID of the alert to delete.")
):
    """
    Deletes a specific alert by its ID.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.delete(
                f"{BASE_URL}/iserver/account/{accountId}/alert/{alertId}",
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/iserver/account/mta",
    tags=["Alerts"],
    summary="Get MTA Alert",
    description="Each login user has a unique Mobile Trading Assistant (MTA) alert with a description, status, and other fields. This endpoint retrieves that alert."
)
async def get_mta_alert():
    """
    Fetches the Mobile Trading Assistant (MTA) alert for the current user.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/account/mta", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.post(
    "/iserver/account/alert/activate",
    tags=["Alerts"],
    summary="Activate or Deactivate Alert",
    description="Activates or deactivates an existing alert. Requires the alert ID."
)
async def activate_deactivate_alert(body: AlertActivationRequest = Body(...)):
    """
    Toggles the active status of an alert.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/iserver/account/alert/activate",
                json=body.dict(),
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}
