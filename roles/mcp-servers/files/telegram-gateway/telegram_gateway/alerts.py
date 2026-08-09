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

import html
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

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

    sent = 0
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        try:
            if not should_notify(alert):
                continue
        except NotImplementedError:
            # Fail loud in logs, but never 500 back at vmalert.
            logger.error("alert dropped: should_notify() is not implemented yet")
            continue
        except Exception:
            logger.exception("should_notify() raised; dropping alert")
            continue

        text = _format_alert(alert)
        for chat_id in TELEGRAM_ALLOWED_USER_IDS:
            try:
                await send_telegram_message(chat_id, text)
                sent += 1
            except Exception:
                # One bad recipient must not stop the rest.
                logger.exception("failed sending alert to chat_id=%s", chat_id)

    return {"status": "ok", "received": len(alerts), "sent": sent}
