from datetime import datetime, timezone

from ops_dashboard.api.routers.inventory import endpoint_severity, job_status, knowledge_status, unmanaged_severity


def test_job_failed_by_exit_code_or_flag():
    assert job_status(1, False, remote=False) == "fail"
    assert job_status(None, True, remote=True) == "fail"


def test_vps_jobs_are_covered_by_cronjobfailed():
    assert job_status(0, False, remote=False) == "ok"
    assert job_status(None, False, remote=False) == "ok"  # not run since cron-shell


def test_remote_jobs_are_unwatched():
    assert job_status(0, False, remote=True) == "unwatched"


def test_endpoint_severity():
    assert endpoint_severity([]) is None
    assert endpoint_severity(["public: relies on the app's own sign-in"]) == "info"
    assert endpoint_severity(["public: relies on the app's own sign-in",
                              "no Traefik middlewares at all (no CrowdSec, rate limit or security headers)"]) == "warn"
    assert endpoint_severity(["PUBLIC INTERNET via Tailscale Funnel"]) == "bad"
    assert endpoint_severity(["DNS points straight at this host (reveals origin, skips Cloudflare)"]) == "bad"
    assert endpoint_severity(["reachable from the LAN"]) == "warn"


def test_lan_plumbing_is_info_but_a_lan_dev_server_warns():
    assert endpoint_severity(["reachable from the LAN"], "udp", 5353, None) == "info"
    assert endpoint_severity(["reachable from the LAN"], "udp", 34961, "firefox") == "info"
    assert endpoint_severity(["reachable from the LAN"], "tcp", 8000, "python3") == "warn"


def test_authentik_issued_client_secrets_are_not_hand_managed():
    assert unmanaged_severity("grafana:GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET") == "info"
    assert unmanaged_severity("ops-dashboard:OIDC_CLIENT_SECRET") == "info"
    assert unmanaged_severity("mailkit-mcp-read:MCP_SHARED_SECRET") == "warn"


def test_knowledge_stale_after_60_days_of_no_writes():
    now = datetime(2026, 10, 17, tzinfo=timezone.utc)
    assert knowledge_status("ok", "2026-10-16T21:53:27Z", now) == "ok"
    assert knowledge_status("ok", "2026-08-10T20:12:09Z", now) == "stale"
    assert knowledge_status("ok", "2026-08-18T00:00:00Z", now) == "ok"  # 60 days is not yet stale


def test_knowledge_without_a_write_clock_is_not_stale():
    assert knowledge_status("ok", None) == "ok"


def test_knowledge_broken_and_stopped_win_over_age():
    assert knowledge_status("broken", "2026-10-16T00:00:00Z") == "broken"
    assert knowledge_status("stopped", None) == "stopped"
