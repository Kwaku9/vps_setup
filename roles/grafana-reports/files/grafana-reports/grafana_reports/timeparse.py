from __future__ import annotations
import re

_UNIT = {"h": "h", "hour": "h", "hours": "h", "d": "d", "day": "d", "days": "d",
         "w": "w", "week": "w", "weeks": "w", "m": "M", "month": "M", "months": "M"}

# "last 24h", "last 7 days", "past 6 hours", "24h", "7d"
_REL = re.compile(r"\b(?:last|past|over the last)?\s*(\d+)\s*(h|hours?|d|days?|w|weeks?|m|months?)\b", re.I)
_NAMED = {
    "today": ("now/d", "now"),
    "yesterday": ("now-1d/d", "now/d"),
    "this week": ("now/w", "now"),
}

def parse_time_phrase(text: str) -> tuple[str, str, str]:
    lowered = text.lower()
    for phrase, (frm, to) in _NAMED.items():
        if phrase in lowered:
            leftover = re.sub(re.escape(phrase), " ", text, flags=re.I)
            return frm, to, _clean(leftover)
    m = _REL.search(text)
    if m:
        n, unit = m.group(1), _UNIT[m.group(2).lower()]
        leftover = (text[: m.start()] + " " + text[m.end():])
        # also drop a leading bare "last"/"past" if left dangling
        leftover = re.sub(r"\b(last|past|over the)\b", " ", leftover, flags=re.I)
        return f"now-{n}{unit}", "now", _clean(leftover)
    return "now-6h", "now", _clean(text)

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
