"""Unit tests for the threat-map backend's pure logic (no network).

Run:  pip install fastapi httpx maxminddb pytest && pytest -q
(or via the throwaway container the deploy docs describe)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


NOW_MS = 1_751_700_000_000  # fixed reference "now"


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------
def test_classify_taxonomy():
    assert server.classify("/wp-login.php") == "wordpress_probe"
    assert server.classify("/.env.production") == "env_probe"
    assert server.classify("/.git/config") == "git_probe"
    assert server.classify("/phpMyAdmin/index.php") == "db_probe"
    assert server.classify("/api/../../etc/passwd") == "api_probe"  # first rule wins
    assert server.classify("/foo/../../etc/passwd") == "path_traversal"
    assert server.classify("/totally/normal") == "generic_probe"
    assert server.classify("") == "generic_probe"
    assert server.classify(None) == "generic_probe"


# ---------------------------------------------------------------------------
# normalize_honeypot
# ---------------------------------------------------------------------------
def _hp_line(**over):
    base = {
        "honeypot": True, "_ts_ns": NOW_MS * 1_000_000,
        "ip": "203.0.113.7", "country": "Germany", "country_code": "DE",
        "city": "Berlin", "lat": 52.52, "lon": 13.4,
        "path": "/wp-login.php", "method": "POST",
        "attack_type": "wordpress_probe", "user_agent": "curl/8",
    }
    base.update(over)
    return base


def test_honeypot_requires_flag():
    assert server.normalize_honeypot({"path": "/x"}) is None


def test_honeypot_normal():
    e = server.normalize_honeypot(_hp_line())
    assert e["type"] == "honeypot"
    assert e["ts_ms"] == NOW_MS
    assert e["geo_ok"] is True
    assert e["country_code"] == "DE"
    assert e["target_lat"] == server.TARGET_LAT


def test_honeypot_unknown_geo_kept_not_dropped():
    e = server.normalize_honeypot(_hp_line(lat=0.0, lon=0.0))
    assert e is not None            # the old code silently dropped these
    assert e["geo_ok"] is False


def test_honeypot_user_agent_truncated():
    e = server.normalize_honeypot(_hp_line(user_agent="A" * 500))
    assert len(e["user_agent"]) == 120


# ---------------------------------------------------------------------------
# normalize_decision (CrowdSec LAPI)
# ---------------------------------------------------------------------------
GEO = {"country": "France", "country_code": "FR", "city": "Paris",
       "lat": 48.85, "lon": 2.35}


def test_decision_capi_is_not_an_attack():
    dec = {"value": "198.51.100.9", "origin": "CAPI", "scenario": "x"}
    assert server.normalize_decision(dec, GEO, NOW_MS) is None


def test_decision_local_origins_pass():
    for origin in ("crowdsec", "cscli", "CAPI".lower().replace("capi", "appsec")):
        dec = {"value": "198.51.100.9", "origin": origin,
               "scenario": "crowdsecurity/ssh-bf", "duration": "4h", "scope": "Ip"}
        e = server.normalize_decision(dec, GEO, NOW_MS)
        assert e is not None
        assert e["attack_type"] == "banned"
        assert e["ts_ms"] == NOW_MS           # receive-time, never start_ip
        assert e["origin"] == origin


def test_decision_ipv6_kept():
    dec = {"value": "2001:db8::1", "origin": "crowdsec", "scenario": "s", "scope": "Ip"}
    e = server.normalize_decision(dec, GEO, NOW_MS)
    assert e is not None and e["ip"] == "2001:db8::1"


def test_decision_non_ip_scope_skipped():
    dec = {"value": "AS12345", "origin": "crowdsec", "scope": "Range"}
    assert server.normalize_decision(dec, GEO, NOW_MS) is None


# ---------------------------------------------------------------------------
# normalize_traefik
# ---------------------------------------------------------------------------
def _tl(**over):
    base = {
        "_ts_ns": NOW_MS * 1_000_000,
        "RequestPath": "/wp-admin/setup.php", "RequestMethod": "GET",
        "RequestHost": "grafana.aicortex.cloud", "DownstreamStatus": 404,
        "ClientAddr": "10.89.0.5:41000",
        "request_Cf-Connecting-Ip": "203.0.113.50",
        "request_Cf-Ipcountry": "BR",
        "request_User-Agent": "Mozilla/5.0 zgrab",
    }
    base.update(over)
    return base


def test_traefik_prefers_cf_header_ip():
    e = server.normalize_traefik(_tl())
    assert e["ip"] == "203.0.113.50"
    assert e["type"] == "traefik_probe"
    assert e["attack_type"] == "wordpress_probe"
    assert e["host"] == "grafana.aicortex.cloud"


def test_traefik_xff_then_clientaddr_fallback():
    # NB: RFC-5737 doc IPs count as private in py3.13 — use real public IPs here
    e = server.normalize_traefik(_tl(**{"request_Cf-Connecting-Ip": "",
                                        "request_X-Forwarded-For": "8.8.8.8, 10.0.0.1"}))
    assert e["ip"] == "8.8.8.8"
    e2 = server.normalize_traefik(_tl(**{"request_Cf-Connecting-Ip": "",
                                         "ClientAddr": "9.9.9.9:55"}))
    assert e2["ip"] == "9.9.9.9"


def test_traefik_ipv6_clientaddr_port_strip():
    e = server.normalize_traefik(_tl(**{"request_Cf-Connecting-Ip": "",
                                        "ClientAddr": "[2606:4700::1111]:443"}))
    assert e["ip"] == "2606:4700::1111"


def test_traefik_documentation_range_treated_as_internal():
    # Py3.13 is_private covers RFC-5737/3849 doc ranges — they never occur as
    # real clients, so dropping them (absent CF headers) is correct behavior.
    assert server.normalize_traefik(
        _tl(**{"request_Cf-Connecting-Ip": "", "ClientAddr": "198.51.100.4:55"})) is None


def test_traefik_internal_noise_dropped():
    # no CF header + private client → internal (health checks, pod-to-pod)
    assert server.normalize_traefik(
        _tl(**{"request_Cf-Connecting-Ip": "", "ClientAddr": "10.89.0.7:1"})) is None


def test_traefik_benign_paths_dropped():
    assert server.normalize_traefik(_tl(RequestPath="/favicon.ico")) is None
    assert server.normalize_traefik(_tl(RequestPath="/.well-known/security.txt")) is None
    assert server.normalize_traefik(_tl(RequestPath="/favicon.ico?v=2")) is None


def test_traefik_status_mapping():
    assert server.normalize_traefik(_tl(DownstreamStatus=401))["attack_type"] == "auth_failure"
    assert server.normalize_traefik(_tl(DownstreamStatus=403))["attack_type"] == "access_denied"
    assert server.normalize_traefik(_tl(DownstreamStatus=429))["attack_type"] == "rate_limited"


def test_traefik_cf_country_fallback_when_no_geoip():
    # test env has no mmdb → geoip returns ?? → Cf-Ipcountry fills the code
    e = server.normalize_traefik(_tl())
    assert e["country_code"] == "BR"


# ---------------------------------------------------------------------------
# vm_line_to_events
# ---------------------------------------------------------------------------
def test_vm_line_expands_samples():
    line = {"metric": {"ip": "198.51.100.7", "country": "cn", "latitude": "39.9",
                       "longitude": "116.4", "scenario": "crowdsecurity/http-bf",
                       "origin": "crowdsec"},
            "values": [1, 1], "timestamps": [NOW_MS - 1000, NOW_MS]}
    evs = server.vm_line_to_events(line)
    assert len(evs) == 2
    assert evs[0]["country_code"] == "CN"
    assert evs[0]["lat"] == 39.9 and evs[0]["geo_ok"]
    assert evs[1]["ts_ms"] == NOW_MS
    assert evs[0]["attack_type"] == "banned"


def test_vm_line_bad_coords_safe():
    line = {"metric": {"latitude": "oops", "longitude": None},
            "values": [1], "timestamps": [NOW_MS]}
    evs = server.vm_line_to_events(line)
    assert evs[0]["lat"] == 0.0 and evs[0]["geo_ok"] is False


# ---------------------------------------------------------------------------
# clamp_range / downsample
# ---------------------------------------------------------------------------
def test_clamp_range_bounds():
    s, e = server.clamp_range(NOW_MS - 1000, NOW_MS + 999_999, NOW_MS)
    assert e == NOW_MS and s == NOW_MS - 1000
    s, _ = server.clamp_range(0, NOW_MS, NOW_MS)  # ancient start → floored
    assert s == NOW_MS - server.MAX_HISTORY_DAYS * 86_400_000


def test_clamp_range_rejects_bad_input():
    import pytest
    with pytest.raises(ValueError):
        server.clamp_range("x", NOW_MS, NOW_MS)
    with pytest.raises(ValueError):
        server.clamp_range(NOW_MS, NOW_MS, NOW_MS)  # start == end
    with pytest.raises(ValueError):
        server.clamp_range(None, None, NOW_MS)


def test_downsample():
    events = [{"ts_ms": i} for i in range(1000)]
    out, truncated = server.downsample(events, 100)
    assert truncated and len(out) <= 100
    assert out[-1]["ts_ms"] == 999          # last event always survives
    same, t2 = server.downsample(events[:50], 100)
    assert not t2 and len(same) == 50


# ---------------------------------------------------------------------------
# report allowlist
# ---------------------------------------------------------------------------
def test_report_allowlist_shape():
    for name, p in server.REPORT_PANELS.items():
        assert p["uid"] == "crowdsec-threats"
        assert isinstance(p["panel_id"], int)
    assert set(server.REPORT_PANELS) == {"map", "countries", "table"}
