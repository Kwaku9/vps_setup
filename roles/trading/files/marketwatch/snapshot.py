#!/usr/bin/env python3
"""Live SPY state snapshot: structure, flow, and trigger evaluation.

Read-only. Pulls intraday bars from the authenticated IBKR Client Portal gateway
and evaluates them against levels derived from stored history.

NEVER places, modifies, or cancels an order.

Usage:
  python3 snapshot.py                 # human-readable
  python3 snapshot.py --json          # machine-readable
  python3 snapshot.py --triggers-only # emit only fired triggers (for monitors)
"""
from __future__ import annotations
import argparse, json, os, ssl, statistics, subprocess, sys, datetime as dt
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

# IBKR history endpoint reports volume in 40-share units; stored weekly-paginated
# fetches report actual shares. Verified 2026-08-06: ratio exactly 40.0 across bars.
VOLUME_UNIT_FACTOR = 40.0
SYMBOLS = {"SPY": "756733", "QQQ": "320227571"}   # verified via iserver/secdef/search 2026-08-06
CONID = SYMBOLS["SPY"]
SSH_HOST = "root@alpine-vps"
GW = "https://localhost:5000/v1/api"
ET = ZoneInfo("America/New_York")
BAR_MINUTES = 5
FULL_SESSION_BARS = 78
PACE_LOOKBACK_SESSIONS = 10
OPENING_VOLUME_LOOKBACK_SESSIONS = 20
REFERENCE_CACHE_PATH = Path(os.getenv(
    "MARKETWATCH_REFERENCE_CACHE_PATH",
    "/var/lib/marketwatch/opening-volume-reference.json",
))


def gateway(path: str) -> dict:
    """Call IBeam directly on the VPS, or through SSH from the workstation.

    ``MARKETWATCH_GATEWAY_URL`` is deliberately opt-in.  The deployed watcher
    uses the loopback-only host port; the analyst workstation retains the SSH
    transport and therefore does not expose the gateway on another interface.
    """
    direct = os.getenv("MARKETWATCH_GATEWAY_URL", "").rstrip("/")
    if direct:
        req = Request(f"{direct}/{path}", headers={"Accept": "application/json"})
        context = ssl._create_unverified_context() if direct.startswith("https://") else None
        try:
            with urlopen(req, timeout=25, context=context) as response:
                return json.loads(response.read())
        except Exception as exc:
            raise RuntimeError(f"direct gateway call failed: {exc}") from exc

    # Workstation path: the Client Portal gateway remains bound to VPS
    # loopback, so reach it inside IBeam over the authenticated tailnet.
    cmd = ["tailscale", "ssh", SSH_HOST,
           f'podman exec ibeam curl -sk --max-time 20 "{GW}/{path}"']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(f"gateway call failed: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def check_auth() -> dict:
    st = gateway("iserver/auth/status")
    if not (st.get("authenticated") and st.get("connected")):
        raise RuntimeError(f"gateway not authenticated: {st}")
    return st


def bars(conid: str, bar: str = "5min", period: str = "1d",
         start_time: str | None = None) -> list[dict]:
    path = (f"iserver/marketdata/history?conid={conid}&period={period}"
            f"&bar={bar}&outsideRth=false&source=Trades")
    if start_time:
        path += f"&startTime={start_time}"
    d = gateway(path)
    # The response declares its unit conversion. It has historically been 40,
    # but reading it from the response prevents a gateway upgrade from silently
    # changing every volume threshold. The constant is only a compatibility
    # fallback for older responses that omitted volumeFactor.
    volume_factor = float(d.get("volumeFactor", VOLUME_UNIT_FACTOR))
    if not 0 < volume_factor < 10_000:
        raise RuntimeError(f"implausible volumeFactor={volume_factor!r}")
    out = []
    for x in d["data"]:
        # IBKR timestamps are epoch milliseconds. Always convert explicitly to
        # New York time; the workstation is currently Atlantic time and differs
        # from ET after the daylight-saving transition.
        t = dt.datetime.fromtimestamp(x["t"] / 1000, ET)
        out.append(dict(time=t.strftime("%H:%M"), date=t.strftime("%Y-%m-%d"),
                        o=x["o"], h=x["h"], l=x["l"], c=x["c"],
                        v=x["v"] * volume_factor, epoch_ms=x["t"]))
    return out


def daily_history(conid: str) -> list[dict]:
    """One year of daily RTH bars -> MAs, record high, average volume."""
    return bars(conid, bar="1d", period="1y")


def profile_bars(conid: str) -> list[dict]:
    """Three months of 30-min RTH bars -> volume profile."""
    return bars(conid, bar="30min", period="3m")


def closed_five_minute_bars(raw: list[dict], now: dt.datetime | None = None) -> list[dict]:
    """Return only bars whose full five-minute interval has elapsed.

    IBKR labels a bar with its *start* time. A 10:15 bar is not usable until
    10:20. The old code consumed ``intra[-1]`` without proving that interval had
    closed, which violated the agent's most important timing rule.
    """
    now = now or dt.datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)
    out = []
    for b in raw:
        start = dt.datetime.fromtimestamp(b["epoch_ms"] / 1000, ET)
        if start + dt.timedelta(minutes=BAR_MINUTES) <= now:
            out.append(b)
    return out


def group_sessions(raw: list[dict]) -> dict[str, list[dict]]:
    sessions: dict[str, list[dict]] = {}
    for b in raw:
        sessions.setdefault(b["date"], []).append(b)
    for day in sessions.values():
        day.sort(key=lambda x: x["epoch_ms"])
    return sessions


def prior_completed_week_high(daily: list[dict], today: str) -> float | None:
    """High of the latest ISO week completed before ``today``."""
    current = dt.date.fromisoformat(today).isocalendar()[:2]
    weeks: dict[tuple[int, int], list[dict]] = {}
    for row in daily:
        key = dt.date.fromisoformat(row["date"]).isocalendar()[:2]
        if key < current:
            weeks.setdefault(key, []).append(row)
    if not weeks:
        return None
    return max(row["h"] for row in weeks[max(weeks)])


def known_resistance_levels(daily: list[dict], prior_week_high: float) -> list[float]:
    """Lookahead-safe resistance known before the current session opened."""
    levels = [prior_week_high, daily[-1]["h"]]
    for lookback in (20, 60):
        levels.append(max(row["h"] for row in daily[-lookback:]))
    start = max(2, len(daily) - 60)
    # Two later completed days are required to confirm a pivot high.
    for j in range(start, len(daily) - 2):
        window = daily[j - 2:j + 3]
        if daily[j]["h"] == max(row["h"] for row in window):
            levels.append(daily[j]["h"])
    return sorted(set(round(float(level), 4) for level in levels))


def opening_volume_reference(conid: str, recent: list[dict], today: str,
                             lookback: int = OPENING_VOLUME_LOOKBACK_SESSIONS) -> dict:
    """Persist a rolling IBKR-only 09:35 volume reference.

    Client Portal caps a history response at 1,000 five-minute bars, or about
    12 sessions. Weekly backward pages are fetched only when the private cache
    lacks 20 complete sessions; normal five-minute checks merely refresh it
    from the already-requested recent window.
    """
    cached: dict[str, float] = {}
    if REFERENCE_CACHE_PATH.exists():
        payload = json.loads(REFERENCE_CACHE_PATH.read_text())
        cached = {str(k): float(v) for k, v in payload.get("slot_0935_volume", {}).items()}

    def absorb(raw: list[dict]) -> None:
        for day, session in group_sessions(raw).items():
            if day < today and len(session) == FULL_SESSION_BARS:
                cached[day] = float(session[1]["v"])

    absorb(recent)
    current_date = dt.date.fromisoformat(today)
    monday = current_date - dt.timedelta(days=current_date.weekday())
    eligible = lambda: sorted(day for day in cached if day < today)
    for weeks_back in range(8):
        if len(eligible()) >= lookback:
            break
        boundary = monday - dt.timedelta(weeks=weeks_back)
        start_time = (
            dt.datetime.combine(boundary, dt.time(9, 30), tzinfo=ET)
            .astimezone(dt.timezone.utc)
            .strftime("%Y%m%d-%H:%M:%S")
        )
        absorb(bars(conid, bar="5min", period="1w", start_time=start_time))

    dates = eligible()
    if len(dates) < lookback:
        raise RuntimeError(f"need {lookback} complete same-slot sessions for opening breakout volume")
    # Retain enough history for diagnostics while bounding the private file.
    retained = dates[-60:]
    payload = {
        "schema": 1,
        "source": "IBKR RTH Trades",
        "slot": "09:35 ET five-minute bar",
        "slot_0935_volume": {day: cached[day] for day in retained},
    }
    REFERENCE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REFERENCE_CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, REFERENCE_CACHE_PATH)
    REFERENCE_CACHE_PATH.chmod(0o600)
    values = [cached[day] for day in dates[-lookback:]]
    return {
        "median": statistics.median(values),
        "sessions": lookback,
        "start": dates[-lookback],
        "end": dates[-1],
    }


def time_normalized_projection(
    current: list[dict],
    history: list[dict],
    lookback: int = PACE_LOOKBACK_SESSIONS,
) -> dict:
    """Project full-session volume from the historical intraday volume curve.

    Linear ``so_far * 390 / elapsed`` extrapolation is invalid because US ETF
    volume is U-shaped. Instead, estimate what fraction of a normal session has
    traded by this same completed-bar index, using recent *IBKR* five-minute
    sessions, then divide the current cumulative volume by that fraction.

    All terms use the same IBKR RTH Trades feed. Consolidated Yahoo/Nasdaq
    volume is intentionally not mixed into an intraday trigger.
    """
    if not current:
        raise RuntimeError("no completed five-minute bars")
    n = len(current)
    today = current[0]["date"]
    grouped = group_sessions(history)
    refs = []
    for day in sorted(grouped):
        bs = grouped[day]
        if day >= today or len(bs) != FULL_SESSION_BARS or n > len(bs):
            continue
        total = sum(x["v"] for x in bs)
        cumulative = sum(x["v"] for x in bs[:n])
        if total > 0 and cumulative > 0:
            refs.append((day, cumulative / total, cumulative, total))
    refs = refs[-lookback:]
    if len(refs) < 5:
        raise RuntimeError(
            f"only {len(refs)} complete reference sessions for bar index {n}; need at least 5"
        )
    fraction = statistics.median(x[1] for x in refs)
    same_time_median = statistics.median(x[2] for x in refs)
    so_far = sum(x["v"] for x in current)
    return dict(
        projected=so_far / fraction,
        expected_fraction=fraction,
        same_time_ratio_pct=so_far / same_time_median * 100,
        reference_sessions=len(refs),
        reference_start=refs[0][0],
        reference_end=refs[-1][0],
        method="historical-same-time-curve",
    )


def load_history() -> list[dict]:
    """Stored 5-min RTH sessions -> daily bars. SPY only (deep base-rate work)."""
    base = Path("/home/general/Projects/VScdeProjects")
    srcs = [
        base / "trade-opening-range-followthrough/runs/2016-08-01_2021-07-30-spy/spy-5m-history.json",
        base / "trade-opening-range-followthrough/runs/2021-08-01_2026-07-31-spy/spy-5m-history.json",
        base / "trade-opening-range-followthrough/runs/2026-08-06-current-regime/spy-5m.json",
    ]
    m = {}
    for p in srcs:
        if not p.exists():
            continue
        for s in json.loads(p.read_text())["sessions"]:
            m[s["date"]] = s
    days = []
    for k in sorted(m):
        b = m[k]["bars"]
        days.append(dict(date=k, o=b[0]["open"], h=max(x["high"] for x in b),
                         l=min(x["low"] for x in b), c=b[-1]["close"],
                         v=sum(x["volume"] for x in b), n=len(b), bars=b))
    return days


def clv(b: dict) -> float:
    rng = b["h"] - b["l"]
    return 0.0 if rng <= 0 else ((b["c"] - b["l"]) - (b["h"] - b["c"])) / rng


def volume_profile(flat: list[dict], bins: int = 60):
    """Volume-at-price from a flat list of bars keyed l/h/v."""
    lo = min(b["l"] for b in flat); hi = max(b["h"] for b in flat)
    if hi <= lo:
        return dict(poc=lo, shelves=[], pockets=[], lo=lo, hi=hi)
    vol = [0.0] * bins
    for b in flat:
        a = max(0, min(bins - 1, int((b["l"] - lo) / (hi - lo) * bins)))
        z = max(0, min(bins - 1, int((b["h"] - lo) / (hi - lo) * bins)))
        for k in range(a, z + 1):
            vol[k] += b["v"] / (z - a + 1)
    mid = [lo + (hi - lo) * (k + 0.5) / bins for k in range(bins)]
    order = sorted(vol)
    hi_thr, lo_thr = order[int(0.80 * bins)], order[int(0.25 * bins)]

    def zones(pred):
        out, run = [], []
        for k in range(bins):
            if pred(vol[k]):
                run.append(k)
            elif run:
                out.append((mid[run[0]], mid[run[-1]])); run = []
        if run:
            out.append((mid[run[0]], mid[run[-1]]))
        return out
    return dict(poc=mid[vol.index(max(vol))],
                shelves=zones(lambda v: v >= hi_thr),
                pockets=[z for z in zones(lambda v: v <= lo_thr) if z[1] - z[0] > 0.5],
                lo=lo, hi=hi)


def analyze(symbol: str = "SPY", include_bars: bool = False) -> dict:
    symbol = symbol.upper()
    if symbol not in SYMBOLS:
        raise ValueError(f"unknown symbol {symbol}; known: {list(SYMBOLS)}")
    conid = SYMBOLS[symbol]
    check_auth()

    raw_intra = bars(conid)                   # current/most recent RTH session, 5-min
    intra = closed_five_minute_bars(raw_intra)
    if not intra:
        raise RuntimeError(f"no completed five-minute bars for {symbol}")
    today = intra[0]["date"]
    daily = [d for d in daily_history(conid) if d["date"] < today]
    if len(daily) < 50:
        raise RuntimeError(f"insufficient daily history for {symbol}: {len(daily)} bars")

    closes = [d["c"] for d in daily]
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50
    avg_vol = sum(d["v"] for d in daily[-20:]) / 20
    record = max(d["h"] for d in daily)   # 1-YEAR high (daily history window), not verified all-time
    prev_close = closes[-1]

    px = intra[-1]["c"]
    sess_v = sum(b["v"] for b in intra)
    sess_h = max(b["h"] for b in intra); sess_l = min(b["l"] for b in intra)
    delta = sum(clv(b) * b["v"] for b in intra)

    elapsed = min(390, len(intra) * BAR_MINUTES)
    recent_5m = bars(conid, bar="5min", period="1m")
    projection = time_normalized_projection(intra, recent_5m)
    projected_v = projection["projected"]

    prior_week_high = prior_completed_week_high(daily, today)
    if prior_week_high is None:
        raise RuntimeError("no completed prior week in daily history")
    opening_reference = opening_volume_reference(conid, recent_5m, today)
    opening_breakout_relative_volume = (
        intra[1]["v"] / opening_reference["median"]
        if len(intra) >= 2 else None
    )
    resistance = known_resistance_levels(daily, prior_week_high)

    vp = volume_profile([b for b in profile_bars(conid) if b["date"] < today])
    below = [z for z in vp["pockets"] if z[1] < px]
    pocket = max(below, key=lambda z: z[1]) if below else None
    above = [z for z in vp["pockets"] if z[0] > px]
    pocket_up = min(above, key=lambda z: z[0]) if above else None

    state = dict(
        symbol=symbol,
        source="IBKR RTH Trades",
        asof=(dt.datetime.fromtimestamp(intra[-1]["epoch_ms"] / 1000, ET)
              + dt.timedelta(minutes=BAR_MINUTES)).strftime("%Y-%m-%d %H:%M ET"),
        price=px,
        prev_close=prev_close, change_pct=(px / prev_close - 1) * 100,
        session=dict(open=intra[0]["o"], high=sess_h, low=sess_l,
                     close_loc=(px - sess_l) / (sess_h - sess_l) * 100 if sess_h > sess_l else 50.0,
                     gap_pct=(intra[0]["o"] / prev_close - 1) * 100),
        volume=dict(so_far=sess_v, projected=projected_v, avg20=avg_vol,
                    pace_pct=projected_v / avg_vol * 100 if avg_vol else 0.0,
                    same_time_ratio_pct=projection["same_time_ratio_pct"],
                    expected_fraction=projection["expected_fraction"],
                    reference_sessions=projection["reference_sessions"],
                    reference_start=projection["reference_start"],
                    reference_end=projection["reference_end"],
                    method=projection["method"], source="IBKR RTH Trades"),
        delta_pct=delta / sess_v * 100 if sess_v else 0.0,
        levels=dict(record_high=record, sma20=sma20, sma50=sma50, poc=vp["poc"],
                    prior_high=daily[-1]["h"], prior_low=daily[-1]["l"],
                    prior_week_high=prior_week_high,
                    known_resistance=resistance,
                    shelves=vp["shelves"], pockets=vp["pockets"],
                    pocket_below=pocket, pocket_above=pocket_up),
        opening=dict(
            breakout_relative_volume=opening_breakout_relative_volume,
            reference_sessions=opening_reference["sessions"],
            reference_start=opening_reference["start"],
            reference_end=opening_reference["end"],
            method="same-five-minute-slot-median",
        ),
        last_bar=dict(start=intra[-1]["time"], epoch_ms=intra[-1]["epoch_ms"],
                      o=intra[-1]["o"], h=intra[-1]["h"],
                      l=intra[-1]["l"], c=intra[-1]["c"], v=intra[-1]["v"],
                      prior_close=intra[-2]["c"] if len(intra) > 1 else intra[-1]["o"]),
        elapsed_min=elapsed,
        bars_complete=len(intra),
        complete=len(intra) == FULL_SESSION_BARS,
    )

    t = []
    pace = state["volume"]["pace_pct"]; d_pct = state["delta_pct"]
    loc = state["session"]["close_loc"]
    expanding = pace >= 120; contracting = pace < 100
    if px >= record:
        t.append(("BULL", "NEW 1-YEAR HIGH", f"{px:.2f} >= {record:.2f} (1y window)"))
    if pocket and px < pocket[1]:
        t.append(("BEAR-CONFIRM" if expanding else "BEAR-WATCH", "BROKE INTO LOW-VOLUME POCKET",
                  f"{px:.2f} < {pocket[1]:.2f}; pace {pace:.0f}% "
                  f"({'EXPANDING - real selling' if expanding else 'not expanding - likely noise'})"))
    if pocket and px < pocket[0]:
        t.append(("BEAR-CONFIRM", "LOST THE POCKET", f"{px:.2f} < {pocket[0]:.2f}; air-gap crossed"))
    # SMA20 is trend CONTEXT, not a trigger. On 2026-07-30 it fired "BEAR" on the
    # same session as a volume-confirmed BULL-CONFIRM -- price was still under the
    # 20-day while buyers were demonstrably stepping in, and the rally ran +4.3%
    # from the next open. A trend-position fact must not carry the same severity
    # as a volume-confirmed entry, or it contradicts the signal that has evidence
    # behind it. Article 4: volume expansion decides; everything else is context.
    if px < sma20:
        t.append(("CONTEXT", "below SMA20", f"{px:.2f} < {sma20:.2f} (trend position, not a signal)"))
    if expanding and d_pct > 10 and loc > 70:
        t.append(("BULL-CONFIRM", "BUYERS IN SIZE (big money)",
                  f"pace {pace:.0f}%, delta {d_pct:+.0f}%, close-loc {loc:.0f}%"))
    if expanding and d_pct < -15 and loc < 30:
        t.append(("BEAR-CONFIRM", "SELLERS IN SIZE (big money)",
                  f"pace {pace:.0f}%, delta {d_pct:+.0f}%, close-loc {loc:.0f}%"))
    if contracting and d_pct < 0 and px < prev_close:
        t.append(("NEUTRAL", "PULLBACK ON CONTRACTING VOLUME",
                  f"pace {pace:.0f}% (<100%) - big money absent; move is noise"))
    state["triggers"] = [dict(side=a, name=b, detail=c) for a, b, c in t]
    if include_bars:
        state["bars"] = intra
    return state


def render(s: dict) -> str:
    L = s["levels"]; V = s["volume"]
    tag = "EXPANDING" if V["pace_pct"] >= 120 else "CONTRACTING" if V["pace_pct"] < 100 else "normal"
    out = []
    if s.get("source") == "fallback-daily":
        out.append("  *** FALLBACK TAPE (daily bars) - the live gateway was unavailable ***")
    out += [f"{s['symbol']} {s['price']:.2f}  ({s['change_pct']:+.2f}%)  {s['asof']}"
           f"{'' if s['complete'] else '  [SESSION INCOMPLETE]'}",
           f"  session O {s['session']['open']:.2f}  H {s['session']['high']:.2f}  "
           f"L {s['session']['low']:.2f}  gap {s['session']['gap_pct']:+.2f}%  "
           f"close-loc {s['session']['close_loc']:.0f}%",
           f"  volume {V['so_far']/1e6:.1f}M so far, projecting {V['projected']/1e6:.1f}M "
           f"= {V['pace_pct']:.0f}% of 20d avg ({V['avg20']/1e6:.1f}M)  [{tag}]",
           f"  delta proxy {s['delta_pct']:+.0f}%" if s["delta_pct"] is not None
           else "  delta proxy UNAVAILABLE (needs intraday bars)",
           "",
           f"  1y-high {L['record_high']:.2f}   SMA20 {L['sma20']:.2f}   "
           f"SMA50 {L['sma50']:.2f}   POC {L['poc']:.2f}"]
    if L["pocket_below"]:
        out.append(f"  pocket below: {L['pocket_below'][1]:.2f} -> {L['pocket_below'][0]:.2f}  (fast down)")
    if L["pocket_above"]:
        out.append(f"  pocket above: {L['pocket_above'][0]:.2f} -> {L['pocket_above'][1]:.2f}  (fast up)")
    out.append("")
    if s["triggers"]:
        out.append("  TRIGGERS:")
        for t in s["triggers"]:
            out.append(f"    [{t['side']}] {t['name']} - {t['detail']}")
    else:
        out.append("  TRIGGERS: none fired")
    if s.get("notes"):
        out.append("")
        out.append("  NOTES:")
        out += [f"    - {n}" for n in s["notes"]]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY,QQQ", help="comma-separated; default SPY,QQQ")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--triggers-only", action="store_true")
    ap.add_argument("--allow-fallback", action="store_true",
                    help="on gateway failure, fall back to the daily-bar tape "
                         "(Yahoo cross-checked against Nasdaq). OPT-IN ON PURPOSE: "
                         "a silent fallback would mask a dead gateway. The fallback "
                         "cannot compute the delta proxy and skips flow triggers.")
    a = ap.parse_args()
    syms = [x.strip().upper() for x in a.symbol.split(",") if x.strip()]
    states, rc = [], 0
    for sym in syms:
        try:
            states.append(analyze(sym))
        except Exception as e:
            if not a.allow_fallback:
                print(f"SNAPSHOT-ERROR [{sym}]: {e}", flush=True); rc = 2
                continue
            # Degraded, never silent: the live failure is still reported, and the
            # substitute state is labelled source="fallback-daily" in its own right.
            print(f"SNAPSHOT-DEGRADED [{sym}]: live gateway failed ({e}); "
                  f"using daily-bar fallback", file=sys.stderr, flush=True)
            try:
                import fallback_feed
                states.append(fallback_feed.analyze(sym))
                rc = max(rc, 1)          # 1 = degraded, 2 = failed. Never 0.
            except Exception as fe:
                print(f"SNAPSHOT-ERROR [{sym}]: fallback also failed: {fe}",
                      flush=True); rc = 2
    if a.json:
        print(json.dumps(states, indent=2))
    elif a.triggers_only:
        for s in states:
            for t in s["triggers"]:
                if t["side"] != "NEUTRAL":
                    print(f"[{t['side']}] {s['symbol']} {t['name']} @ {s['price']:.2f} - {t['detail']}", flush=True)
    else:
        print("\n\n".join(render(s) for s in states))
    return rc


if __name__ == "__main__":
    sys.exit(main())
