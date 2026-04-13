# scanner.py
from fastapi import APIRouter, Body
from fastapi.responses import Response
from typing import List, Optional, Any
import httpx
from pydantic import BaseModel, Field, ConfigDict
from mcp_server.config import BASE_URL

router = APIRouter()

# --- Pydantic Models for Scanner Requests ---

class FilterItem(BaseModel):
    """A single filter for the iServer market scanner."""
    name: str = Field(..., description="The name of the filter, e.g., 'volumeAbove'.")
    value: Any = Field(..., description="The value for the filter.")

class ScannerSubscription(BaseModel):
    """
    Request model for running a market scanner (/iserver/scanner/run).
    This model will be converted to XML internally before sending to the API.
    """
    instrument: str = Field(..., description="The instrument type, e.g., 'STK', 'FUT.US'.")
    type: str = Field(..., description="The scanner type, e.g., 'TOP_PERC_GAIN'.")
    locationCode: str = Field(..., description="The location code, e.g., 'STK.US.MAJOR'.")
    filter: Optional[List[FilterItem]] = Field(None, description="A list of filters for the scan.")

    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "instrument": "STK",
                "type": "TOP_PERC_GAIN",
                "locationCode": "STK.US.MAJOR",
                "filter": [
                    {"name": "volumeAbove", "value": 10000},
                    {"name": "priceAbove", "value": 1}
                ]
            }
        }
    )

class HmdsScannerRequest(BaseModel):
    """
    Request model for running a Historical Market Data Service (HMDS) scanner.
    This model represents the JSON body required by the POST /hmds/scanner endpoint.
    """
    instrument: str = Field(..., description="The instrument type, e.g., 'STK'.")
    locations: str = Field(..., description="A comma-separated list of location codes, e.g., 'STK.US.MAJOR'.")
    scanCode: str = Field(..., description="The scanner type, e.g., 'TOP_PERC_GAIN'.")
    secType: str = Field(..., description="The security type, e.g., 'STK'.")
    filters: Any = Field(None, description="An object containing scanner filters.")

    class ConfigDict:
        json_schema_extra = {
            "example": {
                "instrument": "STK",
                "locations": "STK.US.MAJOR",
                "scanCode": "TOP_PERC_GAIN",
                "secType": "STK",
                "filters": [
                    {"code": "price", "value": 1.0},
                    {"code": "volume", "value": 10000}
                ]
            }
        }


# --- Scanner Router Endpoints ---

@router.get(
    "/iserver/scanner/params",
    tags=["Scanner"],
    summary="Get Scanner Parameters",
    description="Returns an XML file containing all available scanner parameters for the iServer scanner."
)
async def get_scanner_params():
    """
    Retrieves the iServer scanner parameters as an XML file. This information is needed to correctly configure an iServer scanner request.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/scanner/params", timeout=10)
            response.raise_for_status()
            # Return the raw XML content with the correct media type
            return Response(content=response.text, media_type="application/xml")
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.post(
    "/iserver/scanner/run",
    tags=["Scanner"],
    summary="Run iServer Market Scanner",
    description="Runs an iServer market scanner search and returns the top 100 contracts matching the criteria."
)
async def run_scanner(body: ScannerSubscription = Body(...)):
    """
    Submits an iServer scanner configuration and returns the results.
    The JSON request body will be converted to the required XML format.
    """
    # Build the XML string from the Pydantic model
    xml_string = f"<ScannerSubscription><instrument>{body.instrument}</instrument><type>{body.type}</type><locationCode>{body.locationCode}</locationCode>"
    if body.filter:
        xml_string += "<filter>"
        for item in body.filter:
            xml_string += f"<item><name>{item.name}</name><value>{item.value}</value></item>"
        xml_string += "</filter>"
    xml_string += "</ScannerSubscription>"

    headers = {"Content-Type": "application/xml"}

    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/iserver/scanner/run",
                content=xml_string,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.post(
    "/hmds/scanner",
    tags=["Scanner"],
    summary="Run HMDS Market Scanner",
    description="Runs a scanner on the Historical Market Data Service."
)
async def run_hmds_scanner(body: HmdsScannerRequest = Body(...)):
    """
    ### Run HMDS Scanner
    Submits a scanner request to the HMDS. As per the documentation, this endpoint
    first calls `/hmds/auth/init` to authenticate the session before running the scan.

    The request body should be a JSON object specifying the scanner parameters.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            # Initialize HMDS session to prevent 404 error on the first call
            # This is a prerequisite for all /hmds endpoints.
            init_response = await client.get(f"{BASE_URL}/hmds/auth/init", timeout=10)
            init_response.raise_for_status() # Ensure the init call was successful

            # Now, make the actual scanner request
            scanner_response = await client.post(
                f"{BASE_URL}/hmds/scanner",
                json=body.dict(),
                timeout=30
            )
            scanner_response.raise_for_status()
            return scanner_response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}
