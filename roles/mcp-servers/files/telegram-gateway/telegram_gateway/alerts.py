"""Alertmanager-compatible receiver so vmalert can notify over Telegram.

vmalert speaks only the Alertmanager wire protocol: it POSTs a JSON *array* of
alert objects to `<notifier.url>/api/v2/alerts`. Rather than run an Alertmanager
container just to translate that into a chat message — this host is already at
100% swap — the gateway exposes the same endpoint natively.

Wiring (roles/monitoring/tasks/main.yml):
    -notifier.url=http://telegram-gateway:7555
    -notifier.bearerToken=<telegram_gateway_auth_token>

vmalert appends /api/v2/alerts itself, so the URL must NOT include that path.
The bearer token is checked by the existing auth middleware in main.py — this
route is deliberately NOT in its exemption list.
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from telegram_gateway import db
from telegram_gateway.bot import send_telegram_message
from telegram_gateway.config import TELEGRAM_ALLOWED_USER_IDS

logger = logging.getLogger(__name__)

router = APIRouter()

# Emoji per severity, purely cosmetic — the routing decision lives in
# should_notify() below.
_SEVERITY_ICON = {
    "critical": "🔴",
    "warning": "🟠",
    "info": "🔵",
}


def _format_alert(alert: dict[str, Any]) -> str:
    """Render one Alertmanager alert object as a Telegram HTML message.

    Everything interpolated is escaped: alert annotations can contain values
    scraped from container names, HTTP paths and log lines, and an unescaped
    '<' would make Telegram reject the whole message as malformed HTML.
    """
    labels = alert.get("labels", {}) or {}
    annotations = alert.get("annotations", {}) or {}

    name = labels.get("alertname", "UnknownAlert")
    severity = (labels.get("severity") or "info").lower()
    status = (alert.get("status") or "firing").lower()

    icon = "✅" if status == "resolved" else _SEVERITY_ICON.get(severity, "⚪")
    verb = "RESOLVED" if status == "resolved" else severity.upper()

    lines = [f"{icon} <b>{html.escape(verb)}</b> — {html.escape(name)}"]

    if summary := annotations.get("summary"):
        lines.append(html.escape(str(summary)))
    if description := annotations.get("description"):
        lines.append(f"<i>{html.escape(str(description))}</i>")

    context = {k: v for k, v in labels.items() if k not in ("alertname", "severity")}
    if context:
        rendered = ", ".join(
            f"{html.escape(str(k))}={html.escape(str(v))}" for k, v in sorted(context.items())
        )
        lines.append(f"<code>{rendered}</code>")

    return "\n".join(lines)


# --- Routing policy -------------------------------------------------------
# Deliberately conservative: a channel that buzzes all night gets muted, and a
# muted channel is indistinguishable from the -notifier.blackhole this replaced.
# Every knob below is meant to be tuned once real traffic is observed.

# `info` never reaches Telegram; it stays queryable in Grafana.
_NOTIFY_SEVERITIES = {"critical", "warning"}

# Recovery notices roughly double volume. Worth it for the things that actually
# interrupted you, not for warnings that resolve on their own.
_RESOLVED_SEVERITIES = {"critical"}

# The 02:00 America/New_York backup stops ~10 pods for 5-8 minutes, so every
# scrape target legitimately flaps and the rules' `for: 2m` is not long enough to
# ride it out. Suppress only the restart-shaped alerts, and only in that window —
# a real outage at 02:15 still pages via any other alertname.
#
# Expressed in UTC because python:*-slim ships no tzdata, so ZoneInfo would raise.
# 06:00-06:45Z == 02:00-02:45 EDT. This drifts an hour under EST; override with
# ALERT_QUIET_UTC="HH:MM-HH:MM" rather than editing code.
_QUIET_UTC = os.getenv("ALERT_QUIET_UTC", "06:00-06:45")
_RESTART_NOISE = {"TargetDown", "OpenWebUIUnhealthy", "PrometheusTargetMissing"}


def _in_quiet_window(now: datetime | None = None) -> bool:
    """True if `now` (UTC) falls inside the nightly backup window."""
    try:
        start_s, end_s = _QUIET_UTC.split("-")
        start_h, start_m = (int(x) for x in start_s.split(":"))
        end_h, end_m = (int(x) for x in end_s.split(":"))
    except (ValueError, AttributeError):
        logger.warning("ALERT_QUIET_UTC=%r is malformed; not suppressing", _QUIET_UTC)
        return False

    now = now or datetime.now(timezone.utc)
    minutes = now.hour * 60 + now.minute
    start, end = start_h * 60 + start_m, end_h * 60 + end_m
    # Handle a window that wraps past midnight (e.g. "23:50-00:30").
    return start <= minutes < end if start <= end else (minutes >= start or minutes < end)


def should_notify(alert: dict[str, Any]) -> bool:
    """Decide whether a single alert is worth a Telegram message.

    `alert` is one Alertmanager object:
        {"status": "firing"|"resolved",
         "labels": {"alertname": ..., "severity": "critical"|"warning"|"info",
                    "job": ..., "instance": ...},
         "annotations": {"summary": ..., "description": ...},
         "startsAt": ..., "endsAt": ...}
    """
    labels = alert.get("labels", {}) or {}
    severity = (labels.get("severity") or "info").lower()
    status = (alert.get("status") or "firing").lower()

    if status == "resolved":
        return severity in _RESOLVED_SEVERITIES
    if severity not in _NOTIFY_SEVERITIES:
        return False
    if labels.get("alertname") in _RESTART_NOISE and _in_quiet_window():
        return False
    return True


# --- repeat suppression -------------------------------------------------------
# should_notify() answers "is this alert worth interrupting someone for?".
# It does NOT answer "we already said this — say it again?", and vmalert re-posts
# every firing alert on every notification cycle. So one stuck alert becomes a
# message per cycle, forever. On 2026-09-05, 126 stuck HoneypotSilent instances
# did exactly that: ~7 Telegram requests/sec for three days, an 18h rate-limit
# ban, and ~14% of the host CPU spent delivering nothing.
#
# The rule that produced those 126 instances is fixed, but the gateway should not
# depend on every upstream alert rule being well-behaved.
_last_sent: dict[str, float] = {}

# How long to stay quiet about an alert already reported. Tune to taste.
ALERT_REPEAT_SUPPRESSION_SECONDS = 3600


def _alert_key(alert: dict) -> str:
    """Stable identity for one alert instance: status + its full label set."""
    labels = alert.get("labels", {}) or {}
    parts = [f"{k}={v}" for k, v in sorted(labels.items())]
    return f"{(alert.get('status') or 'firing').lower()}|" + ",".join(parts)


# A stuck rule does not repeat one key — it fans out across many. The 2026-09-05
# storm was 126 DISTINCT HoneypotSilent series, so per-key suppression alone
# would still have delivered 126 messages in one burst and tripped the same rate
# limit. The ceiling below is what actually defends against a malformed rule.
ALERT_BURST_MAX = 20
ALERT_BURST_WINDOW_SECONDS = 600
_sent_times: deque[float] = deque()

# _last_sent is keyed on the full label set, so its cardinality is bounded only
# by how creative the alert rules get. Evict lapsed entries once it grows past
# this; the host runs at 100% swap and an unbounded dict is a slow leak.
_LAST_SENT_MAX = 2000


def _evict_last_sent(now: float) -> None:
    """Drop entries older than the suppression window once the dict is large."""
    if len(_last_sent) <= _LAST_SENT_MAX:
        return
    cutoff = now - ALERT_REPEAT_SUPPRESSION_SECONDS
    for key in [k for k, ts in _last_sent.items() if ts < cutoff]:
        _last_sent.pop(key, None)


def burst_budget_remaining(now: float | None = None) -> int:
    """How many more sends the global ceiling allows in the current window."""
    now = now or time.time()
    cutoff = now - ALERT_BURST_WINDOW_SECONDS
    while _sent_times and _sent_times[0] < cutoff:
        _sent_times.popleft()
    return max(0, ALERT_BURST_MAX - len(_sent_times))


def is_muted(alert: dict, mutes: set[tuple[str, str]]) -> bool:
    """True if a Telegram mute covers this alert, by series or by alertname."""
    if not mutes:
        return False
    labels = alert.get("labels", {}) or {}
    alertname = labels.get("alertname", "")
    return ("series", _alert_key(alert)) in mutes or ("alertname", alertname) in mutes


def decide(
    alert: dict,
    mutes: set[tuple[str, str]] | None = None,
    now: float | None = None,
) -> str:
    """Why this alert will or won't be sent: 'send'|'muted'|'repeat'|'burst'.

    Returning 'send' RECORDS the send (burst window + last-sent), so call this
    exactly once per alert per delivery attempt.

    Three gates, cheapest first:
      1. muted from Telegram  — explicit human "stop telling me about this"
      2. repeat suppression   — same key inside ALERT_REPEAT_SUPPRESSION_SECONDS
      3. global burst ceiling — ALERT_BURST_MAX sends per ALERT_BURST_WINDOW

    `mutes` is passed in rather than queried here so one DB round-trip covers a
    whole batch; this also keeps the function sync and trivially testable.
    """
    now = now or time.time()

    if is_muted(alert, mutes or set()):
        return "muted"

    # A resolve means the next firing is genuinely new information, so clear the
    # firing key rather than making a recovered-then-broken service wait out the
    # window. Without this, "it broke again 10 minutes later" stays silent.
    # Done before the repeat check so a resolve is never itself suppressed by a
    # stale firing entry.
    if (alert.get("status") or "firing").lower() == "resolved":
        _last_sent.pop(_alert_key({**alert, "status": "firing"}), None)

    key = _alert_key(alert)
    last = _last_sent.get(key)
    if last is not None and (now - last) < ALERT_REPEAT_SUPPRESSION_SECONDS:
        return "repeat"

    if burst_budget_remaining(now) <= 0:
        return "burst"

    _sent_times.append(now)
    _last_sent[key] = now
    _evict_last_sent(now)
    return "send"


def should_send_now(
    alert: dict,
    mutes: set[tuple[str, str]] | None = None,
    now: float | None = None,
) -> bool:
    """Boolean form of decide(). Kept because it is the documented contract."""
    return decide(alert, mutes, now) == "send"


# --- mute buttons -------------------------------------------------------------
# Telegram caps callback_data at 64 BYTES, and _alert_key() is the full label
# set — far too long to embed. Send a short hash and keep a lookup here.
# The alertname rides along in the payload as a fallback so an "all of this
# rule" press still works after a restart has emptied the registry.
_KEY_REGISTRY_MAX = 2000
_key_registry: dict[str, str] = {}

# Offered durations. `critical` deliberately stops at 8h: a 24h mute on a
# critical is how something stays broken overnight without anyone noticing.
_MUTE_CHOICES = [("1h", 3600), ("8h", 28800), ("24h", 86400)]
_MUTE_MAX_CRITICAL_SECONDS = 28800


def _short_id(key: str) -> str:
    """8 hex chars of the alert key — short enough for callback_data."""
    sid = hashlib.sha256(key.encode()).hexdigest()[:8]
    if len(_key_registry) > _KEY_REGISTRY_MAX:
        _key_registry.clear()
    _key_registry[sid] = key
    return sid


def resolve_short_id(sid: str) -> str | None:
    """Full alert key for a short id, or None if the registry has lost it."""
    return _key_registry.get(sid)


def _mute_keyboard(alert: dict[str, Any]) -> dict[str, Any]:
    """Inline keyboard: mute this series, or every series of this rule."""
    labels = alert.get("labels", {}) or {}
    alertname = str(labels.get("alertname", "UnknownAlert"))[:30]
    severity = (labels.get("severity") or "info").lower()
    sid = _short_id(_alert_key(alert))

    cap = _MUTE_MAX_CRITICAL_SECONDS if severity == "critical" else None
    series_row = [
        {"text": f"🔕 {label}", "callback_data": f"am|s|{sid}|{secs}|{alertname}"}
        for label, secs in _MUTE_CHOICES
        if cap is None or secs <= cap
    ]
    # Muting by alertname is the "all 126 honeypot series" button. Kept to a
    # single conservative duration so it cannot be fat-fingered into a day.
    rule_row = [{
        "text": f"🔕 All {alertname} 8h",
        "callback_data": f"am|n|{sid}|28800|{alertname}",
    }]
    return {"inline_keyboard": [series_row, rule_row]}


@router.post("/api/v2/alerts", include_in_schema=False)
async def receive_alerts(request: Request) -> dict[str, Any]:
    """Alertmanager v2 receiver. Always 200s so vmalert never retry-storms us."""
    try:
        payload = await request.json()
    except Exception:
        logger.warning("alert webhook: unparseable body")
        return {"status": "error", "reason": "invalid json", "sent": 0}

    # vmalert posts a bare array; tolerate {"alerts": [...]} too.
    alerts = payload if isinstance(payload, list) else (payload or {}).get("alerts", [])
    if not isinstance(alerts, list):
        return {"status": "error", "reason": "expected array", "sent": 0}

    # One query per batch, not per alert: a fanned-out rule can put hundreds of
    # alerts in a single POST. A DB failure here must not silence anything, so
    # an empty mute set (send everything) is the fallback.
    try:
        mutes = await db.active_alert_mutes()
    except Exception:
        logger.exception("could not load alert mutes; treating nothing as muted")
        mutes = set()

    sent = 0
    suppressed_burst = 0
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        try:
            if not should_notify(alert):
                continue
        except Exception:
            logger.exception("should_notify() raised; dropping alert")
            continue

        try:
            verdict = decide(alert, mutes)
            if verdict != "send":
                # Only the ceiling gets summarised: a muted or repeated alert is
                # suppression working as intended, not a gap worth reporting.
                if verdict == "burst":
                    suppressed_burst += 1
                continue
        except Exception:
            # Fail OPEN: a policy bug must never silence a real alert.
            logger.exception("decide() raised; sending anyway")

        text = _format_alert(alert)
        markup = _mute_keyboard(alert)
        for chat_id in TELEGRAM_ALLOWED_USER_IDS:
            try:
                await send_telegram_message(chat_id, text, reply_markup=markup)
                sent += 1
            except Exception:
                # One bad recipient must not stop the rest.
                logger.exception("failed sending alert to chat_id=%s", chat_id)

    # The ceiling exists to stop a storm, but going silent mid-storm is its own
    # failure. Say once that it happened, so the gap is visible rather than
    # indistinguishable from "nothing is wrong".
    if suppressed_burst:
        note = (
            f"⚠️ <b>{suppressed_burst} further alerts suppressed</b>\n"
            f"Burst ceiling hit ({ALERT_BURST_MAX} per "
            f"{ALERT_BURST_WINDOW_SECONDS // 60}m). Check Grafana for the full set."
        )
        for chat_id in TELEGRAM_ALLOWED_USER_IDS:
            try:
                await send_telegram_message(chat_id, note)
            except Exception:
                logger.exception("failed sending burst summary to chat_id=%s", chat_id)

    return {
        "status": "ok",
        "received": len(alerts),
        "sent": sent,
        "suppressed_burst": suppressed_burst,
    }
