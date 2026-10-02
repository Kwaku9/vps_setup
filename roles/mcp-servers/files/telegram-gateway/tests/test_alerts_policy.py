"""Routing-policy tests for the vmalert -> Telegram bridge.

Covers should_notify() only — the decision about what is worth interrupting
someone for. The delivery path is a thin wrapper over send_telegram_message and
is exercised by the existing bot tests.
"""

from datetime import datetime, timezone

import pytest

from telegram_gateway.alerts import _format_alert, _in_quiet_window, should_notify


def make_alert(name="SomeAlert", severity="critical", status="firing", **labels):
    return {
        "status": status,
        "labels": {"alertname": name, "severity": severity, **labels},
        "annotations": {"summary": f"{name} summary"},
    }


@pytest.mark.parametrize(
    "severity,expected",
    [("critical", True), ("warning", True), ("info", False), ("debug", False)],
)
def test_severity_floor(severity, expected):
    assert should_notify(make_alert(severity=severity)) is expected


def test_resolved_only_for_critical():
    assert should_notify(make_alert(severity="critical", status="resolved")) is True
    assert should_notify(make_alert(severity="warning", status="resolved")) is False


@pytest.mark.parametrize("alert", [{}, {"labels": {}}, {"labels": None}])
def test_malformed_alerts_are_dropped_not_raised(alert):
    """A malformed payload must never take the endpoint down."""
    assert should_notify(alert) is False


def test_missing_severity_defaults_to_info_and_is_dropped():
    assert should_notify({"status": "firing", "labels": {"alertname": "X"}}) is False


class TestQuietWindow:
    """02:00-02:45 EDT == 06:00-06:45 UTC, the nightly backup pod-restart window."""

    def test_inside_window(self):
        assert _in_quiet_window(datetime(2026, 8, 6, 6, 20, tzinfo=timezone.utc)) is True

    def test_outside_window(self):
        assert _in_quiet_window(datetime(2026, 8, 6, 14, 0, tzinfo=timezone.utc)) is False

    def test_boundaries_are_half_open(self):
        assert _in_quiet_window(datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)) is True
        assert _in_quiet_window(datetime(2026, 8, 6, 6, 45, tzinfo=timezone.utc)) is False

    def test_restart_noise_suppressed_only_in_window(self):
        backup = datetime(2026, 8, 6, 6, 20, tzinfo=timezone.utc)
        midday = datetime(2026, 8, 6, 14, 0, tzinfo=timezone.utc)
        assert _in_quiet_window(backup) and not _in_quiet_window(midday)

    def test_non_restart_alert_still_pages_during_backup(self, monkeypatch):
        """A real outage at 02:20 must not be swallowed just for being nocturnal."""
        monkeypatch.setattr(
            "telegram_gateway.alerts._in_quiet_window", lambda *a, **k: True
        )
        assert should_notify(make_alert("DiskSpaceLow", "warning")) is True
        assert should_notify(make_alert("TargetDown", "critical")) is False


def test_format_escapes_html():
    """Annotations carry container names and log lines; unescaped '<' breaks the send."""
    alert = {
        "status": "firing",
        "labels": {"alertname": "Weird<Name>", "severity": "critical"},
        "annotations": {"summary": "traefik <script>alert(1)</script> down"},
    }
    out = _format_alert(alert)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "Weird&lt;Name&gt;" in out


def test_format_marks_resolved_distinctly():
    firing = _format_alert(make_alert("X", "critical", "firing"))
    resolved = _format_alert(make_alert("X", "critical", "resolved"))
    assert "RESOLVED" in resolved and "RESOLVED" not in firing


# --- repeat suppression, mutes and the burst ceiling --------------------------
# These exercise decide(), which is the function that actually protects the
# channel. should_notify() answers "is this worth an interruption"; decide()
# answers "have we already said it, were we told to stop, and are we flooding".

from telegram_gateway import alerts as _alerts
from telegram_gateway.alerts import (
    ALERT_REPEAT_SUPPRESSION_SECONDS,
    _alert_key,
    _mute_keyboard,
    decide,
    resolve_short_id,
)


@pytest.fixture(autouse=True)
def _clean_alert_state():
    """decide() mutates module state; isolate every test from its neighbours."""
    _alerts._last_sent.clear()
    _alerts._sent_times.clear()
    _alerts._key_registry.clear()
    yield
    _alerts._last_sent.clear()
    _alerts._sent_times.clear()
    _alerts._key_registry.clear()


def test_first_send_passes_then_repeat_is_suppressed():
    a = make_alert()
    assert decide(a, set(), now=1000.0) == "send"
    assert decide(a, set(), now=1000.0 + 60) == "repeat"


def test_repeat_allowed_once_the_window_lapses():
    a = make_alert()
    assert decide(a, set(), now=1000.0) == "send"
    later = 1000.0 + ALERT_REPEAT_SUPPRESSION_SECONDS + 1
    assert decide(a, set(), now=later) == "send"


def test_distinct_series_are_not_suppressed_by_each_other():
    """The Sept-5 shape: one rule, many series. Each is its own key."""
    a = make_alert(instance="honeypot-1")
    b = make_alert(instance="honeypot-2")
    assert decide(a, set(), now=1000.0) == "send"
    assert decide(b, set(), now=1000.0) == "send"


def test_mute_by_series_blocks_only_that_series():
    a = make_alert(instance="honeypot-1")
    b = make_alert(instance="honeypot-2")
    mutes = {("series", _alert_key(a))}
    assert decide(a, mutes, now=1000.0) == "muted"
    assert decide(b, mutes, now=1000.0) == "send"


def test_mute_by_alertname_blocks_every_series_of_that_rule():
    a = make_alert(name="HoneypotSilent", instance="honeypot-1")
    b = make_alert(name="HoneypotSilent", instance="honeypot-2")
    c = make_alert(name="SomethingElse")
    mutes = {("alertname", "HoneypotSilent")}
    assert decide(a, mutes, now=1000.0) == "muted"
    assert decide(b, mutes, now=1000.0) == "muted"
    assert decide(c, mutes, now=1000.0) == "send"


def test_resolve_clears_the_firing_key_so_a_re_break_alerts_immediately():
    """Broke -> resolved -> broke again 10 min later must NOT be suppressed."""
    firing = make_alert(status="firing")
    resolved = make_alert(status="resolved")
    assert decide(firing, set(), now=1000.0) == "send"
    assert decide(resolved, set(), now=1000.0 + 300) == "send"
    # Well inside the repeat window, but the resolve reset it.
    assert decide(firing, set(), now=1000.0 + 600) == "send"


def test_burst_ceiling_stops_a_storm_and_reports_it_as_burst():
    """126 distinct series would otherwise all deliver in one batch."""
    verdicts = [
        decide(make_alert(instance=f"h-{i}"), set(), now=1000.0)
        for i in range(_alerts.ALERT_BURST_MAX + 5)
    ]
    assert verdicts.count("send") == _alerts.ALERT_BURST_MAX
    assert verdicts.count("burst") == 5


def test_burst_budget_refills_after_the_window():
    for i in range(_alerts.ALERT_BURST_MAX):
        assert decide(make_alert(instance=f"h-{i}"), set(), now=1000.0) == "send"
    assert decide(make_alert(instance="overflow"), set(), now=1000.0) == "burst"
    later = 1000.0 + _alerts.ALERT_BURST_WINDOW_SECONDS + 1
    assert decide(make_alert(instance="overflow"), set(), now=later) == "send"


def test_short_id_round_trips_and_fits_callback_data():
    a = make_alert(instance="honeypot-1")
    kb = _mute_keyboard(a)
    for row in kb["inline_keyboard"]:
        for btn in row:
            # Telegram hard-caps callback_data at 64 bytes.
            assert len(btn["callback_data"].encode()) <= 64
    sid = kb["inline_keyboard"][0][0]["callback_data"].split("|")[2]
    assert resolve_short_id(sid) == _alert_key(a)


def test_critical_mute_choices_are_capped_at_eight_hours():
    """A 24h mute on a critical is how something stays broken overnight."""
    kb = _mute_keyboard(make_alert(severity="critical"))
    secs = [int(b["callback_data"].split("|")[3]) for b in kb["inline_keyboard"][0]]
    assert max(secs) <= _alerts._MUTE_MAX_CRITICAL_SECONDS
    kb_warn = _mute_keyboard(make_alert(severity="warning"))
    secs_warn = [int(b["callback_data"].split("|")[3]) for b in kb_warn["inline_keyboard"][0]]
    assert 86400 in secs_warn
