"""Host rehearsal view: totals per person, re-records per section, the host listed first."""
import asyncio

from ops_dashboard.api.routers import host_rehearsal as hr

T1, T2 = "2026-11-15T10:00:00Z", "2026-11-15T10:30:00Z"


def rows():
    return {
        # name, visits, days, minutes, takes, playbacks, listens, briefings, slides, edits, first, last
        "totals": [["Pops", 1, 1, 3, 1, 0, 1, 0, 4, 0, T1, T1],
                   ["Nalah", 2, 2, 12, 4, 3, 5, 1, 15, 1, T1, T2]],
        # name, section/where, minutes, opens, seconds open, takes, avg take s, playbacks, listens, last
        "sections": [["Nalah", "welcome", 5, 2, 240.0, 3, 41.5, 2, 2, T2],
                     ["Nalah", "company", 2, 1, 90.0, 1, 38.0, 1, 1, T2],
                     ["Nalah", "briefing", 4, 0, None, 0, None, 0, 0, T1],
                     ["Nalah", "room", 1, 0, None, 0, None, 0, 0, T1],
                     ["Nalah", None, 0, 0, None, 0, None, 0, 0, T1],
                     ["Pops", "chat", 3, 1, 60.0, 0, None, 0, 1, T1]],
        "daily": [["Nalah", "2026-11-14", 4, 1], ["Nalah", "2026-11-15", 8, 3], ["Ghost", "2026-11-15", 1, 0]],
        "visits": [["Nalah", T2, "Mobile", "iOS", "Mobile Safari", "San Juan"]],
        "denied": [[2]],
    }


def test_host_first_then_test_logins():
    out = hr.assemble(30, rows())
    assert [h["name"] for h in out["hosts"]] == ["Nalah", "Pops"]
    assert out["gate_denied"] == 2 and out["tracking_from"] == 3


def test_rerecords_are_takes_minus_one_per_section():
    nalah = hr.assemble(30, rows())["hosts"][0]
    by = {s["id"]: s for s in nalah["sections"]}
    assert by["welcome"]["takes"] == 3 and by["welcome"]["rerecords"] == 2
    assert by["company"]["takes"] == 1 and by["company"]["rerecords"] == 0
    assert by["presenter"]["takes"] == 0 and by["presenter"]["rerecords"] == 0
    assert nalah["rerecords"] == 2  # summed per section, not takes - 1 overall (that would say 3)


def test_every_section_listed_in_script_order_with_targets():
    nalah = hr.assemble(30, rows())["hosts"][0]
    assert [s["id"] for s in nalah["sections"]] == [s[0] for s in hr.SECTIONS]
    welcome = nalah["sections"][1]
    assert welcome["practice"] is True and welcome["target_seconds"] == 180
    assert welcome["avg_take_seconds"] == 41.5 and welcome["seconds_open"] == 240
    assert nalah["sections"][3]["avg_take_seconds"] is None  # no takes: no average


def test_places_daily_and_visits_belong_to_known_people():
    nalah = hr.assemble(30, rows())["hosts"][0]
    assert {p["id"]: p["minutes"] for p in nalah["places"]} == {"briefing": 4, "room": 1}
    assert [d["day"] for d in nalah["daily"]] == ["2026-11-14", "2026-11-15"]
    assert nalah["visits_recent"][0]["city"] == "San Juan"
    assert all(h["name"] != "Ghost" for h in hr.assemble(30, rows())["hosts"])


def test_not_configured_without_a_key(monkeypatch):
    monkeypatch.delenv("BUILDFOLIO_POSTHOG_PERSONAL_API_KEY", raising=False)
    out = asyncio.run(hr.host_rehearsal(days=30, _={"role": "admin"}))
    assert out["configured"] is False and out["hosts"] == []


def test_only_the_tracking_period_is_queried():
    for sql in hr._queries(7).values():
        assert "tracking_version) >= 3" in sql and "INTERVAL 7 DAY" in sql


def test_presenter_room_events_are_left_out():
    for name, sql in hr._queries(7).items():
        if name != "denied":
            assert "coalesce(properties.rehearsal_mode, 'host') = 'host'" in sql
