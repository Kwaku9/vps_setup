import pytest
from grafana_reports.timeparse import parse_time_phrase

@pytest.mark.parametrize("text,frm,to", [
    ("cyber attack map last 24h", "now-24h", "now"),
    ("attack map last 7 days", "now-7d", "now"),
    ("decisions over the last 6 hours", "now-6h", "now"),
    ("threats last 30d", "now-30d", "now"),
    ("attack map today", "now/d", "now"),
    ("attack map yesterday", "now-1d/d", "now/d"),
    ("attack map", "now-6h", "now"),  # default
])
def test_parse_time_phrase(text, frm, to):
    f, t, _ = parse_time_phrase(text)
    assert (f, t) == (frm, to)

def test_leftover_strips_time_words():
    _, _, leftover = parse_time_phrase("cyber attack map last 24h")
    assert "24h" not in leftover and "last" not in leftover
    assert "cyber attack map" in leftover.strip()
