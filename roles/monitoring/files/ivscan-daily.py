#!/usr/bin/env python3
"""
Daily IV Z-Score Scanner — S&P 500 Implied Volatility Analysis

Iterates all S&P 500 tickers directly (no IBKR scanner API), resolves conids
once (cached to disk), fetches IV snapshots in batches, pre-filters by IV level,
analyzes option term structure (backwardation/contango), then computes full
HV20/z-score metrics on candidates. Results are persisted to PostgreSQL for
Grafana dashboard visualization.

Strategy: Optimized for 30-90 DTE options trading.
  - Sell premium (high IV): look for backwardation (near-term IV > far-term IV)
  - Buy premium (low IV): look for contango (near-term IV <= far-term IV)
  - Sweet spot: 45 DTE entry, 21 DTE exit

Designed to run as a cron job Mon-Fri at 16:30 ET (after market close).

Dependencies: Python 3.x stdlib only (no pip packages).
"""

import json
import math
import logging
import os
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# Configuration
IBEAM_BASE = "https://127.0.0.1:5055/v1/api"
PG_CONTAINER = "postgres"
PG_USER = "postgres"
PG_DB = "enterprise"
PODMAN = "/usr/bin/podman"

# Conid cache
CACHE_DIR = "/var/lib/ivscan"
CACHE_FILE = os.path.join(CACHE_DIR, "sp500_conids.json")
CACHE_MAX_AGE_DAYS = 30

# Snapshot batching
SNAPSHOT_BATCH_SIZE = 20
SNAPSHOT_DELAY = 2.5  # seconds between subscribe and read
BATCH_DELAY = 1.0     # seconds between batches

# Pre-filter thresholds (wide gate — let z-score/rank do the real filtering)
HIGH_IV_THRESHOLD = 0.20   # IV > 20% = potential sell-premium candidate
LOW_IV_THRESHOLD = 0.30    # IV < 30% = potential buy-premium candidate
MIN_VOLUME = 100_000

# Full metrics thresholds
Z_SCORE_THRESHOLD = 1.75
Z_SCORE_MAX = 3.0

# Conid / option resolution rate limit
RESOLVE_DELAY = 0.2  # 5 lookups/sec

# Term structure DTE windows
NEAR_DTE_TARGET = 30   # near-term bucket
NEAR_DTE_MIN = 20
NEAR_DTE_MAX = 50
FAR_DTE_TARGET = 90    # far-term bucket
FAR_DTE_MIN = 60
FAR_DTE_MAX = 120
SWEET_SPOT_DTE = 45    # ideal entry DTE
SWEET_SPOT_MIN = 30
SWEET_SPOT_MAX = 60

# S&P 500 tickers (updated 2026-02-21)
SP500 = sorted(set(filter(None, """
AAPL,ABBV,ABT,ACN,ADBE,ADI,ADM,ADP,ADSK,AEE,AEP,AES,AFL,AIG,AIZ,
AJG,AKAM,ALB,ALGN,ALL,ALLE,AMAT,AMCR,AMD,AME,AMGN,AMP,AMT,AMZN,
ANET,AON,AOS,APA,APD,APH,APTV,ARE,ARES,ATO,AVGO,AVY,AWK,AXON,AXP,
AZO,BA,BAC,BAX,BBY,BDX,BEN,BG,BIIB,BK,BKNG,BKR,BLK,BLDR,
BMY,BR,BRO,BSX,BX,BXP,BALL,CAG,CAH,CARR,CAT,CB,CBOE,CCI,
CCL,CDNS,CDW,CE,CEG,CF,CFG,CHD,CHRW,CHTR,CI,CIEN,CINF,CL,CLX,
CMS,CNC,CNP,COF,COO,COP,COR,COST,CPAY,CPRT,CPT,CRL,CRM,CSGP,
CSCO,CTAS,CTRA,CTSH,CTVA,CVNA,CVS,CVX,CRH,CME,CMG,CMI,D,DAL,
DASH,DD,DE,DECK,DG,DGX,DHI,DHR,DIS,DLTR,DOC,DOV,DOW,DPZ,DRI,
DTE,DUK,DVA,DVN,DDOG,DELL,DXCM,EA,EBAY,ECL,ED,EFX,EG,EIX,EL,
EME,EMR,EQIX,EQR,EQT,ERIE,ES,ESS,ETN,ETR,EVRG,EW,EXC,EXE,EXR,
EXPD,EXPE,F,FANG,FAST,FSLR,FTNT,FCX,FDS,FDX,FE,FFIV,FICO,FIS,
FISV,FITB,FIX,FOX,FOXA,FRT,FTV,GD,GDDY,GE,GEHC,GEN,GEV,GILD,
GIS,GL,GLW,GM,GNRC,GOOG,GOOGL,GPC,GPN,GRMN,GS,GWW,HAL,HAS,
HBAN,HCA,HD,HOLX,HON,HOOD,HPE,HPQ,HRL,HSIC,HST,HSY,HUBB,HUM,
HWM,HIG,HII,HLT,IBM,ICE,IDXX,IEX,IFF,INCY,INTC,INTU,INVH,IP,
IQV,IR,IRM,ISRG,IT,ITW,IVZ,J,JBHT,JBL,JCI,JKHY,JNJ,JPM,KDP,
KEYS,KHC,KIM,KLAC,KMB,KMI,KO,KR,KKR,KVUE,L,LDOS,LEN,LH,LHX,
LII,LIN,LLY,LMT,LNT,LOW,LRCX,LULU,LUV,LVS,LW,LYB,LYV,MA,MAA,
MAR,MAS,MCD,MCHP,MCK,MCO,MDLZ,MDT,MET,META,MGM,MKC,MLKN,MLM,
MMM,MNST,MO,MOH,MOS,MPC,MPWR,MRK,MRNA,MS,MSCI,MSFT,MSI,
MTB,MTCH,MTD,MU,NCLH,NDAQ,NDSN,NEM,NFLX,NI,NKE,NOC,NOW,NRG,
NSC,NTAP,NTRS,NUE,NVDA,NVR,NWSA,NWS,NXPI,O,ODFL,OKE,OMC,ON,
ORCL,ORLY,OTIS,OXY,PANW,PAYC,PAYX,PCAR,PCG,PEG,PEP,PFE,PFG,PG,
PGR,PH,PHM,PKG,PLD,PLTR,PM,PNC,PNR,PNW,PODD,POOL,PPG,PPL,PRU,
PSA,PSX,PTC,PVH,PWR,PYPL,QCOM,RCL,REG,REGN,RF,RJF,
RL,RMD,ROK,ROL,ROP,ROST,RSG,RTX,RVTY,SBAC,SBUX,SCHW,SHW,SJM,
SLB,SMCI,SNA,SNPS,SO,SOLV,SPG,SPGI,SRE,STE,STLD,STT,STX,STZ,
SW,SWK,SWKS,SYF,SYK,SYY,T,TAP,TDG,TDY,TECH,TEL,TER,TFC,TGT,
TJX,TKO,TMO,TMUS,TPL,TPR,TRGP,TRMB,TROW,TRV,TSCO,TSLA,TSN,
TT,TTD,TTWO,TXN,TXT,TYL,UAL,UBER,UDR,UHS,ULTA,UNH,UNP,UPS,
URI,USB,V,VICI,VLO,VLTO,VMC,VRSK,VRSN,VRTX,VST,VTR,VZ,WAB,
WAT,WBA,WBD,WDC,WEC,WELL,WFC,WM,WMB,WMT,WRB,WSM,WST,WTW,
WY,WYNN,XEL,XOM,XYL,YUM,ZBH,ZBRA,ZTS
""".replace("\n", ",").replace(" ", "").split(","))))

MONTH_ABBRS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ivscan")

# SSL context for self-signed IBeam cert
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# IBKR API helpers
# ---------------------------------------------------------------------------

def ib_request(path, method="GET", body=None):
    """Make a request to the IBeam gateway."""
    url = f"{IBEAM_BASE}{path}"
    headers = {"Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        log.warning("HTTP %d on %s %s", e.code, method, path)
        return None
    except Exception as e:
        log.warning("Request failed %s %s: %s", method, path, e)
        return None


def check_session():
    """Verify IBeam is authenticated."""
    data = ib_request("/tickle")
    if not data:
        return False
    auth = data.get("iserver", {}).get("authStatus", {})
    if not auth.get("authenticated") or not auth.get("connected"):
        log.error("IBeam not authenticated: %s", auth)
        return False
    log.info("IBeam session OK (user=%s)", data.get("userId"))
    return True


# ---------------------------------------------------------------------------
# Phase 1: Conid Resolution (cached)
# ---------------------------------------------------------------------------

def load_conid_cache():
    """Load cached conid map if fresh enough."""
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        mtime = os.path.getmtime(CACHE_FILE)
        age_days = (time.time() - mtime) / 86400
        if age_days > CACHE_MAX_AGE_DAYS:
            log.info("Conid cache is %.0f days old (max %d), will refresh", age_days, CACHE_MAX_AGE_DAYS)
            return None
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        log.info("Loaded conid cache: %d tickers (%.0f days old)", len(cache), age_days)
        return cache
    except Exception as e:
        log.warning("Failed to load conid cache: %s", e)
        return None


def save_conid_cache(cache):
    """Persist conid map to disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)
    log.info("Saved conid cache: %d tickers", len(cache))


def resolve_conid(ticker):
    """Resolve a single ticker to its primary US stock conid."""
    data = ib_request("/iserver/secdef/search", method="POST", body={"symbol": ticker, "secType": "STK"})
    if not data or not isinstance(data, list):
        return None
    for entry in data:
        if entry.get("description", "").upper() == ticker or entry.get("symbol", "").upper() == ticker:
            conid = entry.get("conid")
            if conid:
                return int(conid)
    if data and data[0].get("conid"):
        return int(data[0]["conid"])
    return None


def resolve_all_conids():
    """Resolve conids for all S&P 500 tickers, using cache when available."""
    cache = load_conid_cache()
    if cache is not None:
        missing = [t for t in SP500 if t not in cache]
        if not missing:
            return cache
        log.info("Resolving %d new tickers not in cache", len(missing))
    else:
        cache = {}
        missing = list(SP500)
        log.info("Resolving all %d S&P 500 tickers (no cache)", len(missing))

    resolved = 0
    failed = []
    for i, ticker in enumerate(missing):
        if i > 0 and i % 50 == 0:
            log.info("  Resolved %d/%d tickers...", i, len(missing))
        conid = resolve_conid(ticker)
        if conid:
            cache[ticker] = conid
            resolved += 1
        else:
            failed.append(ticker)
        time.sleep(RESOLVE_DELAY)

    log.info("Conid resolution complete: %d resolved, %d failed", resolved, len(failed))
    if failed:
        log.warning("Failed tickers: %s", ", ".join(failed[:20]))

    save_conid_cache(cache)
    return cache


# ---------------------------------------------------------------------------
# Phase 2: Batch IV Snapshot
# ---------------------------------------------------------------------------

def parse_iv(value):
    """Parse IV from snapshot field — may be string like '35.5%' or number."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace("%", "").strip()
        if not value:
            return None
        try:
            v = float(value)
        except ValueError:
            return None
    else:
        v = float(value)
    if v > 1:
        v /= 100.0
    return v


def parse_price(value):
    """Parse price from snapshot field."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace(",", "").strip()
        if not value or value.startswith("C") or value.startswith("H"):
            return None
        try:
            return float(value)
        except ValueError:
            return None
    return float(value)


def parse_volume(vol_raw):
    """Parse volume from snapshot field — handles K/M suffixes."""
    if vol_raw is None:
        return 0
    if isinstance(vol_raw, str):
        vol_raw = vol_raw.replace(",", "").upper()
        if vol_raw.endswith("M"):
            return int(float(vol_raw[:-1]) * 1_000_000)
        elif vol_raw.endswith("K"):
            return int(float(vol_raw[:-1]) * 1_000)
        else:
            try:
                return int(float(vol_raw))
            except ValueError:
                return 0
    return int(vol_raw)


def get_snapshot_batch(conids):
    """Get market data snapshot for a batch of conids. Returns dict of conid -> {price, iv, volume}."""
    conid_str = ",".join(str(c) for c in conids)
    fields = "31,7283,87"  # 31=last, 7283=IV%, 87=today's volume

    # First call subscribes
    ib_request(f"/iserver/marketdata/snapshot?conids={conid_str}&fields={fields}")
    time.sleep(SNAPSHOT_DELAY)
    # Second call gets data
    data = ib_request(f"/iserver/marketdata/snapshot?conids={conid_str}&fields={fields}")
    if not data:
        return {}

    results = {}
    for item in data:
        cid = item.get("conid", item.get("conidEx", ""))
        if isinstance(cid, str) and "@" in cid:
            cid = int(cid.split("@")[0])
        else:
            cid = int(cid) if cid else 0

        results[cid] = {
            "price": parse_price(item.get("31")),
            "iv": parse_iv(item.get("7283")),
            "volume": parse_volume(item.get("87")),
        }
    return results


def fetch_all_snapshots(conid_map):
    """Fetch IV snapshots for all tickers in batches. Returns {ticker: {price, iv, volume}}."""
    tickers = list(conid_map.keys())
    all_results = {}

    batches = [tickers[i:i + SNAPSHOT_BATCH_SIZE] for i in range(0, len(tickers), SNAPSHOT_BATCH_SIZE)]
    log.info("Fetching snapshots: %d tickers in %d batches of %d", len(tickers), len(batches), SNAPSHOT_BATCH_SIZE)

    for batch_idx, batch_tickers in enumerate(batches):
        if batch_idx > 0:
            time.sleep(BATCH_DELAY)

        conids = [conid_map[t] for t in batch_tickers]
        snapshots = get_snapshot_batch(conids)

        for ticker in batch_tickers:
            cid = conid_map[ticker]
            snap = snapshots.get(cid, {})
            all_results[ticker] = snap

        if (batch_idx + 1) % 5 == 0 or batch_idx == len(batches) - 1:
            log.info("  Snapshot batch %d/%d done", batch_idx + 1, len(batches))

    return all_results


# ---------------------------------------------------------------------------
# Phase 3: Pre-filter
# ---------------------------------------------------------------------------

def prefilter_candidates(snapshots, conid_map):
    """Pre-filter tickers by IV level and volume. Returns {direction: [(ticker, conid, snap), ...]}."""
    high_candidates = []
    low_candidates = []
    skipped_no_data = 0
    skipped_low_vol = 0

    for ticker, snap in snapshots.items():
        price = snap.get("price")
        iv = snap.get("iv")
        volume = snap.get("volume", 0)

        if price is None or iv is None or iv < 0.001:
            skipped_no_data += 1
            continue
        if volume < MIN_VOLUME:
            skipped_low_vol += 1
            continue

        conid = conid_map[ticker]
        entry = (ticker, conid, snap)

        if iv > HIGH_IV_THRESHOLD:
            high_candidates.append(entry)
        if iv < LOW_IV_THRESHOLD:
            low_candidates.append(entry)

    log.info(
        "Pre-filter: %d high IV (>%.0f%%), %d low IV (<%.0f%%), "
        "skipped %d no-data, %d low-volume",
        len(high_candidates), HIGH_IV_THRESHOLD * 100,
        len(low_candidates), LOW_IV_THRESHOLD * 100,
        skipped_no_data, skipped_low_vol,
    )
    return {
        "high": high_candidates,
        "low": low_candidates,
        "skipped_no_data": skipped_no_data,
        "skipped_low_vol": skipped_low_vol,
    }


# ---------------------------------------------------------------------------
# Phase 3.5: Term Structure Analysis (30-90 DTE)
# ---------------------------------------------------------------------------

def expiry_to_month_code(expiry_yyyymmdd):
    """Convert YYYYMMDD to MMMYY (e.g., '20260320' -> 'MAR26')."""
    dt = datetime.strptime(expiry_yyyymmdd, "%Y%m%d")
    return f"{MONTH_ABBRS[dt.month - 1]}{dt.strftime('%y')}"


def get_option_expirations(symbol):
    """Get available option expiration dates for a symbol via chain endpoint.
    Returns sorted list of YYYYMMDD strings."""
    data = ib_request(f"/trsrv/secdef/chains?symbol={symbol}")
    if not data:
        return []

    expirations = set()

    # The response format varies. Try multiple parsing strategies.
    chains = data if isinstance(data, dict) else {}

    # Format A: {"chains": {"C": {"20260320": [strikes], ...}, "P": {...}}}
    # Also handles "call"/"put" keys
    chain_data = chains.get("chains", chains)
    if isinstance(chain_data, dict):
        for right_key in ("C", "P", "call", "put", "CALL", "PUT"):
            section = chain_data.get(right_key, {})
            if isinstance(section, dict):
                for key in section:
                    if isinstance(key, str) and key.isdigit() and len(key) == 8:
                        expirations.add(key)

    # Format B: {"chains": [{"expirations": [...]}]}
    chain_list = chains.get("chains", [])
    if isinstance(chain_list, list):
        for item in chain_list:
            if isinstance(item, dict):
                for exp in item.get("expirations", []):
                    if isinstance(exp, str) and len(exp) == 8 and exp.isdigit():
                        expirations.add(exp)

    return sorted(expirations)


def find_nearest_expirations(expirations):
    """Find near (~30 DTE), far (~90 DTE), and sweet-spot (~45 DTE) expirations.
    Returns (near_exp, near_dte, far_exp, far_dte, target_dte) or Nones."""
    today = datetime.now()
    exp_with_dte = []
    for exp_str in expirations:
        try:
            exp_date = datetime.strptime(exp_str, "%Y%m%d")
            dte = (exp_date - today).days
            if dte > 0:
                exp_with_dte.append((exp_str, dte))
        except ValueError:
            continue

    if not exp_with_dte:
        return None, None, None, None, None

    # Near: closest to 30 DTE within [20, 50]
    near_pool = [(e, d) for e, d in exp_with_dte if NEAR_DTE_MIN <= d <= NEAR_DTE_MAX]
    near = min(near_pool, key=lambda x: abs(x[1] - NEAR_DTE_TARGET), default=None)

    # Far: closest to 90 DTE within [60, 120]
    far_pool = [(e, d) for e, d in exp_with_dte if FAR_DTE_MIN <= d <= FAR_DTE_MAX]
    far = min(far_pool, key=lambda x: abs(x[1] - FAR_DTE_TARGET), default=None)

    # Sweet spot: closest to 45 DTE within [30, 60]
    sweet_pool = [(e, d) for e, d in exp_with_dte if SWEET_SPOT_MIN <= d <= SWEET_SPOT_MAX]
    sweet = min(sweet_pool, key=lambda x: abs(x[1] - SWEET_SPOT_DTE), default=None)

    target_dte = sweet[1] if sweet else (near[1] if near else None)

    return (
        near[0] if near else None,
        near[1] if near else None,
        far[0] if far else None,
        far[1] if far else None,
        target_dte,
    )


def get_options_for_month(underlying_conid, month_code):
    """Get option contracts for a specific month via /iserver/secdef/info.
    Returns list of dicts with conid, strike, right, maturityDate, etc."""
    data = ib_request(
        f"/iserver/secdef/info?conid={underlying_conid}&secType=OPT&month={month_code}"
    )
    if not data:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Response might be wrapped
        return data.get("secdef", data.get("contracts", data.get("data", [])))
    return []


def find_atm_call_conid(options, target_price):
    """Find the ATM call option conid from a list of option contracts."""
    calls = []
    for o in options:
        right = str(o.get("right", o.get("putOrCall", ""))).upper()
        if right in ("C", "CALL"):
            strike = o.get("strike")
            conid = o.get("conid")
            if strike is not None and conid is not None:
                calls.append((int(conid), float(strike)))

    if not calls:
        return None

    # Closest strike to target price
    best_conid, best_strike = min(calls, key=lambda x: abs(x[1] - target_price))
    return best_conid


def analyze_term_structure(all_candidates, conid_map):
    """Analyze option term structure for pre-filtered candidates.

    For each candidate:
    1. Get option chain expirations
    2. Find near (~30 DTE) and far (~90 DTE) expirations
    3. Resolve ATM call conids at each expiration
    4. Batch snapshot to get IV at each expiration
    5. Compute term structure slope = (IV_near - IV_far) / IV_far

    Returns dict: ticker -> {iv_30d, iv_90d, term_slope, target_dte, near_dte, far_dte}
    """
    term_data = {}
    option_lookups = []  # (ticker, near_opt_conid, far_opt_conid, near_dte, far_dte, target_dte)

    log.info("Resolving option chains for %d candidates...", len(all_candidates))

    for ticker, conid, snap in all_candidates:
        price = snap["price"]

        # Step 1: Get available expirations
        exps = get_option_expirations(ticker)
        if not exps:
            log.debug("  %s: no option expirations", ticker)
            continue

        # Step 2: Find near/far/target expirations
        near_exp, near_dte, far_exp, far_dte, target_dte = find_nearest_expirations(exps)
        if not near_exp or not far_exp:
            log.debug("  %s: missing near(%s)/far(%s) expiration", ticker, near_exp, far_exp)
            continue

        # Step 3: Get option contracts for near and far months
        near_month = expiry_to_month_code(near_exp)
        far_month = expiry_to_month_code(far_exp)

        near_options = get_options_for_month(conid, near_month)
        time.sleep(RESOLVE_DELAY)
        far_options = get_options_for_month(conid, far_month)
        time.sleep(RESOLVE_DELAY)

        if not near_options or not far_options:
            log.debug("  %s: no options for %s/%s", ticker, near_month, far_month)
            continue

        # Step 4: Find ATM call conids
        near_opt_conid = find_atm_call_conid(near_options, price)
        far_opt_conid = find_atm_call_conid(far_options, price)

        if not near_opt_conid or not far_opt_conid:
            log.debug("  %s: could not find ATM calls", ticker)
            continue

        option_lookups.append((ticker, near_opt_conid, far_opt_conid, near_dte, far_dte, target_dte))

    if not option_lookups:
        log.info("Term structure: no candidates with valid option chains")
        return term_data

    log.info("Term structure: resolved chains for %d candidates, snapshotting...", len(option_lookups))

    # Step 5: Batch snapshot all option conids
    all_opt_conids = []
    for _, near_cid, far_cid, _, _, _ in option_lookups:
        all_opt_conids.extend([near_cid, far_cid])

    opt_snaps = {}
    batches = [all_opt_conids[i:i + SNAPSHOT_BATCH_SIZE]
               for i in range(0, len(all_opt_conids), SNAPSHOT_BATCH_SIZE)]
    for batch in batches:
        snap = get_snapshot_batch(batch)
        opt_snaps.update(snap)
        time.sleep(BATCH_DELAY)

    # Step 6: Compute term structure slope
    for ticker, near_cid, far_cid, near_dte, far_dte, target_dte in option_lookups:
        near_iv = opt_snaps.get(near_cid, {}).get("iv")
        far_iv = opt_snaps.get(far_cid, {}).get("iv")

        slope = None
        if near_iv and far_iv and far_iv > 0.001:
            slope = round((near_iv - far_iv) / far_iv, 3)

        term_data[ticker] = {
            "iv_30d": near_iv,
            "iv_90d": far_iv,
            "term_slope": slope,
            "target_dte": target_dte,
            "near_dte": near_dte,
            "far_dte": far_dte,
        }

        if slope is not None:
            label = "BACKWARDATION" if slope > 0 else "CONTANGO"
            log.info(
                "  %s: IV%dD=%.1f%% IV%dD=%.1f%% slope=%+.3f (%s) target=%dDTE",
                ticker, near_dte, (near_iv or 0) * 100,
                far_dte, (far_iv or 0) * 100, slope, label, target_dte,
            )

    log.info("Term structure: %d/%d candidates analyzed successfully", len(term_data), len(all_candidates))
    return term_data


# ---------------------------------------------------------------------------
# Phase 4: Full Metrics (HV20, z-score, scoring)
# ---------------------------------------------------------------------------

def get_daily_bars(conid):
    """Get 1 year of daily bars for a conid. Returns list of close prices."""
    data = ib_request(f"/iserver/marketdata/history?conid={conid}&period=1y&bar=1d")
    if not data or "data" not in data:
        return []
    return [float(bar["c"]) for bar in data["data"] if bar.get("c") is not None]


def compute_hv20_series(closes):
    """Compute rolling 20-day historical volatility (annualized) from close prices."""
    if len(closes) < 21:
        return []
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    hv20s = []
    for i in range(19, len(returns)):
        window = returns[i - 19:i + 1]
        mean = sum(window) / len(window)
        variance = sum((r - mean) ** 2 for r in window) / (len(window) - 1)
        hv20s.append(math.sqrt(variance) * math.sqrt(252))
    return hv20s


def compute_metrics(current_iv, closes):
    """Compute Z-score, IV/HV ratio, and IV rank from daily closes and current IV."""
    hv20s = compute_hv20_series(closes)
    if len(hv20s) < 120:  # Need ~6 months minimum
        return None

    latest_hv20 = hv20s[-1]
    mean_hv20 = sum(hv20s) / len(hv20s)
    std_hv20 = math.sqrt(sum((h - mean_hv20) ** 2 for h in hv20s) / (len(hv20s) - 1))

    if std_hv20 < 0.0001:
        return None

    z_score = (current_iv - mean_hv20) / std_hv20
    iv_hv_ratio = current_iv / latest_hv20 if latest_hv20 > 0.0001 else 0
    min_hv = min(hv20s)
    max_hv = max(hv20s)
    iv_rank = ((current_iv - min_hv) / (max_hv - min_hv) * 100) if (max_hv - min_hv) > 0.0001 else 50

    return {
        "hv20": round(latest_hv20, 4),
        "z_score": round(z_score, 3),
        "iv_hv_ratio": round(iv_hv_ratio, 3),
        "iv_rank": round(iv_rank, 2),
    }


def score_candidate(metrics, volume, price, direction, term_slope=None):
    """Score a candidate using the IV Scan Scoring Matrix.

    Scoring breakdown (max 12):
      Z-Score Magnitude:       0-3
      IV/HV Ratio:             0-2
      Term Structure:          0-2  (backwardation for sell, contango for buy)
      Options Liquidity:       0-2
      IV Rank Extreme:         0-2
      Price Range:             0-1
    """
    score = 0
    z = abs(metrics["z_score"])
    ratio = metrics["iv_hv_ratio"]
    rank = metrics["iv_rank"]

    # Z-Score Magnitude (0-3)
    if z >= 2.5:
        score += 3
    elif z >= 2.0:
        score += 2
    elif z >= 1.75:
        score += 1

    # IV/HV Ratio Confirmation (0-2)
    if direction == "high":
        if ratio > 2.0:
            score += 2
        elif ratio > 1.5:
            score += 1
    else:
        if ratio < 0.5:
            score += 2
        elif ratio < 0.7:
            score += 1

    # Term Structure Confirmation (0-2)
    if term_slope is not None:
        if direction == "high":
            # Backwardation (near > far) confirms elevated front-end IV
            # = temporary spike that mean-reverts → ideal for selling premium
            if term_slope > 0.15:
                score += 2
            elif term_slope > 0.05:
                score += 1
        else:
            # Contango (near < far) confirms depressed front-end IV
            # = cheap near-term options → ideal for buying premium
            if term_slope < -0.10:
                score += 2
            elif term_slope < -0.02:
                score += 1

    # Options Liquidity (0-2)
    if volume > 5_000_000:
        score += 2
    elif volume > 1_000_000:
        score += 1

    # IV Rank Extreme (0-2)
    if direction == "high":
        if rank > 95:
            score += 2
        elif rank > 90:
            score += 1
    else:
        if rank < 5:
            score += 2
        elif rank < 10:
            score += 1

    # Price Range (0-1)
    if 50 <= price <= 500:
        score += 1

    return score


def process_prefiltered(candidates, direction, term_data):
    """Process pre-filtered candidates: daily bars, metrics, scoring with term structure.
    Returns top 10 by score."""
    results = []

    for i, (ticker, conid, snap) in enumerate(candidates):
        price = snap["price"]
        iv = snap["iv"]
        volume = snap.get("volume", 0)

        if i > 0:
            time.sleep(0.5)  # Rate limit daily bar requests

        closes = get_daily_bars(conid)
        if len(closes) < 121:
            log.info("  %s: skipped (only %d bars, need 121+)", ticker, len(closes))
            continue

        metrics = compute_metrics(iv, closes)
        if metrics is None:
            log.info("  %s: skipped (metrics computation failed)", ticker)
            continue

        z = metrics["z_score"]
        if abs(z) < Z_SCORE_THRESHOLD:
            log.info("  %s: z=%.2f below threshold", ticker, z)
            continue
        if abs(z) > Z_SCORE_MAX:
            log.warning("  %s: z=%.2f OUTLIER (>3.0) — likely event-driven, skipping", ticker, z)
            continue

        # Get term structure data (may be None if chain resolution failed)
        ts = term_data.get(ticker, {})
        term_slope = ts.get("term_slope")

        score = score_candidate(metrics, volume, price, direction, term_slope)
        signal = "SELL PREMIUM" if direction == "high" else "BUY PREMIUM"

        results.append({
            "ticker": ticker,
            "conid": conid,
            "price": price,
            "iv": iv,
            "hv20": metrics["hv20"],
            "iv_hv_ratio": metrics["iv_hv_ratio"],
            "z_score": z,
            "iv_rank": metrics["iv_rank"],
            "score": score,
            "signal": signal,
            "direction": direction,
            "monthly_ranks": {},
            "iv_30d": ts.get("iv_30d"),
            "iv_90d": ts.get("iv_90d"),
            "term_slope": term_slope,
            "target_dte": ts.get("target_dte"),
        })

        ts_info = ""
        if term_slope is not None:
            ts_info = f" term={term_slope:+.3f}"
        log.info(
            "  %s: price=%.2f iv=%.1f%% hv20=%.1f%% z=%.2f rank=%.0f%%%s score=%d -> %s",
            ticker, price, iv * 100, metrics["hv20"] * 100, z,
            metrics["iv_rank"], ts_info, score, signal,
        )

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10]


# ---------------------------------------------------------------------------
# Phase 5: DB Insert
# ---------------------------------------------------------------------------

def ensure_db_schema():
    """Add new columns to iv_scan_results if they don't exist (idempotent migration)."""
    sql = (
        "ALTER TABLE trading.iv_scan_results ADD COLUMN IF NOT EXISTS iv_30d NUMERIC(6,4);\n"
        "ALTER TABLE trading.iv_scan_results ADD COLUMN IF NOT EXISTS iv_90d NUMERIC(6,4);\n"
        "ALTER TABLE trading.iv_scan_results ADD COLUMN IF NOT EXISTS term_slope NUMERIC(6,3);\n"
        "ALTER TABLE trading.iv_scan_results ADD COLUMN IF NOT EXISTS target_dte INTEGER;\n"
    )
    result = subprocess.run(
        [PODMAN, "exec", "-i", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB],
        input=sql,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.warning("Schema migration: %s", result.stderr.strip())
    else:
        log.info("DB schema verified (iv_30d, iv_90d, term_slope, target_dte)")


def insert_results(candidates):
    """Batch insert candidates into PostgreSQL via podman exec."""
    if not candidates:
        log.info("No candidates to insert")
        return

    values = []
    for c in candidates:
        monthly = json.dumps(c.get("monthly_ranks", {})).replace("'", "''")
        iv_30d = f"{c['iv_30d']:.4f}" if c.get("iv_30d") is not None else "NULL"
        iv_90d = f"{c['iv_90d']:.4f}" if c.get("iv_90d") is not None else "NULL"
        term_slope = f"{c['term_slope']:.3f}" if c.get("term_slope") is not None else "NULL"
        target_dte = str(c["target_dte"]) if c.get("target_dte") is not None else "NULL"

        values.append(
            f"('{c['ticker']}', {c['conid']}, {c['price']:.2f}, "
            f"{c['iv']:.4f}, {c['hv20']:.4f}, {c['iv_hv_ratio']:.3f}, "
            f"{c['z_score']:.3f}, {c['iv_rank']:.2f}, "
            f"'{monthly}', {c['score']}, '{c['signal']}', '{c['direction']}', "
            f"{iv_30d}, {iv_90d}, {term_slope}, {target_dte})"
        )

    sql = (
        "INSERT INTO trading.iv_scan_results "
        "(ticker, conid, price, iv, hv20, iv_hv_ratio, z_score, iv_rank, "
        "monthly_ranks, score, signal, scan_direction, "
        "iv_30d, iv_90d, term_slope, target_dte) VALUES\n"
        + ",\n".join(values)
        + ";"
    )

    result = subprocess.run(
        [PODMAN, "exec", "-i", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB],
        input=sql,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error("PostgreSQL insert failed: %s", result.stderr)
    else:
        log.info("Inserted %d candidates into PostgreSQL", len(candidates))


# ---------------------------------------------------------------------------
# Phase 2.5: Snapshot Persistence (all S&P 500 IV data)
# ---------------------------------------------------------------------------

def insert_snapshots(snapshots, conid_map):
    """UPSERT all Phase 2 snapshot data to trading.iv_snapshots in batches."""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = []
    for ticker, snap in snapshots.items():
        price = snap.get("price")
        iv = snap.get("iv")
        volume = snap.get("volume", 0)
        if price is None and iv is None:
            continue
        conid = conid_map.get(ticker, 0)
        price_sql = f"{price:.2f}" if price is not None else "NULL"
        iv_sql = f"{iv:.4f}" if iv is not None else "NULL"
        rows.append(f"('{today}', '{ticker}', {conid}, {price_sql}, {iv_sql}, {volume})")

    if not rows:
        log.info("No snapshot rows to insert")
        return

    BATCH = 100
    inserted = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        sql = (
            "INSERT INTO trading.iv_snapshots (scan_date, ticker, conid, price, iv, volume) VALUES\n"
            + ",\n".join(batch)
            + "\nON CONFLICT (scan_date, ticker) DO UPDATE SET "
            "price = EXCLUDED.price, iv = EXCLUDED.iv, volume = EXCLUDED.volume;"
        )
        result = subprocess.run(
            [PODMAN, "exec", "-i", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB],
            input=sql, capture_output=True, text=True,
        )
        if result.returncode != 0:
            log.error("Snapshot insert batch %d failed: %s", i // BATCH, result.stderr.strip())
        else:
            inserted += len(batch)

    log.info("Inserted/updated %d snapshot rows into trading.iv_snapshots", inserted)


def insert_scan_metadata(stats):
    """Insert a single scan metadata row."""
    sql = (
        "INSERT INTO trading.scan_metadata "
        "(total_tickers, tickers_with_iv, tickers_skipped_no_data, tickers_skipped_low_volume, "
        "high_prefilter_count, low_prefilter_count, high_final_count, low_final_count, duration_seconds) "
        f"VALUES ({stats['total_tickers']}, {stats['tickers_with_iv']}, "
        f"{stats['skipped_no_data']}, {stats['skipped_low_vol']}, "
        f"{stats['high_prefilter']}, {stats['low_prefilter']}, "
        f"{stats['high_final']}, {stats['low_final']}, {stats['duration']:.1f});"
    )
    result = subprocess.run(
        [PODMAN, "exec", "-i", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB],
        input=sql, capture_output=True, text=True,
    )
    if result.returncode != 0:
        log.error("Scan metadata insert failed: %s", result.stderr.strip())
    else:
        log.info("Scan metadata saved to trading.scan_metadata")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    start_time = time.time()
    log.info("=" * 60)
    log.info("S&P 500 IV Z-Score Daily Scan — %s", datetime.now().strftime("%Y-%m-%d %H:%M"))
    log.info("Strategy: 30-90 DTE term structure analysis, 45 DTE sweet spot")
    log.info("=" * 60)

    # Check IBeam session
    if not check_session():
        log.error("IBeam session check failed. Exiting.")
        sys.exit(1)

    # Phase 1: Resolve conids
    log.info("--- Phase 1: Conid Resolution ---")
    conid_map = resolve_all_conids()
    if len(conid_map) < 100:
        log.error("Only %d conids resolved (expected ~500). Aborting.", len(conid_map))
        sys.exit(1)
    log.info("Conid map: %d tickers ready", len(conid_map))

    # Phase 2: Batch IV snapshots
    log.info("--- Phase 2: Batch IV Snapshots ---")
    snapshots = fetch_all_snapshots(conid_map)
    with_iv = sum(1 for s in snapshots.values() if s.get("iv") is not None)
    log.info("Snapshots: %d total, %d with IV data", len(snapshots), with_iv)

    # Phase 2.5: Persist all snapshots to iv_snapshots table
    log.info("--- Phase 2.5: Snapshot Persistence ---")
    insert_snapshots(snapshots, conid_map)

    # Phase 3: Pre-filter
    log.info("--- Phase 3: Pre-filter ---")
    filtered = prefilter_candidates(snapshots, conid_map)

    # Phase 3.5: Term structure analysis (run once for all pre-filtered candidates)
    all_prefiltered = filtered["high"] + filtered["low"]
    # Deduplicate (a ticker won't appear in both, but defensive)
    seen = set()
    unique_prefiltered = []
    for entry in all_prefiltered:
        if entry[0] not in seen:
            seen.add(entry[0])
            unique_prefiltered.append(entry)

    term_data = {}
    if unique_prefiltered:
        log.info("--- Phase 3.5: Term Structure Analysis (%d candidates) ---", len(unique_prefiltered))
        term_data = analyze_term_structure(unique_prefiltered, conid_map)
    else:
        log.info("--- Phase 3.5: Term Structure Analysis (skipped, no candidates) ---")

    # Phase 4: Full metrics + scoring
    all_candidates = []
    high_results = []
    low_results = []

    log.info("--- Phase 4a: High IV candidates (%d) ---", len(filtered["high"]))
    if filtered["high"]:
        high_results = process_prefiltered(filtered["high"], "high", term_data)
        all_candidates.extend(high_results)
        log.info("High IV final: %d candidates", len(high_results))

    log.info("--- Phase 4b: Low IV candidates (%d) ---", len(filtered["low"]))
    if filtered["low"]:
        low_results = process_prefiltered(filtered["low"], "low", term_data)
        all_candidates.extend(low_results)
        log.info("Low IV final: %d candidates", len(low_results))

    # Phase 5: DB insert
    log.info("--- Phase 5: DB Insert ---")
    ensure_db_schema()
    insert_results(all_candidates)

    # Phase 5.5: Scan metadata
    elapsed = time.time() - start_time
    insert_scan_metadata({
        "total_tickers": len(snapshots),
        "tickers_with_iv": with_iv,
        "skipped_no_data": filtered["skipped_no_data"],
        "skipped_low_vol": filtered["skipped_low_vol"],
        "high_prefilter": len(filtered["high"]),
        "low_prefilter": len(filtered["low"]),
        "high_final": len(high_results),
        "low_final": len(low_results),
        "duration": elapsed,
    })

    # Summary
    log.info("=" * 60)
    log.info("SCAN COMPLETE — %d candidates persisted in %.1f minutes", len(all_candidates), elapsed / 60)
    high_count = sum(1 for c in all_candidates if c["direction"] == "high")
    low_count = sum(1 for c in all_candidates if c["direction"] == "low")
    log.info("  High IV (sell premium): %d", high_count)
    log.info("  Low IV (buy premium): %d", low_count)
    ts_count = sum(1 for c in all_candidates if c.get("term_slope") is not None)
    log.info("  With term structure data: %d/%d", ts_count, len(all_candidates))
    if all_candidates:
        log.info("  Top candidates:")
        for c in sorted(all_candidates, key=lambda x: x["score"], reverse=True)[:5]:
            ts_str = f" term={c['term_slope']:+.3f}" if c.get("term_slope") is not None else ""
            dte_str = f" {c['target_dte']}DTE" if c.get("target_dte") else ""
            log.info(
                "    %s: z=%.2f rank=%.0f%%%s%s score=%d/%d %s",
                c["ticker"], c["z_score"], c["iv_rank"], ts_str, dte_str,
                c["score"], 12, c["signal"],
            )
    log.info("=" * 60)


if __name__ == "__main__":
    main()
