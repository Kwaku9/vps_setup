from ops_dashboard.api.routers.triage import shape_alerts


def test_firing_before_pending_and_critical_first():
    raw = [
        {"name": "MemHigh", "state": "pending", "labels": {"severity": "warning"}, "activeAt": "2026-10-06T10:00:00Z"},
        {"name": "DiskSpaceLow", "state": "firing", "labels": {"severity": "warning", "mountpoint": "/"},
         "annotations": {"summary": "disk"}, "activeAt": "2026-10-06T09:00:00Z"},
        {"name": "PostgresDown", "state": "firing", "labels": {"severity": "critical"}, "activeAt": "2026-10-06T11:00:00Z"},
    ]
    out = shape_alerts(raw)
    assert [a["name"] for a in out] == ["PostgresDown", "DiskSpaceLow", "MemHigh"]
    assert out[1]["summary"] == "disk" and out[1]["target"] == "/"


def test_missing_fields_do_not_crash():
    out = shape_alerts([{"labels": {"alertname": "X"}}])
    assert out[0]["name"] == "X" and out[0]["severity"] == "warning" and out[0]["since"] is None
