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
