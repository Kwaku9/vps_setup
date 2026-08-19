import json

DS = {"type": "postgres", "uid": "postgres-trading"}
CAP = 25.0  # DAILY_USD_CAP in the LookStack worker. Keep these two in step.

def sql(q, fmt="table"):
    return [{"datasource": DS, "format": fmt, "rawQuery": True, "rawSql": q, "refId": "A"}]

def stat(title, q, x, y, w=6, h=4, unit="none", decimals=2, steps=None, desc=""):
    return {
        "type": "stat", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": sql(q),
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "textMode": "auto", "colorMode": "value", "graphMode": "none"},
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": decimals,
            "thresholds": {"mode": "absolute",
                           "steps": steps or [{"color": "text", "value": None}]}}, "overrides": []},
    }

def ts(title, q, x, y, w=12, h=8, unit="none", desc="", extra=None):
    d = {"custom": {"lineWidth": 2, "fillOpacity": 12, "showPoints": "auto"}, "unit": unit}
    d.update(extra or {})
    return {
        "type": "timeseries", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": sql(q, "time_series"),
        "fieldConfig": {"defaults": d, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }

def table(title, q, x, y, w=12, h=8, desc=""):
    return {
        "type": "table", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": sql(q),
        "fieldConfig": {"defaults": {"custom": {"align": "auto"}}, "overrides": []},
        "options": {"showHeader": True},
    }

panels = []

panels.append({
    "type": "text", "title": "How to read this", "datasource": None,
    "gridPos": {"x": 0, "y": 0, "w": 24, "h": 4},
    "options": {"mode": "markdown", "content": (
        "**This is a receipt, not a brake.** Spend is limited by a fail-closed daily counter "
        "in the render worker (`DAILY_USD_CAP`, currently **$%.0f**) and by reserved concurrency "
        "of 3, which caps the *rate*. Neither depends on this dashboard.\n\n"
        "**The data is T+1.** Postgres sits on alpine-vps behind Tailscale with no public inbound, "
        "so the Lambda cannot push — the box pulls from DynamoDB nightly at 04:20 and re-reads the "
        "last 3 days to catch rows written after midnight or by an SQS retry.\n\n"
        "**Judge staleness from _Sync freshness_, never from an empty chart.** A day with no renders "
        "is a real answer."
    ) % CAP},
})

Y = 4
panels += [
    stat("Spend today", f"SELECT COALESCE(sum(total_usd),0) FROM larouge_look_usage WHERE day = current_date",
         0, Y, unit="currencyUSD", desc=f"Against the ${CAP:.0f}/day fail-closed cap.",
         steps=[{"color": "green", "value": None},
                {"color": "yellow", "value": CAP * 0.6},
                {"color": "red", "value": CAP * 0.85}]),
    stat("Looks delivered today",
         "SELECT count(DISTINCT job_id) FROM larouge_look_usage WHERE day = current_date",
         6, Y, unit="none", decimals=0, desc="Distinct customers, not render attempts."),
    stat("Attempts per look",
         "SELECT CASE WHEN count(DISTINCT job_id)=0 THEN 0 "
         "ELSE count(*)::numeric/count(DISTINCT job_id) END "
         "FROM larouge_look_usage WHERE day >= current_date - 6",
         12, Y, desc="7-day. Measured 1.68 across the 42-render eval; drift upward means the "
                     "verifier is rejecting more, which costs money before it costs quality.",
         steps=[{"color": "green", "value": None}, {"color": "yellow", "value": 2.0},
                {"color": "red", "value": 2.5}]),
    stat("Cost per finished look",
         "SELECT CASE WHEN count(DISTINCT job_id)=0 THEN 0 "
         "ELSE sum(total_usd)/count(DISTINCT job_id) END "
         "FROM larouge_look_usage WHERE day >= current_date - 6",
         18, Y, unit="currencyUSD", decimals=3,
         desc="7-day. Includes retries, so it exceeds the single-render price.",
         steps=[{"color": "green", "value": None}, {"color": "yellow", "value": 0.10},
                {"color": "red", "value": 0.15}]),
]

Y += 4
panels += [
    ts("Daily spend", "SELECT day::timestamptz AS time, sum(total_usd) AS \"spend\" "
       "FROM larouge_look_usage GROUP BY day ORDER BY day",
       0, Y, unit="currencyUSD",
       desc=f"Red line is the ${CAP:.0f} daily cap the worker enforces.",
       extra={"thresholds": {"mode": "absolute", "steps": [
           {"color": "green", "value": None}, {"color": "red", "value": CAP}]},
           "custom": {"lineWidth": 2, "fillOpacity": 12, "showPoints": "auto",
                      "thresholdsStyle": {"mode": "line"}}}),
    ts("Renders per day, by attempt number",
       "SELECT day::timestamptz AS time, 'attempt ' || attempt AS metric, count(*) AS value "
       "FROM larouge_look_usage GROUP BY day, attempt ORDER BY day",
       12, Y, desc="Attempt 2 and 3 are the verifier rejecting and re-rolling. A growing tail is "
                   "the earliest signal that render quality is slipping."),
]

Y += 8
panels += [
    ts("Render latency", "SELECT day::timestamptz AS time, "
       "percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) AS \"p50\", "
       "percentile_cont(0.95) WITHIN GROUP (ORDER BY ms) AS \"p95\" "
       "FROM larouge_look_usage GROUP BY day ORDER BY day",
       0, Y, unit="ms", desc="Per render call, not per customer — a customer waits for all attempts."),
    table("Model and size mix (7 days)",
          "SELECT model, size, count(*) AS renders, round(sum(total_usd),4) AS usd, "
          "round(avg(ms)) AS avg_ms FROM larouge_look_usage "
          "WHERE day >= current_date - 6 GROUP BY model, size ORDER BY renders DESC",
          12, Y, desc="Should be gemini-3.1-flash-lite-image @1K only. Anything else means the "
                      "worker's pinned model changed — that pin exists because a provider once "
                      "answered a nano_banana_pro request with a different model."),
]

Y += 8
panels += [
    stat("Sync freshness",
         "SELECT EXTRACT(EPOCH FROM (now() - max(finished_at)))/3600 "
         "FROM larouge_look_sync_runs WHERE ok",
         0, Y, w=6, h=6, unit="h", decimals=1,
         desc="Hours since the last SUCCESSFUL pull. This is the honest staleness signal: an empty "
              "usage chart can mean a quiet day, but this going red always means the job is broken.",
         steps=[{"color": "green", "value": None}, {"color": "yellow", "value": 26},
                {"color": "red", "value": 30}]),
    table("Recent sync runs",
          "SELECT finished_at AS \"finished\", ok, rows_upserted AS \"rows\", "
          "days_scanned AS \"days\", detail FROM larouge_look_sync_runs "
          "ORDER BY started_at DESC LIMIT 12",
          6, Y, w=18, h=6,
          desc="Failures are recorded here with their reason, so a dead job never looks like a quiet day."),
]

dash = {
    "uid": "larouge-look",
    "title": "L.A. Rouge — Try the Look",
    "tags": ["larouge", "cost", "ai"],
    "timezone": "browser",
    "editable": True,
    "refresh": "5m",
    "time": {"from": "now-30d", "to": "now"},
    "templating": {"list": []},
    "panels": panels,
    "schemaVersion": 39,
    "version": 1,
}
print(json.dumps(dash, indent=2))
