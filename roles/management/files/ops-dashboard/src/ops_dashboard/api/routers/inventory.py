"""Inventory: everything the infra-graph collector knows, for the Inventory tab.

Read-only views over the Neo4j knowledge graph (rebuilt nightly by
roles/neo4j/files/infra-graph) joined with live numbers from VictoriaMetrics:
cron jobs' last exit code and duration (cron-shell), and container memory/CPU.
Every route needs a signed-in user (AuthMiddleware); none changes anything.

Each view is a plain async function (`jobs()`, `databases()`, ...) so it can be
exercised without HTTP; the routes are thin wrappers.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Query

from .timeline_search import _neo

router = APIRouter(prefix="/api/inventory", tags=["inventory"])

VM_URL = os.environ.get("VM_URL", "http://metrics-pod:8428")
ROLE_RE = re.compile(r"/roles/([^/]+)/")


def _iso(v):
    if v is None:
        return None
    if hasattr(v, "to_native"):
        v = v.to_native()
    return v.isoformat() if hasattr(v, "isoformat") else v


def _clean(d):
    """Neo4j temporal values -> ISO strings, recursively."""
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_clean(v) for v in d]
    return _iso(d) if hasattr(d, "to_native") else d


async def _q(cypher: str, **params) -> list[dict]:
    async with _neo.session() as s:
        res = await s.run(cypher, **params)
        return _clean(await res.data())


async def _vm(promql: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{VM_URL}/api/v1/query", params={"query": promql})
            r.raise_for_status()
            return r.json().get("data", {}).get("result", [])
    except (httpx.HTTPError, ValueError):
        return []  # live numbers are a bonus; the graph data still answers


async def _vm_by(promql: str, label: str) -> dict[str, float]:
    return {r["metric"].get(label): float(r["value"][1]) for r in await _vm(promql) if r["metric"].get(label)}


# ── views ───────────────────────────────────────────────────────────────────

async def summary() -> dict:
    rows = await _q("""
        CALL { MATCH (n:ScheduledJob) RETURN count(n) AS jobs }
        CALL { MATCH (n:Datastore) RETURN count(n) AS datastores }
        CALL { MATCH (n:Database) RETURN count(n) AS databases }
        CALL { MATCH (n:Table) RETURN count(n) AS tables }
        CALL { MATCH (n:McpServer) RETURN count(n) AS mcp }
        CALL { MATCH (n:Credential) RETURN count(n) AS credentials }
        CALL { MATCH (n:PublicEndpoint) RETURN count(n) AS endpoints }
        CALL { MATCH (n:Pipeline) RETURN count(n) AS pipelines }
        CALL { MATCH (n:AlertRule) RETURN count(n) AS alert_rules }
        CALL { MATCH (n:Script) RETURN count(n) AS scripts }
        CALL { MATCH (n:External) RETURN count(n) AS apis }
        CALL { MATCH (n:Host) RETURN count(n) AS hosts }
        OPTIONAL MATCH (m:CollectorRun {name: 'infra-graph'})
        RETURN *, m.last_run AS graph_refreshed, m.sources_failed AS sources_failed""")
    out = rows[0] if rows else {}
    out.pop("m", None)
    return out


async def jobs() -> list[dict]:
    rows = await _q("""
        MATCH (j:ScheduledJob)
        OPTIONAL MATCH (j)-[:RUNS_IN]->(w)
        OPTIONAL MATCH (j)-[:RUNS]->(s:Script)
        OPTIONAL MATCH (r:AlertRule)-[:WATCHES]->(j)
        OPTIONAL MATCH (s)-[:USES]->(c:Credential)
        OPTIONAL MATCH (s)-[:CALLS_EXTERNAL]->(x:External)
        RETURN j {.name, .schedule, .frequency, .command, .ansible_managed, .host, .kind, .log,
                  .last_result, .exit_status, .failing, .purpose, .missing, .conditional, .role} AS job,
               collect(DISTINCT w.name) AS where, collect(DISTINCT s {.path, .source}) AS scripts,
               collect(DISTINCT r.name) AS alert_rules, collect(DISTINCT c.name) AS credentials,
               collect(DISTINCT x.name) AS apis
        ORDER BY job.name""")
    exit_code = await _vm_by("cron_job_last_exit_code", "cron_job")
    duration = await _vm_by("cron_job_last_duration_seconds", "cron_job")
    last_run = await _vm_by("cron_job_last_run_timestamp_seconds", "cron_job")
    last_ok = await _vm_by("cron_job_last_success_timestamp_seconds", "cron_job")
    cpu = await _vm_by("cron_job_last_cpu_seconds", "cron_job")
    rss = await _vm_by("cron_job_last_max_rss_bytes", "cron_job")
    out = []
    for r in rows:
        j = r["job"]
        name = j["name"]
        role = j.get("role") or next((m[1] for s in r["scripts"]
                                      if s.get("source") and (m := ROLE_RE.search(s["source"]))), None)
        code = exit_code.get(name)
        if code is None and j.get("exit_status") not in (None, ""):
            try:
                code = float(j["exit_status"])
            except ValueError:
                code = None
        status = "drift" if j.get("missing") else job_status(code, j.get("failing"), remote=bool(j.get("host")))
        out.append({
            **j,
            "where": [w for w in r["where"] if w] or ([j["host"]] if j.get("host") else []),
            "group": ("remote" if j.get("host") else "missing-live" if j.get("missing")
                      else "in-ansible" if j.get("ansible_managed") else "unmanaged"),
            "role": role,
            "scripts": [s["path"] for s in r["scripts"]],
            "alert_rules": r["alert_rules"], "credentials": r["credentials"], "apis": r["apis"],
            "last_exit_code": None if code is None else int(code),
            "last_duration_s": duration.get(name),
            "last_cpu_s": cpu.get(name), "last_max_rss_bytes": rss.get(name),
            "last_run": _ts(last_run.get(name)), "last_success": _ts(last_ok.get(name)),
            "status": status,
        })
    return out


def job_status(exit_code, failing, remote: bool) -> str:
    """fail: last run failed. unwatched: a remote job nothing alerts on (VPS cron
    jobs all run through cron-shell, so CronJobFailed covers them). ok otherwise,
    including a job that has not run since cron-shell started recording."""
    if (exit_code is not None and exit_code != 0) or failing:
        return "fail"
    return "unwatched" if remote else "ok"


ENDPOINT_BAD = ("PUBLIC INTERNET", "DNS points straight at this host", "reachable from the internet")
ENDPOINT_WARN = ("no Traefik middlewares", "reachable from the LAN", "exposure unknown", "nothing listens on")


# Workstation plumbing that is normally open to the LAN: DNS, mDNS, LLMNR,
# DHCPv6 and Tailscale's own port.
BENIGN_LAN_PORTS = {53, 5353, 5355, 546, 547, 41641}
BROWSERS = {"firefox", "chrome", "chromium", "brave"}


def endpoint_severity(flags, proto: str | None = None, port: int | None = None,
                      process: str | None = None) -> str | None:
    """bad: exposed in a way that bypasses the front door. warn: a weak front
    door, or a service other machines on the LAN can reach. info: public by
    design (relying on the app's own sign-in) or ordinary workstation plumbing."""
    text = " | ".join(flags or [])
    if not text:
        return None
    if any(k in text for k in ENDPOINT_BAD):
        return "bad"
    if "reachable from the LAN" in text and (port in BENIGN_LAN_PORTS or (process or "").lower() in BROWSERS):
        return "info"
    if any(k in text for k in ENDPOINT_WARN):
        return "warn"
    return "info"


def unmanaged_severity(name: str) -> str:
    """OIDC/OAuth client secrets are issued by Authentik and fetched at deploy
    time (sso-setup, ops-dashboard-auth.yml), not hand-managed."""
    return "info" if re.search(r"(OIDC|OAUTH)_CLIENT_SECRET", name) else "warn"


def _ts(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch else None


async def databases() -> list[dict]:
    rows = await _q("""
        MATCH (ds:Datastore)
        OPTIONAL MATCH (ds)-[:RUNS_IN]->(c:Container)
        OPTIONAL MATCH (ds)-[:BACKED_UP_BY]->(b1:ScheduledJob)
        OPTIONAL MATCH (c)-[:BACKED_UP_BY]->(b2:ScheduledJob)
        OPTIONAL MATCH (src:Datasource)-[:READS]->(ds)
        OPTIONAL MATCH (dash:Dashboard)-[:QUERIES]->(src)
        RETURN ds {.name, .engine, .bytes, .state, .roles, .retention} AS store,
               c {.name, .pod, .ports, .memory_limit, .state} AS container,
               collect(DISTINCT coalesce(b1.name, b2.name)) AS backed_up_by,
               collect(DISTINCT dash.title) AS dashboards
        ORDER BY store.engine, store.name""")
    dbs = await _q("""
        MATCH (ds:Datastore)-[:HAS_DATABASE]->(db:Database)
        OPTIONAL MATCH (w)-[wr:WRITES]->(db)
        OPTIONAL MATCH (rd)-[rr:READS]->(db)
        OPTIONAL MATCH (u)-[:USES_DATABASE]->(db)
        OPTIONAL MATCH (src:Datasource)-[:READS]->(db)
        OPTIONAL MATCH (dash:Dashboard)-[:QUERIES]->(src)
        OPTIONAL MATCH (db)-[:HAS_TABLE]->(t:Table)
        RETURN ds.name AS store, db {.name, .db, .bytes, .tables, .nodes, .keys} AS database,
               collect(DISTINCT {who: w.name, user: wr.user, conns: wr.conns}) AS writers,
               collect(DISTINCT {who: rd.name, user: rr.user, conns: rr.conns}) AS readers,
               collect(DISTINCT u.name) AS declared_users,
               collect(DISTINCT dash.title) AS dashboards, count(DISTINCT t) AS table_count""")
    live = {}
    try:
        from .metrics import vm_client
        live = {k: v.model_dump() for k, v in (await vm_client.query_all_containers()).items()}
    except Exception:
        pass
    by_store = {}
    for d in dbs:
        by_store.setdefault(d["store"], []).append({
            **d["database"],
            "writers": [w for w in d["writers"] if w["who"]],
            "readers": [r for r in d["readers"] if r["who"]],
            "declared_users": d["declared_users"], "dashboards": d["dashboards"], "table_count": d["table_count"],
        })
    out = []
    for r in rows:
        st, c = r["store"], r["container"]
        res = live.get((c or {}).get("name"), {}) if c else {}
        access = []
        if c:
            access += [f"host {p.split('->')[0]}" for p in (c.get("ports") or [])]
            access.append("container network (any container)")
        out.append({**st, "container": c, "databases": by_store.get(st["name"], []),
                    "backed_up_by": [b for b in r["backed_up_by"] if b],
                    "dashboards": r["dashboards"], "resources": res or None, "access": access,
                    "status": "warn" if not r["backed_up_by"] or r["backed_up_by"] == [None] else "ok"})
    return out


async def tables(database: str | None = None, limit: int = 300) -> list[dict]:
    return await _q("""
        MATCH (db:Database)-[:HAS_TABLE]->(t:Table)
        WHERE $db IS NULL OR db.name = $db
        RETURN db.name AS database, t.schema AS schema, t.table AS table, t.rows AS rows, t.bytes AS bytes
        ORDER BY t.bytes DESC LIMIT $limit""", db=database, limit=limit)


async def mcp() -> list[dict]:
    return await _q("""
        MATCH (m:McpServer)
        OPTIONAL MATCH (m)-[:RUNS_IN]->(t)
        RETURN m {.name, .scope, .where, .transport, .command, .url, .status} AS server, t.name AS runs_in
        ORDER BY server.status, server.name""")


async def credentials() -> list[dict]:
    rows = await _q("""
        MATCH (c:Credential)
        OPTIONAL MATCH (c)-[i:INJECTED_INTO]->(ct:Container)
        OPTIONAL MATCH (s:Script)-[:USES]->(c)
        OPTIONAL MATCH (c)-[:GRANTS]->(g)
        OPTIONAL MATCH (c)-[:SAME_VALUE_AS]-(o:Credential)
        RETURN c {.name, .vault_files, .drift, .conflict, .duplicate_in_file, .empty, .unreferenced, .unmanaged,
                  .rotated_at, .tracking_since, .files} AS credential,
               collect(DISTINCT {container: ct.name, env: i.env, matches_vault: i.matches_vault}) AS containers,
               collect(DISTINCT s.name) AS scripts, head(collect(DISTINCT g.name)) AS grants,
               collect(DISTINCT o.name) AS same_value_as
        ORDER BY credential.name""")
    return [{**r["credential"], "containers": [x for x in r["containers"] if x["container"]],
             "scripts": r["scripts"], "grants": r["grants"], "same_value_as": r["same_value_as"]} for r in rows]


async def endpoints() -> list[dict]:
    return await _q("""
        MATCH (e:PublicEndpoint)
        OPTIONAL MATCH (e)-[:EXPOSES]->(:Route)-[:ROUTES_TO]->(t)
        RETURN e {.key, .name, .kind, .host, .path, .proto, .port, .process, .reachable, .via, .access,
                  .middlewares, .flags, .flagged} AS endpoint, collect(DISTINCT t.name) AS served_by
        ORDER BY endpoint.flagged DESC, endpoint.kind, endpoint.name""")


async def pipelines(own_only: bool = True) -> list[dict]:
    return await _q("""
        MATCH (p:Pipeline) WHERE NOT $own OR p.own
        RETURN p {.file, .name, .system, .origin, .repo, .host, .state, .runnable, .triggers, .runner, .deploys,
                  .secret_names, .github_state, .last_run_status, .last_run_at} AS pipeline
        ORDER BY pipeline.runnable DESC, pipeline.system, pipeline.name""", own=own_only)


async def alert_rules() -> dict:
    rules = await _q("""
        MATCH (r:AlertRule)
        OPTIONAL MATCH (r)-[:WATCHES]->(t)
        RETURN r {.key, .name, .source, .group, .severity, .state, .health, .covers_all_containers, .paused, .expr}
               AS rule, collect(DISTINCT t.name) AS watches
        ORDER BY rule.state DESC, rule.source, rule.name""")
    gaps = await _q("""
        CALL { MATCH (c:Container) WHERE coalesce(c.alert_rules, 0) = 0 RETURN collect(c.name) AS containers }
        CALL { MATCH (j:ScheduledJob) WHERE coalesce(j.alert_rules, 0) = 0 AND j.host IS NULL
               RETURN collect(j.name) AS jobs }
        RETURN containers, jobs""")
    return {"rules": rules, "unwatched": gaps[0] if gaps else {}}


async def scripts() -> list[dict]:
    return await _q("""
        MATCH (s:Script)
        OPTIONAL MATCH (j:ScheduledJob)-[:RUNS]->(s)
        OPTIONAL MATCH (s)-[:EXECS_IN]->(c:Container)
        OPTIONAL MATCH (s)-[:CALLS]->(t)
        OPTIONAL MATCH (s)-[:CALLS_EXTERNAL]->(x:External)
        OPTIONAL MATCH (s)-[:USES]->(k:Credential)
        RETURN s {.path, .name, .lang, .source} AS script, collect(DISTINCT j.name) AS run_by,
               collect(DISTINCT c.name) AS execs_in, collect(DISTINCT t.name) AS calls,
               collect(DISTINCT x.name) AS apis, collect(DISTINCT k.name) AS credentials
        ORDER BY script.path""")


async def apis() -> dict:
    outbound = await _q("""
        MATCH (x:External)
        OPTIONAL MATCH (caller)-[r:CALLS_EXTERNAL]->(x)
        OPTIONAL MATCH (k:Credential)-[:GRANTS]->(x)
        RETURN x {.name, .category, .hosts, .requests_7d} AS api,
               collect(DISTINCT caller.name) AS callers, collect(DISTINCT k.name) AS credentials
        ORDER BY api.requests_7d DESC""")
    internal = await _q("""
        MATCH (a:Api)
        OPTIONAL MATCH (a)-[:IMPLEMENTED_BY]->(e:Endpoint)
        RETURN a {.router, .method, .path, .hits_7d, .errors_4xx_7d, .errors_5xx_7d, .p95_ms} AS api,
               e.project AS implemented_in
        ORDER BY api.hits_7d DESC LIMIT 200""")
    return {"outbound": outbound, "internal": internal}


async def hosts() -> list[dict]:
    return await _q("""
        MATCH (h:Host)
        RETURN h {.name, .os, .remote, .stale, .snapshot_at, .repos, .repos_dirty, .repos_unpushed} AS host
        ORDER BY host.remote, host.name""")


async def findings() -> list[dict]:
    """What needs attention, generated from the graph's flags (most severe first)."""
    out = []
    for j in await jobs():
        if j["status"] == "drift":
            out.append({"severity": "info" if j.get("conditional") else "warn", "kind": "job",
                        "title": f"{j['name']} is defined in Ansible but not in the crontab",
                        "detail": f"role {j.get('role') or '?'}" + (" (switched off by a when: condition?)" if j.get("conditional") else
                                                                    ": rerun that role's cron tags")})
        if j["status"] == "fail":
            out.append({"severity": "bad", "kind": "job", "title": f"{j['name']} is failing",
                        "detail": f"last exit {j['last_exit_code']}" + (f" ({j['last_result']})" if j.get('last_result') else "")})
    for c in await credentials():
        if c.get("drift"):
            out.append({"severity": "bad", "kind": "credential", "title": f"{c['name']}: live value differs from the vault",
                        "detail": ", ".join(x["container"] for x in c["containers"])})
        if c.get("conflict"):
            out.append({"severity": "warn", "kind": "credential", "title": f"{c['name']} differs between the two vault files",
                        "detail": "the root vault.yml wins"})
        if c.get("unmanaged"):
            sev = unmanaged_severity(c["name"])
            out.append({"severity": sev, "kind": "credential", "title": f"{c['name']} is in no vault",
                        "detail": "issued by Authentik at deploy time" if sev == "info" else "managed by hand"})
    for e in await endpoints():
        ep = e["endpoint"]
        sev = endpoint_severity(ep.get("flags"), ep.get("proto"), ep.get("port"), ep.get("process"))
        if sev:
            out.append({"severity": sev, "kind": "endpoint", "title": e["endpoint"]["name"],
                        "detail": "; ".join(e["endpoint"]["flags"])})
    al = await alert_rules()
    for r in al["rules"]:
        if r["rule"].get("state") == "firing":
            out.append({"severity": "bad", "kind": "alert", "title": f"{r['rule']['name']} is firing",
                        "detail": ", ".join(r["watches"])})
    remote_unwatched = [j["name"] for j in await jobs() if j["status"] == "unwatched"]
    if remote_unwatched:
        out.append({"severity": "info", "kind": "coverage",
                    "title": f"{len(remote_unwatched)} jobs on other hosts have no alert",
                    "detail": "laptop timers are inventoried but nothing pages when they fail"})
    order = {"bad": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda f: order[f["severity"]])


VIEWS = {"summary": summary, "jobs": jobs, "databases": databases, "mcp": mcp, "credentials": credentials,
         "endpoints": endpoints, "alerts": alert_rules, "scripts": scripts, "apis": apis, "hosts": hosts,
         "findings": findings}


@router.get("/tables")
async def get_tables(database: str | None = None, limit: int = Query(300, ge=1, le=2000)):
    return await tables(database, limit)


@router.get("/pipelines")
async def get_pipelines(own: bool = True):
    return await pipelines(own)


@router.get("/{view}")
async def get_view(view: str):
    fn = VIEWS.get(view)
    if not fn:
        raise HTTPException(404, f"unknown inventory view {view!r}")
    return await fn()
