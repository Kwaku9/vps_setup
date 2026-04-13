# contract.py
from fastapi import APIRouter, Query, Body, Path
from typing import List, Optional
import httpx
from pydantic import BaseModel, Field, ConfigDict
from mcp_server.config import BASE_URL

router = APIRouter()

# --- Pydantic Models ---

class ContractRulesRequest(BaseModel):
    """Request model for the Contract Rules endpoint."""
    conid: int = Field(..., description="The contract ID for which to retrieve trading rules.")
    isBuy: bool = Field(..., description="Specify true for buy side rules, false for sell side rules.")

    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "conid": 265598, # IBM
                "isBuy": True
            }
        }
    )


# --- Contract Router Endpoints ---

@router.get(
    "/iserver/contract/{conid}/algos",
    tags=["Contract"],
    summary="Get IB Algos",
    description="Returns a list of available IB Algos for a contract."
)
async def get_contract_algos(
    conid: int = Path(..., description="The contract ID."),
    algos: Optional[str] = Query(None, description="A comma-separated list of IB Algos to query."),
    addDescription: Optional[str] = Query(None, description="Set to 1 to receive algorithm descriptions."),
    addParams: Optional[str] = Query(None, description="Set to 1 to receive algorithm parameters.")
):
    """
    Retrieves a list of supported IB Algos for a given instrument.
    """
    params = {}
    if algos:
        params["algos"] = algos
    if addDescription:
        params["addDescription"] = addDescription
    if addParams:
        params["addParams"] = addParams

    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/contract/{conid}/algos", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/iserver/contract/{conid}/info-and-rules",
    tags=["Contract"],
    summary="Get Contract Info and Rules",
    description="Returns a conglomeration of contract information and trading rules."
)
async def get_contract_info_and_rules(
    conid: int = Path(..., description="The contract ID."),
    isBuy: bool = Query(..., description="Side of the market: true for Buy, false for Sell.")
):
    """
    Retrieves a combination of contract details and associated trading rules in a single call.
    """
    params = {"isBuy": isBuy}
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/contract/{conid}/info-and-rules", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}


@router.get(
    "/iserver/contract/{conid}/info",
    tags=["Contract"],
    summary="Contract Information",
    description="Get full contract details for a given contract ID (conid)."
)
async def get_contract_info(
    conid: int = Path(..., description="The contract ID.")
):
    """
    Retrieves detailed information about a specific contract using its conid.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/contract/{conid}/info", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/iserver/secdef/bond-filters",
    tags=["Contract"],
    summary="Get Bond Filters",
    description="Returns a list of available bond filters for a given issuer."
)
async def get_bond_filters(
    issuerId: str = Query(..., description="Specifies the issuerId value used to designate the bond issuer type.")
):
    """
    Retrieves a list of filters that can be used when searching for bonds.
    """
    params = {
        "symbol": "BOND",
        "issuerId": issuerId
    }
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/secdef/bond-filters", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/iserver/secdef/currency",
    tags=["Contract"],
    summary="Search Currency Pairs",
    description="Search for currency pairs."
)
async def search_currency_pairs(
    symbol: str = Query(..., description="The currency pair (e.g., EUR.USD).")
):
    """
    Retrieves information about a currency pair. Corresponds to the user's request for /iserver/currency/pairs.
    """
    params = {"symbol": symbol}
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/secdef/currency", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/iserver/secdef/info",
    tags=["Contract"],
    summary="Secdef Info",
    description="Provides security definition and rules information for a given conid."
)
async def get_secdef_info(
    conid: str = Query(..., description="The contract ID."),
    secType: str = Query(..., description="The security type."),
    month: Optional[str] = Query(None, description="The expiration month for options/futures (e.g., 'DEC23')."),
    exchange: Optional[str] = Query(None, description="The exchange to query."),
    strike: Optional[float] = Query(None, description="The strike price for options."),
    right: Optional[str] = Query(None, description="The right for options: 'C' for Call, 'P' for Put.")
):
    """
    A comprehensive endpoint to get instrument metadata and rules in one call.
    """
    params = {"conid": conid, "sectype": secType}
    if month:
        params["month"] = month
    if exchange:
        params["exchange"] = exchange
    if strike:
        params["strike"] = strike
    if right:
        params["right"] = right

    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/secdef/info", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/iserver/secdef/search",
    tags=["Contract"],
    summary="Search by Symbol or Name",
    description="Search for contracts by symbol or company name. Returns a list of matching contracts."
)
async def search_contract_by_symbol_or_name(
    symbol: str = Query(..., description="The symbol or company name to search for."),
    name: Optional[bool] = Query(False, description="Set to true to search by company name instead of symbol."),
    secType: Optional[str] = Query(None, description="The security type to filter by (e.g., STK, OPT, FUT).")
):
    """
    Searches for contracts based on a symbol or name. This is a primary method for finding a contract's conid.
    """
    params = {"symbol": symbol}
    if name is not None:
        params["name"] = str(name).lower()
    if secType:
        params["sectype"] = secType

    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/secdef/search", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.post(
    "/iserver/contract/rules",
    tags=["Contract"],
    summary="Contract Rules",
    description="Returns trading rules for a contract. The request body requires the conid and a boolean for the side."
)
async def get_contract_rules(body: ContractRulesRequest = Body(...)):
    """
    Fetches the trading rules for a given contract, such as order types and sizes.
    """
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/iserver/contract/rules",
                json=body.dict(),
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/iserver/secdef/strikes",
    tags=["Contract"],
    summary="Option Strikes",
    description="Get a list of available option strikes for a given underlying contract ID (conid)."
)
async def get_strikes(
    conid: int = Query(..., description="The contract ID of the underlying security."),
    secType: str = Query(..., description="The security type (e.g., OPT, WAR)."),
    month: str = Query(..., description="The expiration month in 'MMMYY' format (e.g., JAN25)."),
    exchange: Optional[str] = Query(None, description="The exchange to filter by. Defaults to SMART.")
):
    """
    Retrieves available strike prices for an options contract based on the underlying conid, security type, and expiration.
    """
    params = {"conid": conid, "sectype": secType, "month": month}
    if exchange:
        params["exchange"] = exchange
        
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/iserver/secdef/strikes", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/trsrv/futures",
    tags=["Contract"],
    summary="Futures Details by Symbol",
    description="Returns a list of futures for the given symbols."
)
async def get_trsrv_futures_by_symbol(
    symbols: str = Query(..., description="A comma-separated list of underlying symbols.")
):
    """
    Get detailed information about futures contracts for given symbols.
    """
    params = {"symbols": symbols}
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/trsrv/futures", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/trsrv/secdef",
    tags=["Contract"],
    summary="Security Definitions by Conid",
    description="Returns a list of security definitions for the given conids."
)
async def get_secdef_by_conids(
    conids: str = Query(..., description="A comma-separated list of contract IDs.")
):
    """
    Retrieves security definitions for one or more contracts.
    """
    params = {"conids": conids}
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/trsrv/secdef", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/trsrv/stocks",
    tags=["Contract"],
    summary="Stocks by Symbol",
    description="Returns a list of stock contracts for the given symbols."
)
async def get_stocks_by_symbol(
    symbols: str = Query(..., description="A comma-separated list of stock symbols.")
):
    """
    Fetches stock contracts for a list of symbols. This is more direct than a general search if you know you are looking for stocks.
    """
    params = {"symbols": symbols}
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/trsrv/stocks", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}

@router.get(
    "/trsrv/secdef/schedule",
    tags=["Contract"],
    summary="Trading Schedule",
    description="Returns the trading schedule for a contract."
)
async def get_trading_schedule(
    assetClass: str = Query(..., description="The asset class of the contract, e.g., 'STK', 'OPT', 'FUT'."),
    symbol: str = Query(..., description="The underlying symbol."),
    exchange: Optional[str] = Query(None, description="The exchange to query."),
    exchangeFilter: Optional[str] = Query(None, description="The exchange filter.")
):
    """
    Retrieves the trading schedule for a given contract.
    """
    params = {"assetclass": assetClass, "symbol": symbol}
    if exchange:
        params["exchange"] = exchange
    if exchangeFilter:
        params["exchangeFilter"] = exchangeFilter

    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(f"{BASE_URL}/trsrv/secdef/schedule", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            return {"error": "IBKR API Error", "status_code": exc.response.status_code, "detail": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": "Request Error", "detail": str(exc)}
