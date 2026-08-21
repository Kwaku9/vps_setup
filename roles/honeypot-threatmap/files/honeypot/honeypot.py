"""
Lightweight fake-responsive honeypot.
Mimics common web targets (WordPress, phpMyAdmin, .env, admin panels).
Logs every hit as structured JSON → stdout (Alloy picks it up → Loki).
Exposes Prometheus metrics on /metrics.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GEOIP_DB_PATH    = os.environ.get("GEOIP_DB", "/geoip/GeoLite2-City.mmdb")
GEOIP_CACHE_SIZE = int(os.environ.get("GEOIP_CACHE_SIZE", "10000"))
LOG_LEVEL        = os.environ.get("LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# Burned-hostname canaries
# ---------------------------------------------------------------------------
# Hostnames that were once real services and leaked to public Certificate
# Transparency logs before the wildcard-only cutover. The services have moved;
# these names now resolve here.
#
# A request to one of these is NOT ambiguous. There is no cached DNS, no stale
# bookmark, and no crawler that would produce it — the name only ever existed in
# CT logs and in our own configuration. Every hit is an actor working from
# certificate-transparency reconnaissance (ATT&CK T1596.003).
#
# That makes these the highest-fidelity detection signal we have: unlike the
# apex honeypot, which catches indiscriminate internet-wide bot noise, a canary
# hit means somebody specifically enumerated *us*.
#
# Populated from roles/honeypot-threatmap/defaults/main.yml.
BURNED_HOSTNAMES = {
    h.strip().lower()
    for h in os.environ.get("BURNED_HOSTNAMES", "").split(",")
    if h.strip()
}

logging.basicConfig(level=LOG_LEVEL, format="%(message)s")
log = logging.getLogger("honeypot")

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
hits_total   = Counter("honeypot_hits_total",   "Total honeypot hits",   ["attack_type", "country_code"])
bots_unique  = Gauge(  "honeypot_unique_ips",   "Unique IPs seen today")

# Separate series for canary hits. Kept distinct from hits_total so that
# alerting can fire on ANY canary hit without being drowned out by the constant
# background rate of apex scanning.
canary_hits = Counter(
    "honeypot_canary_hits_total",
    "Hits on burned hostnames that leaked to CT logs before the wildcard cutover",
    ["hostname", "country_code", "attack_type"],
)
canary_unique_ips = Gauge(
    "honeypot_canary_unique_ips",
    "Unique source IPs that have hit a burned-hostname canary today",
)

# ---------------------------------------------------------------------------
# GeoIP — local MaxMind GeoLite2 (no rate limits, instant lookups)
# ---------------------------------------------------------------------------
_geo_cache: OrderedDict[str, dict] = OrderedDict()
_seen_ips:   set[str] = set()
_canary_ips: set[str] = set()
_seen_day = datetime.now(timezone.utc).date()   # UTC day the sets above belong to
_mmdb = None

def _load_mmdb():
    global _mmdb
    try:
        import maxminddb
        _mmdb = maxminddb.open_database(GEOIP_DB_PATH)
        log.info(f"Loaded MaxMind GeoLite2 from {GEOIP_DB_PATH}")
    except Exception as e:
        log.warning(f"MaxMind DB unavailable ({e}), GeoIP will be unknown")

def _is_private(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False

async def geoip(ip: str) -> dict:
    if ip in _geo_cache:
        return _geo_cache[ip]
    if _is_private(ip):
        return {"country": "Private", "countryCode": "XX", "city": "", "lat": 0.0, "lon": 0.0}
    result = {"country": "Unknown", "countryCode": "??", "city": "", "lat": 0.0, "lon": 0.0}
    if _mmdb:
        try:
            rec = _mmdb.get(ip)
            if rec:
                country = rec.get("country", {})
                city    = rec.get("city", {})
                loc     = rec.get("location", {})
                result = {
                    "country":     country.get("names", {}).get("en", "Unknown"),
                    "countryCode": country.get("iso_code", "??"),
                    "city":        city.get("names", {}).get("en", ""),
                    "lat":         loc.get("latitude", 0.0),
                    "lon":         loc.get("longitude", 0.0),
                }
        except Exception:
            pass
    if len(_geo_cache) >= GEOIP_CACHE_SIZE:
        _geo_cache.popitem(last=False)
    _geo_cache[ip] = result
    return result

# ---------------------------------------------------------------------------
# Attack classification
# ---------------------------------------------------------------------------
_PATH_RULES: list[tuple[str, list[str]]] = [
    ("wordpress_probe",  ["/wp-login", "/wp-admin", "/xmlrpc.php", "/wp-content", "/wp-includes"]),
    ("env_probe",        ["/.env", "/.env.", "/config.php", "/configuration.php", "/settings.php", "/local.php"]),
    ("git_probe",        ["/.git/", "/.svn/", "/.hg/"]),
    ("db_probe",         ["/phpmyadmin", "/pma", "/adminer", "/mysql", "/myadmin"]),
    ("admin_probe",      ["/admin", "/administrator", "/manager", "/dashboard", "/panel", "/console", "/control"]),
    ("api_probe",        ["/api/", "/graphql", "/swagger", "/openapi", "/v1/", "/v2/"]),
    ("shell_probe",      ["/shell", "/cmd", "/exec", "/eval", "/cgi-bin", "/bin/sh"]),
    ("backup_probe",     [".bak", ".backup", ".old", ".sql", ".zip", ".tar"]),
    ("path_traversal",   ["../", "%2e%2e", "%252e"]),
    ("credential_probe", ["/login", "/signin", "/auth", "/account", "/user", "/password"]),
    ("cms_probe",        ["/joomla", "/drupal", "/magento", "/typo3", "/moodle", "/prestashop"]),
]

def classify(path: str) -> str:
    lp = path.lower()
    for attack_type, patterns in _PATH_RULES:
        if any(p in lp for p in patterns):
            return attack_type
    return "generic_probe"

# ---------------------------------------------------------------------------
# Decoy response templates
# ---------------------------------------------------------------------------
_WP_LOGIN = """<!DOCTYPE html><html><head><title>Log In &lsaquo; AICORTEX &#8212; WordPress</title>
<meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/wp-includes/css/buttons.css">
</head><body class="login"><div id="login"><h1><a href="https://aicortex.cloud/">AICORTEX</a></h1>
<form name="loginform" id="loginform" action="/wp-login.php" method="post">
<p><label for="user_login">Username or Email Address<br>
<input type="text" name="log" id="user_login" class="input" value="" size="20" autocapitalize="none" autocomplete="username" /></label></p>
<p><label for="user_pass">Password<br>
<input type="password" name="pwd" id="user_pass" class="input" value="" size="20" autocomplete="current-password" /></label></p>
<p class="forgetmenot"><label for="rememberme"><input name="rememberme" type="checkbox" id="rememberme" value="forever" /> Remember Me</label></p>
<p class="submit"><input type="submit" name="wp-submit" id="wp-submit" class="button button-primary button-large" value="Log In" />
<input type="hidden" name="redirect_to" value="/wp-admin/" /><input type="hidden" name="testcookie" value="1" /></p>
</form><p id="nav"><a href="/wp-login.php?action=lostpassword">Lost your password?</a></p>
</div></body></html>"""

_FAKE_ENV = """APP_NAME=AICORTEX
APP_ENV=production
APP_KEY=base64:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
APP_DEBUG=false
APP_URL=https://aicortex.cloud
DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=aicortex_prod
DB_USERNAME=aicortex_user
DB_PASSWORD=
MAIL_MAILER=smtp
MAIL_HOST=mailhog
MAIL_PORT=1025
"""

_FAKE_GIT_CONFIG = """[core]
\trepositoryformatversion = 0
\tfilemode = true
\tbare = false
\tlogallrefupdates = true
[remote "origin"]
\turl = git@github.com:aicortex/private-repo.git
\tfetch = +refs/heads/*:refs/remotes/origin/*
[branch "main"]
\tremote = origin
\tmerge = refs/heads/main
"""

_XMLRPC = """<?xml version="1.0" encoding="UTF-8"?>
<methodResponse><params><param><value><string>WordPress/6.4.2</string></value></param></params></methodResponse>"""

_WP_LOGIN_FAIL = """<!DOCTYPE html><html><head><title>WordPress &rsaquo; Error</title></head>
<body><div id="login"><h1>Error</h1><p><strong>ERROR</strong>: The password you entered for the username <strong>admin</strong> is incorrect.
<a href="/wp-login.php?action=lostpassword">Lost your password?</a></p></div></body></html>"""

_PHPMYADMIN = """<!DOCTYPE html><html><head><title>phpMyAdmin</title></head>
<body><div class="login_form"><h1>phpMyAdmin</h1>
<form method="post" action="index.php"><input type="text" name="pma_username" placeholder="Username"/>
<input type="password" name="pma_password" placeholder="Password"/>
<input type="submit" value="Go"/></form></div></body></html>"""

_ROOT_PAGE = """<!DOCTYPE html><html><head><title>AICORTEX</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#0a0a0a;color:#e0e0e0}
.c{text-align:center}.logo{font-size:2.5rem;font-weight:900;letter-spacing:.1em;color:#00ff88}
p{color:#888;margin-top:.5rem}</style></head>
<body><div class="c"><div class="logo">AICORTEX</div><p>AI Infrastructure &amp; Security</p></div></body></html>"""

# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------
def _roll_daily_counters() -> None:
    """Reset the 'today' gauges at UTC midnight.

    _seen_ips previously grew without bound for the life of the process while
    being reported as 'Unique IPs seen today'. Two problems: the number was not
    actually a daily figure (it was cumulative since last restart, so it only
    ever went up and silently reset on redeploy), and the set was an unbounded
    memory leak on a 256m container. Both fixed by rolling at UTC midnight.
    """
    global _seen_day, _seen_ips, _canary_ips
    today = datetime.now(timezone.utc).date()
    if today != _seen_day:
        _seen_day = today
        _seen_ips = set()
        _canary_ips = set()
        bots_unique.set(0)
        canary_unique_ips.set(0)


async def log_hit(request: Request, attack_type: str, response_code: int, extra: dict | None = None):
    ip = request.headers.get("cf-connecting-ip") or \
         request.headers.get("x-forwarded-for", "").split(",")[0].strip() or \
         (request.client.host if request.client else "unknown")

    geo = await geoip(ip)

    # Which hostname did they ask for? This is what separates a burned-name
    # canary hit (targeted, high confidence) from apex bot noise (indiscriminate).
    host = (request.headers.get("host") or "").split(":")[0].lower()
    is_canary = host in BURNED_HOSTNAMES

    _roll_daily_counters()

    if ip not in _seen_ips:
        _seen_ips.add(ip)
        bots_unique.set(len(_seen_ips))

    hits_total.labels(attack_type=attack_type, country_code=geo["countryCode"]).inc()

    if is_canary:
        canary_hits.labels(
            hostname=host, country_code=geo["countryCode"], attack_type=attack_type
        ).inc()
        if ip not in _canary_ips:
            _canary_ips.add(ip)
            canary_unique_ips.set(len(_canary_ips))

    event: dict[str, Any] = {
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "honeypot":     True,
        "ip":           ip,
        "country":      geo["country"],
        "country_code": geo["countryCode"],
        "city":         geo["city"],
        "lat":          geo["lat"],
        "lon":          geo["lon"],
        "method":       request.method,
        "host":         host,
        "path":         request.url.path,
        "query":        str(request.url.query) if request.url.query else None,
        "user_agent":   request.headers.get("user-agent", ""),
        "attack_type":  attack_type,
        "response_code": response_code,
        # ── canary fields ────────────────────────────────────────────────────
        # canary=true means the request targeted a hostname that only ever
        # existed in public CT logs. Treat as confirmed reconnaissance.
        "canary":       is_canary,
        "confidence":   "confirmed_recon" if is_canary else "opportunistic",
        # Referer and forwarding chain help fingerprint the tooling in use.
        "referer":      request.headers.get("referer"),
        "xff_chain":    request.headers.get("x-forwarded-for"),
        "cf_asn":       request.headers.get("cf-ipasn"),
    }
    if extra:
        event.update(extra)

    print(json.dumps(event, ensure_ascii=False), flush=True)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
_load_mmdb()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    await log_hit(request, classify(request.url.path), 200)
    return HTMLResponse(_ROOT_PAGE, headers={"Server": "Apache/2.4.54 (Ubuntu)"})

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots(request: Request):
    await log_hit(request, "recon", 200)
    return PlainTextResponse("User-agent: *\nDisallow: /wp-admin/\nDisallow: /wp-includes/\n",
                              headers={"Server": "Apache/2.4.54 (Ubuntu)"})

@app.get("/sitemap.xml")
async def sitemap(request: Request):
    await log_hit(request, "recon", 200)
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://aicortex.cloud/</loc></url></urlset>',
        media_type="application/xml", headers={"Server": "Apache/2.4.54 (Ubuntu)"}
    )

@app.get("/wp-login.php", response_class=HTMLResponse)
async def wp_login_get(request: Request):
    await log_hit(request, "wordpress_probe", 200)
    return HTMLResponse(_WP_LOGIN, headers={"Server": "Apache/2.4.54 (Ubuntu)", "X-Powered-By": "PHP/8.1.27"})

@app.post("/wp-login.php", response_class=HTMLResponse)
async def wp_login_post(request: Request):
    try:
        body = await request.body()
        payload = body.decode("utf-8", errors="replace")[:500]
    except Exception:
        payload = ""
    await log_hit(request, "wordpress_probe", 200, {"payload_snippet": payload})
    return HTMLResponse(_WP_LOGIN_FAIL, headers={"Server": "Apache/2.4.54 (Ubuntu)", "X-Powered-By": "PHP/8.1.27"})

@app.api_route("/xmlrpc.php", methods=["GET", "POST"])
async def xmlrpc(request: Request):
    await log_hit(request, "wordpress_probe", 200)
    return Response(_XMLRPC, media_type="text/xml",
                    headers={"Server": "Apache/2.4.54 (Ubuntu)", "X-Powered-By": "PHP/8.1.27"})

@app.get("/.env")
@app.get("/.env.local")
@app.get("/.env.backup")
@app.get("/.env.production")
async def fake_env(request: Request):
    await log_hit(request, "env_probe", 200)
    return PlainTextResponse(_FAKE_ENV, headers={"Server": "Apache/2.4.54 (Ubuntu)"})

@app.get("/.git/config")
@app.get("/.git/HEAD")
async def fake_git(request: Request):
    await log_hit(request, "git_probe", 200)
    content = _FAKE_GIT_CONFIG if "config" in request.url.path else "ref: refs/heads/main\n"
    return PlainTextResponse(content, headers={"Server": "Apache/2.4.54 (Ubuntu)"})

@app.api_route("/phpmyadmin/{path:path}", methods=["GET", "POST"])
@app.api_route("/pma/{path:path}", methods=["GET", "POST"])
@app.api_route("/mysql/{path:path}", methods=["GET", "POST"])
async def fake_pma(request: Request, path: str = ""):
    await log_hit(request, "db_probe", 200)
    return HTMLResponse(_PHPMYADMIN, headers={"Server": "Apache/2.4.54 (Ubuntu)", "X-Powered-By": "PHP/8.1.27"})

@app.api_route("/wp-admin/{path:path}", methods=["GET", "POST"])
@app.api_route("/wp-content/{path:path}", methods=["GET", "POST"])
@app.api_route("/wp-includes/{path:path}", methods=["GET", "POST"])
async def fake_wp(request: Request, path: str = ""):
    await log_hit(request, "wordpress_probe", 200)
    return HTMLResponse(_WP_LOGIN, status_code=302,
                        headers={"Location": "/wp-login.php",
                                 "Server": "Apache/2.4.54 (Ubuntu)", "X-Powered-By": "PHP/8.1.27"})

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"])
async def catch_all(request: Request, path: str):
    attack_type = classify(request.url.path)
    try:
        body = await request.body()
        payload = body.decode("utf-8", errors="replace")[:300] if body else None
    except Exception:
        payload = None
    await log_hit(request, attack_type, 404, {"payload_snippet": payload} if payload else None)
    return Response(
        b'{"error":"Not Found"}', status_code=404,
        media_type="application/json",
        headers={"Server": "Apache/2.4.54 (Ubuntu)", "X-Powered-By": "PHP/8.1.27"}
    )
