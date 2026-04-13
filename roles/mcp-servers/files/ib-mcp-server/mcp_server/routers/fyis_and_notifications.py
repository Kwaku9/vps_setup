# fyis_and_notifications.py
from fastapi import APIRouter, Body, Path, Query
from typing import List, Optional
import httpx
from pydantic import BaseModel, Field, ConfigDict
from mcp_server.config import BASE_URL

router = APIRouter()

# --- Pydantic Models for FYI Requests ---

class DeliveryOptionsRequest(BaseModel):
    """Request model for enabling/disabling notifications."""
    enabled: bool = Field(..., description="True to enable, false to disable.")

class DeviceDeliveryOptionsRequest(BaseModel):
    """Request model for enabling/disabling device notifications."""
    deviceId: str = Field(..., description="The device ID.")
    uiName: str = Field(..., description="The name of the UI.")
    enabled: bool = Field(..., description="True to enable, false to disable.")

class FYISettingsGetRequest(BaseModel):
    """Request model for getting a list of disclaimer notifications."""
    typeCodes: List[str] = Field(..., description="A list of FYI type codes.")

class FYISettingsRequest(BaseModel):
    """Request model for enabling/disabling disclaimer type notifications."""
    enabled: bool = Field(..., description="True to enable, false to disable.")

class MarkReadRequest(BaseModel):
    """Request model for marking notifications as read."""
    notificationIds: List[str] = Field(..., description="A list of notification IDs to mark as read.")


# --- FYIs and Notifications Router Endpoints ---

@router.get(
    "/fyi/unreadnumber",
    tags=["FYIs and Notifications"],
    summary="Get Unread Number of FYIs",
    description="Returns the total number of unread FYI notifications."
)
async def get_fyi_unread_number():
    """
    Retrieves the count of unread notifications.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/fyi/unreadnumber", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/fyi/deliveryoptions",
    tags=["FYIs and Notifications"],
    summary="Get FYI Delivery Options",
    description="Returns a list of all supported delivery options."
)
async def get_fyi_delivery_options():
    """
    Fetches the available FYI delivery options.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/fyi/deliveryoptions", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.post(
    "/fyi/deliveryoptions",
    tags=["FYIs and Notifications"],
    summary="Enable/Disable FYI Delivery Options",
    description="Enables or disables a delivery option."
)
async def configure_fyi_delivery_options(body: DeliveryOptionsRequest = Body(...)):
    """
    Enables or disables a specific FYI delivery option.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(f"{BASE_URL}/fyi/deliveryoptions", json=body.dict(), timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.put(
    "/fyi/deliveryoptions/device",
    tags=["FYIs and Notifications"],
    summary="Enable Device Notifications",
    description="Enables or disables notifications for a specific device."
)
async def configure_device_delivery_options(body: DeviceDeliveryOptionsRequest = Body(...)):
    """
    Configures FYI notifications for a specific device.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.put(f"{BASE_URL}/fyi/deliveryoptions/device", json=body.dict(), timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.post(
    "/fyi/settings",
    tags=["FYIs and Notifications"],
    summary="Get FYI Settings",
    description="Returns a list of disclaimer-type notifications."
)
async def get_fyi_settings(body: FYISettingsGetRequest = Body(...)):
    """
    Retrieves the settings for a list of disclaimer type notifications.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(f"{BASE_URL}/fyi/settings", json=body.dict(), timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.put(
    "/fyi/settings/{typecode}",
    tags=["FYIs and Notifications"],
    summary="Enable/Disable FYI Setting",
    description="Enables or disables a specific disclaimer-type notification."
)
async def configure_fyi_setting(
    typecode: str = Path(..., description="The FYI type code to configure."),
    body: FYISettingsRequest = Body(...)
):
    """
    Enables or disables a specific FYI setting by its type code.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.put(f"{BASE_URL}/fyi/settings/{typecode}", json=body.dict(), timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.delete(
    "/fyi/notifications",
    tags=["FYIs and Notifications"],
    summary="Mark Notifications as Read",
    description="Marks a list of notifications as read."
)
async def mark_notifications_as_read(body: MarkReadRequest = Body(...)):
    """
    Marks one or more notifications as read by their IDs.
    Note: The documentation specifies using a DELETE method with a request body.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            # Using request to handle DELETE with body, as httpx.delete doesn't directly support it.
            request = client.build_request("DELETE", f"{BASE_URL}/fyi/notifications", json=body.dict())
            response = await client.send(request, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/fyi/notifications",
    tags=["FYIs and Notifications"],
    summary="Get Notifications",
    description="Returns a list of notifications."
)
async def get_notifications(
    exclude: Optional[str] = Query(None, description="A comma-separated list of notification IDs to exclude from the response."),
    include: Optional[str] = Query(None, description="A comma-separated list of notification IDs to include in the response."),
    max_count: int = Query(10, alias="max", description="The maximum number of notifications to return.")
):
    """
    Retrieves a list of notifications, with options to filter and limit the results.
    """
    params = {"max": max_count}
    if exclude:
        params["exclude"] = exclude
    if include:
        params["include"] = include
        
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/fyi/notifications", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}
