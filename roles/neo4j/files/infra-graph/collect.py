#!/usr/bin/env python3
"""infra-graph collector: discover what is ACTUALLY running and emit infra.json.

Every fact comes from a live source on this host, never from a hand-written map:

  podman   pods, containers, networks, IPs, mounts, limits   (podman inspect)
  cron     scheduled jobs                                    (/etc/crontabs/root)
  db       datastores, databases, tables, live connections   (pg/neo4j/redis catalogs, sqlite files)
  traefik  routes, middlewares, backends                     (/opt/compose/traefik/dynamic/*.yml)
  grafana  dashboards, datasources, panel->datasource links  (Grafana HTTP API)
  backup   which mounts/volumes the nightly backup covers    (/usr/local/bin/vps-backup)
  scripts  the scripts cron runs, what they call and exec    (script files on disk, read-only)
  egress   outbound APIs actually called, by container      (Squid access-json.log, last 7 days)
  ingress  which routed API paths are actually used          (Traefik access.log, last 7 days)

Output is one JSON document consumed by load-infra.cypher via apoc.load.json.
Each source reports ok/failed in `sources`; the loader only reconciles (deletes
stale nodes for) sources that succeeded, so one broken API can never wipe a
slice of the graph.

Secrets: credentials are read from container metadata at runtime and passed to
child processes through the environment, never argv, and never written to the
output. Connection strings are reduced to host/port/db before they are stored.

Stdlib + PyYAML only (both present on the host).
"""
import glob
import gzip
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import base64
import calendar
from datetime import datetime, timezone

import yaml

HOST = "alpine-vps"
DYNAMIC_DIR = "/opt/compose/traefik/dynamic"
CRONTAB = "/etc/crontabs/root"
BACKUP_SCRIPT = "/usr/local/bin/vps-backup"
SQLITE_ROOTS = ["/opt/podman-data", "/opt/compose"]
REPO = "/workspace/vscode-projects/vps_setup"
SQUID_LOGS = "/var/log/squid/access-json.log*"
TRAEFIK_LOGS = "/opt/podman-data/crowdsec/traefik-logs/access.log*"
WINDOW_DAYS = 7
OWN_DOMAIN = "aicortex.cloud"

# Which engine a container runs, by image substring. Order matters: vmalert
# must not be mistaken for victoriametrics.
ENGINES = [
    ("vmalert", None),
    ("pgvector", "postgres"), ("postgres", "postgres"),
    ("redis", "redis"), ("neo4j:", "neo4j"),
    ("victoriametrics", "victoriametrics"),
    ("grafana/loki", "loki"), ("grafana/tempo", "tempo"),
]
# Well-known service ports, used to resolve "localhost:5432" / "<pod>:5432"
# to the member container that actually listens there.
PORT_ENGINE = {"5432": "postgres", "6379": "redis", "7687": "neo4j", "7474": "neo4j",
               "8428": "victoriametrics", "3100": "loki", "3200": "loki", "3201": "tempo"}

SECRET_RE = re.compile(r"(?i)((?:token|secret|password|passwd|pass|key|auth)[A-Z_]*=)\S+")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd, env=None, timeout=120, input=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e, input=input)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} {cmd[1] if len(cmd) > 1 else ''} rc={r.returncode}: {r.stderr.strip()[:200]}")
    return r.stdout


def redact(s):
    return SECRET_RE.sub(r"\1<redacted>", s or "")


def du_bytes(path):
    try:
        out = run(["du", "-sk", path], timeout=300)
        return int(out.split()[0]) * 1024
    except Exception:
        return None


# ───────────────────────────── podman ─────────────────────────────
def collect_podman(out):
    ps = json.loads(run(["podman", "ps", "-a", "--format", "json"]))
    ids = [c["Id"] for c in ps]
    insp = json.loads(run(["podman", "inspect"] + ids)) if ids else []
    pods = json.loads(run(["podman", "pod", "ps", "--format", "json"]) or "[]")
    nets = json.loads(run(["podman", "network", "ls", "--format", "json"]) or "[]")

    out["networks"] = [{"name": n["name"],
                        "subnet": ",".join(s.get("subnet", "") for s in n.get("subnets") or []),
                        "driver": n.get("driver")} for n in nets]
    infra_ip = {}       # pod name -> {network: ip}
    infra_ports = {}    # pod name -> host port bindings (pods publish ports via their infra container)
    containers = []
    # inspect carries the pod's ID, not its name (PodName is not populated).
    pod_by_id = {p["Id"]: p["Name"] for p in pods}
    for c in insp:
        name = c["Name"]
        pod = pod_by_id.get(c.get("Pod") or "", "")
        is_infra = bool(c.get("IsInfra"))
        net = {k: v.get("IPAddress") for k, v in (c.get("NetworkSettings", {}).get("Networks") or {}).items()}
        if is_infra:
            infra_ip[pod] = net
            infra_ports[pod] = [f'{b.get("HostIp") or "0.0.0.0"}:{b.get("HostPort")}->{cp}'
                                for cp, bs in ((c.get("HostConfig") or {}).get("PortBindings") or {}).items()
                                for b in bs or []]
            continue
        hc = c.get("HostConfig", {})
        cfg = c.get("Config", {})
        ports = []
        for cport, binds in (hc.get("PortBindings") or {}).items():
            for b in binds or []:
                ports.append(f'{b.get("HostIp") or "0.0.0.0"}:{b.get("HostPort")}->{cport}')
        containers.append({
            "name": name, "pod": pod, "image": cfg.get("Image") or c.get("ImageName"),
            "state": c["State"]["Status"], "oom_killed": bool(c["State"].get("OOMKilled")),
            "started": c["State"].get("StartedAt"), "restart_policy": (hc.get("RestartPolicy") or {}).get("Name"),
            "memory_limit": hc.get("Memory") or 0, "networks": net, "ports": ports,
            "mounts": [{"type": m.get("Type"), "source": m.get("Source"), "name": m.get("Name"),
                        "dest": m.get("Destination")} for m in c.get("Mounts") or []],
            "env_keys": sorted({e.split("=", 1)[0] for e in cfg.get("Env") or []}),
            "_env": cfg.get("Env") or [], "_cmd": cfg.get("Cmd") or [],
        })
    # Pod members share the infra container's network namespace: give them its IPs.
    for c in containers:
        if c["pod"] and not c["networks"]:
            c["networks"] = infra_ip.get(c["pod"], {})
    out["pods"] = [{"name": p["Name"], "status": p["Status"],
                    "networks": infra_ip.get(p["Name"], {}), "ports": infra_ports.get(p["Name"], []),
                    "members": [m["Names"] for m in p.get("Containers") or [] if m["Names"] != p["Name"] + "-infra"
                                and not m["Names"].endswith("-infra")]} for p in pods]
    out["containers"] = containers
    if len(containers) < 5:
        raise RuntimeError(f"implausible: only {len(containers)} containers")


def engine_of(c):
    img = (c.get("image") or "").lower()
    for needle, eng in ENGINES:
        if needle in img:
            return eng
    return None


def env_of(c):
    return dict(e.split("=", 1) for e in c["_env"] if "=" in e)


class Resolver:
    """host[:port] as written in a URL/env -> the container that serves it."""

    def __init__(self, out):
        self.by_name = {c["name"]: c for c in out["containers"]}
        self.pod_members = {}
        self.by_ip = {}
        for c in out["containers"]:
            self.pod_members.setdefault(c["pod"], []).append(c)
            for ip in c["networks"].values():
                if ip:
                    self.by_ip.setdefault(ip, []).append(c)
        # Host-published ports ("127.0.0.1:8428->8428/tcp"), so a host script's
        # http://127.0.0.1:8428 resolves to the container behind it. Pods publish
        # through their infra container, so map those to the member that listens.
        self.host_ports = {}
        for c in out["containers"]:
            for p in c["ports"]:
                self.host_ports.setdefault(p.split("->")[0].rsplit(":", 1)[-1], c["name"])
        for p in out.get("pods", []):
            for x in p.get("ports", []):
                hp, _, cp = x.partition("->")
                member = self._pick(self.pod_members.get(p["name"], []), cp.split("/")[0])
                self.host_ports.setdefault(hp.rsplit(":", 1)[-1], member or p["name"])

    def _pick(self, cands, port):
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]["name"]
        want = PORT_ENGINE.get(str(port))
        for c in cands:
            if want and engine_of(c) == want:
                return c["name"]
        for c in cands:  # a member that publishes the port
            if any(p.endswith(f"->{port}/tcp") for p in c["ports"]):
                return c["name"]
        return None

    def resolve(self, host, port=None, from_container=None):
        host = (host or "").strip().lower()
        if not host:
            return None
        if host in ("localhost", "127.0.0.1", "::1") and from_container:
            fc = self.by_name.get(from_container)
            if fc and fc["pod"]:
                return self._pick(self.pod_members[fc["pod"]], port)
            return from_container
        if host in ("localhost", "127.0.0.1", "::1"):  # seen from the host itself
            return self.host_ports.get(str(port)) if port else None
        if host in self.by_name:
            return host
        if host in self.pod_members and host:
            return self._pick(self.pod_members[host], port)
        if host in self.by_ip:
            return self._pick(self.by_ip[host], port)
        return None


URL_RE = re.compile(r"^(?P<scheme>[a-z0-9+]+)://(?:[^@/]*@)?(?P<host>[^:/?#]+)(?::(?P<port>\d+))?(?:/(?P<path>[^?#]*))?", re.I)


def env_dependencies(c, resolver):
    """Declared dependencies from env: URLs and *_HOST/*_PORT/*_DB triples. Values never stored."""
    env = env_of(c)
    deps = []
    for k, v in env.items():
        m = URL_RE.match(v.strip())
        if not m:
            continue
        tgt = resolver.resolve(m["host"], m["port"], c["name"])
        if tgt and tgt != c["name"]:
            db = (m["path"] or "").split("/")[0] if m["scheme"].lower().startswith("postgres") else ""
            deps.append({"to": tgt, "via": k, "db": db})
    for k, v in env.items():
        if k.endswith("_HOST") and v and not URL_RE.match(v):
            stem = k[:-5]
            port = env.get(stem + "_PORT")
            tgt = resolver.resolve(v, port, c["name"])
            if tgt and tgt != c["name"]:
                db = env.get(stem + "_NAME") or env.get(stem + "_DB") or env.get(stem + "_DATABASE") or ""
                deps.append({"to": tgt, "via": k, "db": db})
    seen, uniq = set(), []
    for d in deps:
        key = (d["to"], d["db"])
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    return uniq


# ───────────────────────────── databases ─────────────────────────────
PG_TABLES = r"""
SELECT n.nspname, c.relname, greatest(coalesce(s.n_live_tup, c.reltuples::bigint), 0),
       pg_total_relation_size(c.oid)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
WHERE c.relkind IN ('r','p','m')
  AND n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%'
"""
PG_WRITERS = r"""
SELECT r.rolname,
       r.rolsuper OR pg_has_role(r.oid, 'pg_write_all_data', 'MEMBER')
       OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                  WHERE c.relowner = r.oid AND n.nspname NOT IN ('pg_catalog','information_schema'))
       OR EXISTS (SELECT 1 FROM information_schema.role_table_grants g
                  WHERE g.grantee = r.rolname AND g.privilege_type IN ('INSERT','UPDATE','DELETE'))
FROM pg_roles r WHERE r.rolcanlogin
"""


def psql(container, user, db, sql):
    out = run(["podman", "exec", "-i", container, "psql", "-U", user, "-d", db, "-AtX", "-F", "\t", "-v",
               "ON_ERROR_STOP=1", "-f", "-"], input=sql, timeout=120)
    return [l.split("\t") for l in out.splitlines() if l.strip()]


def collect_postgres(c, ds, resolver, warnings):
    env = env_of(c)
    user = env.get("POSTGRES_USER", "postgres")
    root = env.get("POSTGRES_DB", "postgres")
    dbs = psql(c["name"], user, root,
               "SELECT datname, pg_database_size(datname) FROM pg_database WHERE NOT datistemplate AND datallowconn;")
    ds["roles"] = [r[0] for r in psql(c["name"], user, root,
                                      "SELECT rolname FROM pg_roles WHERE rolcanlogin ORDER BY 1;")]
    conns = psql(c["name"], user, root,
                 "SELECT datname, usename, coalesce(host(client_addr),'local'), count(*) FROM pg_stat_activity "
                 "WHERE backend_type='client backend' AND datname IS NOT NULL GROUP BY 1,2,3;")
    for dbname, size in dbs:
        db = {"name": f'{c["name"]}/{dbname}', "db": dbname, "bytes": int(size), "tables": [], "clients": []}
        try:
            writers = {r[0]: r[1] == "t" for r in psql(c["name"], user, dbname, PG_WRITERS)}
            for schema, rel, rows, nbytes in psql(c["name"], user, dbname, PG_TABLES):
                db["tables"].append({"name": f'{db["name"]}/{schema}.{rel}', "schema": schema, "table": rel,
                                     "rows": int(float(rows)), "bytes": int(nbytes)})
        except Exception as e:  # a DB we cannot open (e.g. missing extension) still exists
            writers = {}
            warnings.append(f'{db["name"]}: {e}')
        for cdb, usr, addr, n in conns:
            if cdb != dbname:
                continue
            who = c["name"] if addr in ("local", "127.0.0.1", "::1") else resolver.resolve(addr, None)
            # an IP owned by a pod resolves to all members; keep the pod name then
            if who is None:
                who = next((p for p, ms in resolver.pod_members.items()
                            if p and any(addr in m["networks"].values() for m in ms)), None)
            db["clients"].append({"who": who or addr, "user": usr, "conns": int(n),
                                  "writes": bool(writers.get(usr, False))})
        ds["databases"].append(db)


RETENTION_KEYS = {"loki": ("retention_period",), "tempo": ("block_retention",)}


def _retention(c, engine):
    """How long the store keeps data, read from its real configuration."""
    cmd = c.get("_cmd") or []
    if engine == "victoriametrics":
        v = next((a.split("=", 1)[1] for a in cmd if a.startswith("-retentionPeriod=")), None)
        return v or "1 month (VictoriaMetrics default)"
    if engine in RETENTION_KEYS:
        cfg = next((a.split("=", 1)[1] for a in cmd if a.startswith("-config.file=")), None)
        src = next((m["source"] for m in c["mounts"] if cfg and m.get("dest") == cfg), None)
        try:
            with open(src) as fh:
                text = fh.read()
        except (OSError, TypeError):
            return None
        for key in RETENTION_KEYS[engine]:
            m = re.search(rf"(?m)^\s*{key}:\s*([^\s#]+)", text)
            if m:
                return m[1]
        return None
    if engine == "neo4j":
        env = env_of(c)
        return env.get("NEO4J_db_tx__log_rotation_retention__policy") or "graph: kept; tx logs: Neo4j default"
    if engine == "postgres":
        return "none (rows kept until deleted)"
    return None


def collect_dbs(out):
    resolver = Resolver(out)
    warnings = []
    stores = []
    for c in out["containers"]:
        eng = engine_of(c)
        if not eng:
            continue
        ds = {"name": c["name"], "engine": eng, "container": c["name"], "state": c["state"],
              "bytes": None, "databases": [], "roles": [], "retention": _retention(c, eng)}
        binds = [m["source"] for m in c["mounts"] if m["type"] == "bind" and m["source"].startswith("/opt/")]
        if binds:
            ds["bytes"] = sum(b for b in (du_bytes(p) for p in binds) if b)
        if c["state"] != "running":
            stores.append(ds)
            continue
        try:
            if eng == "postgres":
                collect_postgres(c, ds, resolver, warnings)
            elif eng == "neo4j":
                q = "MATCH (n) RETURN count(n);"
                o = run(["podman", "exec", "-i", c["name"], "sh", "-c",
                         'cypher-shell -u neo4j -p "${NEO4J_AUTH#neo4j/}" --format plain'], input=q)
                ds["databases"].append({"name": f'{c["name"]}/neo4j', "db": "neo4j", "bytes": None,
                                        "nodes": int(o.split()[-1]), "tables": [], "clients": []})
            elif eng == "redis":
                cmd = c["_cmd"]
                pw = cmd[cmd.index("--requirepass") + 1] if "--requirepass" in cmd else ""
                o = run(["podman", "exec", "-e", "REDISCLI_AUTH", c["name"], "redis-cli", "dbsize"],
                        env={"REDISCLI_AUTH": pw} if pw else None)
                ds["databases"].append({"name": f'{c["name"]}/db0', "db": "db0", "bytes": None,
                                        "keys": int(o.strip().split()[-1]), "tables": [], "clients": []})
        except Exception as e:
            warnings.append(f'{c["name"]}: {e}')
        stores.append(ds)

    # SQLite files living in bind mounts: attribute each to the container mounting it.
    # Containers that mount whole trees (ansible-deployment: /opt/podman-data,
    # /workspace...) must not claim the files inside them; a file with no
    # narrower owner is reported as unowned, which is the truth.
    broad = {"/", "/opt", "/opt/podman-data", "/opt/compose", "/workspace", "/root", "/var", "/var/log"}
    mounts = [(m["source"], c["name"]) for c in out["containers"] for m in c["mounts"]
              if m["type"] == "bind" and m["source"] and m["source"].rstrip("/") not in broad]
    for root in SQLITE_ROOTS:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "cache", "postgres", "pgdata")]
            if dirpath.count("/") > 6:
                dirs[:] = []
            for f in files:
                if not re.search(r"\.(db|sqlite3?)$", f):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    with open(p, "rb") as fh:
                        if fh.read(16) != b"SQLite format 3\x00":
                            continue
                    st = os.stat(p)
                except OSError:
                    continue
                owner = next((cn for src, cn in sorted(mounts, key=lambda x: -len(x[0]))
                              if p.startswith(src.rstrip("/") + "/")), None)
                stores.append({"name": p, "engine": "sqlite", "container": owner, "state": "file",
                               "bytes": st.st_size, "mtime": int(st.st_mtime), "databases": [], "roles": []})
    out["datastores"] = stores
    out["db_warnings"] = warnings

    for c in out["containers"]:
        c["depends"] = env_dependencies(c, resolver)


# ───────────────────────────── cron ─────────────────────────────
def human_freq(m, h, dom, mon, dow):
    if (m, h, dom, mon, dow) == ("*", "*", "*", "*", "*"):
        return "every 1 min"
    if m.startswith("*/") and h == "*":
        return f"every {m[2:]} min" + ("" if dow == "*" else f", dow {dow}")
    if h == "*" and m.isdigit():
        return f"hourly at :{int(m):02d}"
    days = "daily" if dow == "*" and dom == "*" else (f"dow {dow}" if dow != "*" else f"day {dom}")
    if m.isdigit() and re.fullmatch(r"[\d,]+", h):
        return f"{days} at " + ", ".join(f"{int(x):02d}:{int(m):02d}" for x in h.split(","))
    return f"{m} {h} {dom} {mon} {dow}"


def collect_cron(out):
    jobs, name = [], None
    for line in open(CRONTAB):
        line = line.rstrip("\n")
        if line.startswith("#Ansible: "):
            name = line[len("#Ansible: "):].strip()
            continue
        if not line.strip() or line.lstrip().startswith("#") or re.match(r"^[A-Z_]+=", line):
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        m, h, dom, mon, dow, cmd = parts
        jname = name or re.sub(r"\.(sh|py)$", "", os.path.basename(cmd.split()[0]))
        execs = re.findall(r"podman\s+exec\s+(?:-\S+\s+)*([A-Za-z0-9_.-]+)", cmd)
        jobs.append({"name": jname, "schedule": f"{m} {h} {dom} {mon} {dow}",
                     "frequency": human_freq(m, h, dom, mon, dow), "command": redact(cmd)[:400],
                     "managed": name is not None, "runs_in": execs or [], "log": next(iter(
                         re.findall(r">>?\s*(/var/log/\S+)", cmd)), None)})
        name = None
    if not jobs:
        raise RuntimeError("implausible: crontab has no jobs")
    # Unmanaged lines can share a derived name; keep each one distinct.
    names = [j["name"] for j in jobs]
    for j in jobs:
        if names.count(j["name"]) > 1:
            j["name"] = f'{j["name"]} @ {j["schedule"]}'
    out["jobs"] = jobs


# ───────────────────────────── traefik ─────────────────────────────
def collect_traefik(out):
    resolver = Resolver(out)
    routes, mws = [], set()
    services = {}
    docs = []
    for f in sorted(os.listdir(DYNAMIC_DIR)):
        if not re.search(r"\.ya?ml$", f):
            continue  # *.bak-* files are not loaded by Traefik either
        with open(os.path.join(DYNAMIC_DIR, f)) as fh:
            d = yaml.safe_load(fh) or {}
        docs.append((f, d))
        http = d.get("http") or {}
        for sname, s in (http.get("services") or {}).items():
            services[sname] = [x.get("url") for x in ((s.get("loadBalancer") or {}).get("servers") or [])]
        mws.update((http.get("middlewares") or {}).keys())
    for f, d in docs:
        for rname, r in ((d.get("http") or {}).get("routers") or {}).items():
            hosts = re.findall(r"Host\(`([^`]+)`\)", r.get("rule", ""))
            path = re.findall(r"PathPrefix\(`([^`]+)`\)", r.get("rule", ""))
            svc = (r.get("service") or "").split("@")[0]
            backends = []
            for u in services.get(svc, []):
                m = URL_RE.match(u or "")
                if m:
                    h = m["host"].lower()
                    backends.append({"url": u, "to": resolver.resolve(h, m["port"]),
                                     "pod": h if h in resolver.pod_members and h else None})
            for h in hosts or [None]:
                # Several routers can share a host (the apex has one per path and
                # priority), so the router name is part of the identity.
                key = f'{h or "-"}{path[0] if path else ""}#{rname}'
                routes.append({"key": key, "host": h, "path": path[0] if path else None, "router": rname,
                               "file": f, "service": svc, "backends": backends,
                               "middlewares": [x.split("@")[0] for x in r.get("middlewares") or []]})
    if not routes:
        raise RuntimeError("implausible: no Traefik routers found")
    out["routes"] = routes
    out["middlewares"] = sorted(mws)


# ───────────────────────────── grafana ─────────────────────────────
def collect_grafana(out):
    env = env_of(next(c for c in out["containers"] if c["name"] == "grafana"))
    tok = base64.b64encode(f'{env["GF_SECURITY_ADMIN_USER"]}:{env["GF_SECURITY_ADMIN_PASSWORD"]}'.encode()).decode()

    def get(path):
        req = urllib.request.Request("http://127.0.0.1:3000" + path, headers={"Authorization": "Basic " + tok})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    resolver = Resolver(out)
    dss = get("/api/datasources")
    default_uid = next((d["uid"] for d in dss if d.get("isDefault")), None)
    by_name = {d["name"]: d["uid"] for d in dss}
    out["datasources"] = []
    for d in dss:
        m = URL_RE.match(d.get("url") or "") or URL_RE.match("x://" + (d.get("url") or ""))
        # Datasource URLs are written from Grafana's point of view: "localhost"
        # means Grafana's own pod (metrics-pod), so resolve relative to it.
        tgt = resolver.resolve(m["host"], m["port"], "grafana") if m else None
        db = d.get("database") or (d.get("jsonData") or {}).get("database") or ""
        out["datasources"].append({"uid": d["uid"], "name": d["name"], "type": d["type"],
                                   "target": tgt, "db": db})
    dashes = []
    for s in get("/api/search?type=dash-db&limit=5000"):
        try:
            dash = get(f'/api/dashboards/uid/{s["uid"]}')["dashboard"]
        except Exception:
            continue
        used = set()

        def walk(o):
            if isinstance(o, dict):
                ds = o.get("datasource")
                if isinstance(ds, dict) and ds.get("uid") and not str(ds["uid"]).startswith("$"):
                    used.add(ds["uid"])
                elif isinstance(ds, str) and ds in by_name:
                    used.add(by_name[ds])
                elif "targets" in o and ds is None and default_uid:
                    used.add(default_uid)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(dash.get("panels") or [])
        walk(dash.get("rows") or [])
        dashes.append({"uid": s["uid"], "title": s["title"], "folder": s.get("folderTitle") or "General",
                       "datasources": sorted(u for u in used if u in {d["uid"] for d in dss})})
    if not dashes:
        raise RuntimeError("implausible: Grafana returned no dashboards")
    out["dashboards"] = dashes


# ───────────────────────────── backup coverage ─────────────────────────────
def collect_backup(out):
    txt = open(BACKUP_SCRIPT).read()
    dirs = re.findall(r'^if \[ -d "([^"]+)" \]', txt, re.M)
    vols = re.findall(r"podman volume export (\S+)", txt)
    covered = []
    for c in out["containers"]:
        hit = [m["source"] for m in c["mounts"] if m["type"] == "bind" and m["source"]
               and any(m["source"] == d or m["source"].startswith(d.rstrip("/") + "/") for d in dirs)]
        hit += [m["name"] for m in c["mounts"] if m["type"] == "volume" and m["name"] in vols]
        if hit:
            covered.append({"container": c["name"], "paths": sorted(set(hit))})
    out["backup"] = {"job": "vps-daily-backup", "dirs": dirs, "volumes": vols, "covered": covered}



# ───────────────────────────── MCP servers ─────────────────────────────
CLAUDE_JSON = "/root/.claude.json"
CLAUDE_SETTINGS = "/root/.claude/settings.json"
LEGACY_MCP = "/root/.claude/mcp_settings.json"
PLUGIN_CACHE = "/root/.claude/plugins/cache"


def _vkey(v):
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v)]


def _tcp_ok(host, port):
    import socket
    try:
        with socket.create_connection((host, int(port)), timeout=3):
            return True
    except Exception:
        return False


def mcp_health(srv, containers):
    """Cheap, deterministic health: never launches the server itself."""
    t = srv["transport"]
    if t == "stdio":
        args = srv.get("args") or []
        cmd = srv.get("command") or ""
        if cmd == "podman" and args[:1] == ["exec"]:
            rest = [a for a in args[1:]]
            # skip flags like -i, -e K=V
            i = 0
            while i < len(rest) and rest[i].startswith("-"):
                i += 2 if rest[i] in ("-e", "--env", "-w", "--workdir", "-u", "--user") else 1
            cname = rest[i] if i < len(rest) else None
            srv["container"] = cname
            entry = next((a for a in rest[i + 1:] if re.search(r"\.(py|js|mjs)$", a)), None)
            c = containers.get(cname)
            if not c:
                return "container-missing"
            if c["state"] != "running":
                return "container-stopped"
            if entry:
                try:
                    run(["podman", "exec", cname, "test", "-e", entry if entry.startswith("/") else
                         os.path.join("/app", entry.lstrip("./"))], timeout=20)
                except Exception:
                    return "entry-missing"
            return "ok"
        if not cmd:
            return "misconfigured"
        if subprocess.run(["sh", "-c", f"command -v {cmd}"], capture_output=True).returncode != 0:
            return "runtime-missing"
        return "ok"
    url = srv.get("url") or ""
    if "${" in url:
        return "misconfigured"
    m = URL_RE.match(url)
    if not m:
        return "misconfigured"
    host, port = m["host"], m["port"] or ("443" if url.startswith("https") else "80")
    srv["host"], srv["port"] = host, port
    if host in ("127.0.0.1", "localhost"):
        return "ok" if _tcp_ok("127.0.0.1", port) else "refused"
    return "remote"


def collect_mcp(out):
    containers = {c["name"]: c for c in out.get("containers", [])}
    cj = json.load(open(CLAUDE_JSON))
    servers = []

    def add(name, scope, cfg, where=None, disabled=False):
        t = cfg.get("type") or ("stdio" if cfg.get("command") else "http")
        srv = {"key": f"{scope}:{name}" + (f"@{where}" if where else ""), "name": name, "scope": scope,
               "where": where, "transport": t, "command": cfg.get("command"),
               "args": [redact(a) for a in cfg.get("args") or []], "url": redact(cfg.get("url") or ""),
               "env_keys": sorted((cfg.get("env") or {}).keys()),
               "header_keys": sorted((cfg.get("headers") or {}).keys())}
        srv["status"] = "disabled" if disabled else mcp_health(srv, containers)
        if srv["transport"] != "stdio" and srv.get("host") and srv["host"] in ("127.0.0.1", "localhost"):
            srv["container"] = next((c["name"] for c in out.get("containers", [])
                                     if any(p.startswith(f'127.0.0.1:{srv["port"]}->') or p.startswith(f'0.0.0.0:{srv["port"]}->')
                                            for p in c["ports"])), None)
            if not srv["container"]:  # published by a pod's infra container
                srv["pod"] = next((p["name"] for p in out.get("pods", [])
                                   if any(x.split("->")[0].endswith(f':{srv["port"]}') for x in p.get("ports", []))), None)
        servers.append(srv)

    for n, cfg in (cj.get("mcpServers") or {}).items():
        add(n, "user", cfg)
    for proj, pc in (cj.get("projects") or {}).items():
        disabled = set(pc.get("disabledMcpServers") or [])
        for n, cfg in (pc.get("mcpServers") or {}).items():
            add(n, "local", cfg, where=proj, disabled=n in disabled)
    if os.path.exists(LEGACY_MCP):
        for n, cfg in (json.load(open(LEGACY_MCP)).get("mcpServers") or {}).items():
            add(n, "legacy-file", cfg, where=LEGACY_MCP)
    enabled = {}
    if os.path.exists(CLAUDE_SETTINGS):
        enabled = {k: v for k, v in (json.load(open(CLAUDE_SETTINGS)).get("enabledPlugins") or {}).items() if v}
    for pid in enabled:
        plugin, _, market = pid.partition("@")
        base = os.path.join(PLUGIN_CACHE, market, plugin)
        if not os.path.isdir(base):
            continue
        vers = sorted(os.listdir(base), key=_vkey)
        f = os.path.join(base, vers[-1], ".mcp.json") if vers else None
        if f and os.path.exists(f):
            d = json.load(open(f))
            for n, cfg in (d.get("mcpServers") or d).items():
                if isinstance(cfg, dict):
                    add(f"plugin:{plugin}:{n}", "plugin", cfg)
    for n in cj.get("claudeAiMcpEverConnected") or []:
        servers.append({"key": f"claude.ai:{n}", "name": n, "scope": "claude.ai", "where": None,
                        "transport": "http", "command": None, "args": [], "url": "", "env_keys": [],
                        "header_keys": [], "status": "account-connector", "container": None})
    if not servers:
        raise RuntimeError("implausible: no MCP servers configured")
    out["mcp_servers"] = servers


# ───────────────────────────── outbound API naming ─────────────────────────────
# Host suffix -> (API name, category). Names match the hand-curated External
# nodes (OpenAI, api.telegram.org, CrowdSec CAPI, ...) so observed traffic lands
# on those nodes instead of beside them. First match wins: specific hosts first.
API_PROVIDERS = [
    ("aiplatform.googleapis.com", "Google Vertex AI", "llm"),
    ("generativelanguage.googleapis.com", "Google Gemini API", "llm"),
    ("openai.com", "OpenAI", "llm"), ("anthropic.com", "Anthropic", "llm"),
    ("openrouter.ai", "OpenRouter", "llm"), ("groq.com", "Groq", "llm"),
    ("cohere.com", "Cohere", "llm"), ("cohere.ai", "Cohere", "llm"), ("x.ai", "xAI", "llm"),
    ("deepseek.com", "DeepSeek", "llm"), ("huggingface.co", "Hugging Face", "llm"),
    ("api.telegram.org", "api.telegram.org", "messaging"), ("resend.com", "Resend SMTP", "messaging"),
    ("twilio.com", "Twilio", "messaging"), ("heygen.com", "HeyGen", "media"),
    ("ibkr.com", "IBKR", "market-data"), ("interactivebrokers.com", "IBKR", "market-data"),
    ("aisstream.io", "aisstream.io", "data-feed"), ("wigle.net", "WiGLE API", "data-feed"),
    ("wikidata.org", "Wikidata", "data-feed"),
    ("version.crowdsec.net", "CrowdSec version check", "vendor-phone-home"),
    ("crowdsec.net", "CrowdSec CAPI", "security-feed"), ("maxmind.com", "MaxMind", "security-feed"),
    ("abuse.ch", "abuse.ch", "security-feed"),
    ("stats.grafana.org", "Grafana usage stats", "vendor-phone-home"),
    ("grafana.com", "grafana.com", "vendor"),
    ("version.goauthentik.io", "Authentik version check", "vendor-phone-home"),
    ("goauthentik.io", "goauthentik.io", "vendor"),
    ("checkpoint.prisma.io", "Prisma telemetry", "vendor-phone-home"),
    ("update.argotunnel.com", "cloudflared update check", "vendor-phone-home"),
    ("argotunnel.com", "Cloudflare Edge", "infra"), ("cftunnel.com", "Cloudflare Edge", "infra"),
    ("r2.cloudflarestorage.com", "Cloudflare R2", "storage"), ("api.cloudflare.com", "Cloudflare API", "infra"),
    ("cloudflareaccess.com", "Cloudflare Access", "infra"), ("tailscale.com", "Tailscale", "infra"),
    ("gravatar.com", "Gravatar", "vendor"),
    # Chromium inside the Grafana image renderer / Playwright phones home on its own.
    ("clients.google.com", "Chromium phone-home", "vendor-phone-home"),
    ("clients2.google.com", "Chromium phone-home", "vendor-phone-home"),
    ("optimizationguide-pa.googleapis.com", "Chromium phone-home", "vendor-phone-home"),
    ("content-autofill.googleapis.com", "Chromium phone-home", "vendor-phone-home"),
    ("update.googleapis.com", "Chromium phone-home", "vendor-phone-home"),
    ("gvt1.com", "Chromium phone-home", "vendor-phone-home"),
    ("go-mpulse.net", "Akamai mPulse", "vendor-phone-home"),
    ("accounts.google.com", "Google accounts", "vendor"), ("www.google.com", "google.com", "vendor"),
    ("googleapis.com", "Google APIs", "cloud"),
    ("github.com", "GitHub", "dev"), ("githubusercontent.com", "GitHub", "dev"), ("ghcr.io", "GitHub", "registry"),
    ("docker.io", "Docker Hub", "registry"), ("quay.io", "Quay", "registry"),
    ("pypi.org", "PyPI", "registry"), ("pythonhosted.org", "PyPI", "registry"),
    ("npmjs.org", "npm", "registry"), ("debian.org", "Debian packages", "registry"),
    ("nodesource.com", "NodeSource packages", "registry"), ("alpinelinux.org", "Alpine packages", "registry"),
]


def api_of(host):
    h = host.lower().rstrip(".")
    for suffix, name, cat in API_PROVIDERS:
        if h == suffix or h.endswith("." + suffix):
            return name, cat
    if h.endswith(".amazonaws.com"):
        return "AWS " + h.split(".")[0], "cloud"
    return ".".join(h.split(".")[-2:]), "other"


def is_public_host(h):
    h = h.lower()
    if "." not in h or h.endswith((".internal", ".local", ".lan", ".localdomain")):
        return False
    try:
        return ipaddress.ip_address(h).is_global
    except ValueError:
        return True


def norm_path(p):
    """Collapse ids, numbers and templated/secret-looking segments so paths aggregate."""
    p = (p or "/").split("?")[0].split("#")[0] or "/"
    segs = []
    for s in p.split("/"):
        if "$" in s or "{" in s or "%" in s:
            s = "{var}"
        elif re.fullmatch(r"\d+", s):
            s = "{n}"
        elif re.fullmatch(r"[0-9a-fA-F-]{16,}", s):
            s = "{id}"
        elif len(s) > 40 or re.fullmatch(r"[A-Za-z0-9_:-]{28,}", s):
            s = "{x}"
        segs.append(s)
    return "/".join(segs)[:160] or "/"


def read_json_log(pattern, since):
    """JSON lines from a log and its rotations (plain or .gz) modified since `since`."""
    for p in sorted(glob.glob(pattern)):
        try:
            if os.path.getmtime(p) < since:
                continue
            opener = gzip.open if p.endswith(".gz") else open
            with opener(p, "rt", errors="replace") as fh:
                for line in fh:
                    if line.startswith("{"):
                        try:
                            yield json.loads(line)
                        except ValueError:
                            pass
        except OSError:
            continue


# ───────────────────────────── scripts ─────────────────────────────
FILE_REF_RE = re.compile(r"(?<![\w.-])(/(?:opt/compose|etc|root/\.config|usr/local/etc)/[\w./+-]+)")
SCRIPT_RE = re.compile(r"(?<![\w.-])(/(?:usr/local/s?bin|opt/compose|opt/scripts|root/bin)/[\w./+-]+)")
REL_SCRIPT_RE = re.compile(r"\$\{?(?:HERE|DIR|SCRIPT_DIR|BASEDIR)\}?/([\w./+-]+)")
TEXT_URL_RE = re.compile(r"\b(https?)://([A-Za-z0-9._-]+)(?::(\d+))?(/[^\s\"'`<>)\]}]*)?")
EXEC_FLAGS_WITH_VALUE = {"-e", "--env", "-u", "--user", "-w", "--workdir", "--env-file"}


def exec_targets(text):
    """Container names after `podman exec [flags]`, flags with values skipped."""
    found = []
    for m in re.finditer(r"podman\s+exec\s+([^\n;|&]*)", text):
        toks = m.group(1).split()
        i = 0
        while i < len(toks) and toks[i].startswith("-"):
            i += 2 if toks[i] in EXEC_FLAGS_WITH_VALUE else 1
        if i < len(toks):
            found.append(toks[i].strip("\"'"))
    return found


def _tasks(node):
    """Every task dict in a tasks file, descending into block/rescue/always."""
    if isinstance(node, list):
        for x in node:
            yield from _tasks(x)
    elif isinstance(node, dict):
        yield node
        for k in ("block", "rescue", "always"):
            yield from _tasks(node.get(k))


def repo_sources():
    """(deployed path -> repo file, stem -> candidate repo files).

    The first map is exact: it comes from the roles' copy/template tasks,
    including simple `loop:` lists of {src, dest} items. The second is the
    fallback, matched on name with .py/.sh/.j2 stripped, because deployed
    scripts usually drop their extension (cloudflare-zone-metrics.py.j2).
    """
    dests, names = {}, {}
    roles = os.path.join(REPO, "roles")
    if not os.path.isdir(roles):
        return dests, names
    # Some scripts ship straight from tools/ rather than from a role.
    for dirpath, dirs, files in os.walk(os.path.join(REPO, "tools")):
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__", "tests")]
        for f in files:
            names.setdefault(script_stem(f), []).append(os.path.join(dirpath, f))
    for role in sorted(os.listdir(roles)):
        rdir = os.path.join(roles, role)
        for kind in ("files", "templates"):
            for dirpath, dirs, files in os.walk(os.path.join(rdir, kind)):
                dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__", "tests")]
                for f in files:
                    names.setdefault(script_stem(f), []).append(os.path.join(dirpath, f))
        for tf in glob.glob(os.path.join(rdir, "tasks", "*.yml")):
            try:
                with open(tf) as fh:
                    doc = yaml.safe_load(fh)
            except Exception:
                continue
            for t in _tasks(doc):
                for mod in ("template", "copy", "ansible.builtin.template", "ansible.builtin.copy"):
                    a = t.get(mod)
                    if not isinstance(a, dict) or not isinstance(a.get("src"), str) or not isinstance(a.get("dest"), str):
                        continue
                    items = t.get("loop") or t.get("with_items")
                    pairs = [(a["src"], a["dest"])]
                    if isinstance(items, list) and "{{" in a["src"] + a["dest"]:
                        sub = lambda s, it: re.sub(r"\{\{\s*item\.(\w+)\s*\}\}", lambda m: str(it.get(m[1], m[0])), s)
                        pairs = [(sub(a["src"], it), sub(a["dest"], it)) for it in items if isinstance(it, dict)]
                    for src, dest in pairs:
                        if "{{" in src or "{{" in dest:
                            continue
                        src = src if src.startswith("/") else os.path.join(rdir, "templates" if "template" in mod else "files", src)
                        if dest.endswith("/"):
                            dest += os.path.basename(src).removesuffix(".j2")
                        if os.path.isfile(src):
                            dests[dest] = src
    return dests, names


def sha1_file(p):
    try:
        with open(p, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()
    except OSError:
        return None


def analyze_script(path, resolver, containers, sources):
    with open(path, "rb") as fh:
        raw = fh.read(512 * 1024)
    st = os.stat(path)
    info = {"path": path, "name": os.path.basename(path), "bytes": st.st_size, "mtime": int(st.st_mtime),
            "sha": hashlib.sha1(raw).hexdigest()[:12], "lang": None, "source": None,
            "invokes": [], "execs": [], "calls": [], "routes": [], "externals": [], "reads": []}
    if b"\0" in raw[:4096]:
        info["lang"] = "binary"
        return info
    text = raw.decode("utf-8", "replace")
    first = text.split("\n", 1)[0]
    info["lang"] = ("python" if "python" in first or path.endswith(".py") else
                    "shell" if re.search(r"\b(ba|a|da)?sh\b", first) or path.endswith(".sh") else "other")
    # Comments name URLs and paths too (docs links, examples); only code counts.
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))

    calls, routes, ext = {}, {}, {}
    for scheme, host, port, upath in TEXT_URL_RE.findall(code):
        h = host.lower()
        if h.endswith(OWN_DOMAIN):
            routes.setdefault(h, set()).add(norm_path(upath))
        elif is_public_host(h):
            name, cat = api_of(h)
            ext.setdefault(name, {"api": name, "category": cat, "hosts": set()})["hosts"].add(h)
        else:
            tgt = resolver.resolve(h, port or ("443" if scheme == "https" else "80"))
            if tgt:
                calls.setdefault((tgt, port), set()).add(norm_path(upath))
    info["calls"] = [{"to": t, "port": p, "paths": sorted(ps)} for (t, p), ps in calls.items()]
    info["routes"] = [{"host": h, "paths": sorted(ps)} for h, ps in routes.items()]
    # SDK clients never spell out a URL; name the API from the client call.
    for svc in re.findall(r"boto3\.(?:client|resource)\(\s*['\"]([\w-]+)", code):
        ext.setdefault("AWS " + svc, {"api": "AWS " + svc, "category": "cloud", "hosts": set()})
    if re.search(r"\brclone\b", code) and re.search(r"\br2[-\w]*:", code):
        ext.setdefault("Cloudflare R2", {"api": "Cloudflare R2", "category": "storage", "hosts": set()})
    info["externals"] = [dict(v, hosts=sorted(v["hosts"])) for v in ext.values()]
    info["execs"] = sorted({c for c in exec_targets(code) if c in containers})
    info["summary"] = _script_summary(text)

    # A Python file naming a path is usually reading it, not running it; only
    # count paths on lines that start a process.
    lines = code.splitlines()
    if info["lang"] == "python":
        lines = [l for l in lines if re.search(r"subprocess|Popen|\brun\(|\bcall\(|check_output|os\.system|execv", l)]
    body = "\n".join(lines)
    inv = set(SCRIPT_RE.findall(body))
    inv |= {os.path.normpath(os.path.join(os.path.dirname(path), r)) for r in REL_SCRIPT_RE.findall(body)}
    info["invokes"] = sorted(p for p in inv if p != path and is_script(p))
    # Data files it reads (token files, config files); the credentials source
    # links a script to the secrets rendered into these.
    info["reads"] = sorted({p for p in FILE_REF_RE.findall(code)
                            if p != path and os.path.isfile(p) and not is_script(p)})

    # Which repo file deployed it: the Ansible task whose dest is this path;
    # else an identical files/ copy; else a lone same-named candidate.
    dests, names = sources
    cands = names.get(script_stem(info["name"]), [])
    full = hashlib.sha1(raw).hexdigest() if st.st_size <= len(raw) else None
    exact = [c for c in cands if full and sha1_file(c) == full]
    info["source"] = dests.get(path) or (exact[0] if exact else (cands[0] if len(cands) == 1 else None))
    return info


SUMMARY_SKIP = re.compile(r"(?i)ansible|managed by|^!|^-\*-|coding[:=]|^usage|^\s*$|^[=#-]{3,}|^set -|copyright")


def _script_summary(text):
    """First real sentence of a script's header comment or docstring: what the job does."""
    lines = text.splitlines()[:40]
    doc = re.search(r'^\s*(?:"""|\'\'\')(.+?)(?:"""|\'\'\'|$)', "\n".join(lines), re.S | re.M)
    candidates = []
    if doc:
        candidates += doc[1].splitlines()
    candidates += [l.lstrip("#").strip() for l in lines if l.lstrip().startswith("#")]
    for l in candidates:
        l = l.strip().strip('"').strip()
        if len(l) > 12 and not SUMMARY_SKIP.search(l):
            return re.split(r"(?<=[.!?])\s", l)[0][:200]
    return None


def script_stem(name):
    return re.sub(r"(\.(py|sh))?(\.j2)?$", "", name)


def is_script(p):
    """Something cron runs, not a data file it reads or writes (tokens, .prom, logs)."""
    if not os.path.isfile(p):
        return False
    return p.endswith((".sh", ".py")) or os.access(p, os.X_OK)


def collect_scripts(out):
    resolver = Resolver(out)
    containers = {c["name"] for c in out["containers"]}
    sources = repo_sources()
    scripts, queue = {}, []
    for j in out["jobs"]:
        j["scripts"] = sorted({p for p in SCRIPT_RE.findall(j["command"]) if is_script(p)})
        queue += [(p, 0) for p in j["scripts"]]
    while queue:
        p, depth = queue.pop(0)
        if p in scripts:
            continue
        try:
            info = analyze_script(p, resolver, containers, sources)
        except OSError:
            continue
        if info["lang"] == "binary" and depth > 0:
            continue  # a tool a script happens to call (claude, trivy), not part of the job
        scripts[p] = info
        if depth < 3:
            queue += [(q, depth + 1) for q in scripts[p]["invokes"]]
    if not scripts:
        raise RuntimeError("implausible: cron runs no scripts we can read")
    out["scripts"] = list(scripts.values())
    titles, defined = _ansible_cron_tasks()
    for j in out["jobs"]:
        s0 = next((scripts[p] for p in j.get("scripts", []) if p in scripts and scripts[p].get("summary")), None)
        j["purpose"] = (s0 or {}).get("summary") or titles.get(j["name"])
    live = {j["name"] for j in out["jobs"]}
    # Defined in Ansible but absent from the live crontab: lost by an
    # out-of-band crontab edit, or switched off by a `when:` (conditional).
    out["cron_missing"] = [{"name": n, "role": d["role"], "purpose": titles.get(n), "conditional": d["conditional"]}
                           for n, d in sorted(defined.items()) if n not in live]


def _ansible_cron_tasks():
    """({cron name: task title}, {cron name: {role, conditional}}) for cron jobs Ansible keeps present."""
    titles, defined = {}, {}
    for tf in glob.glob(os.path.join(REPO, "roles", "*", "tasks", "*.yml")):
        role = tf.split("/roles/")[1].split("/")[0]
        try:
            with open(tf) as fh:
                doc = yaml.safe_load(fh)
        except Exception:
            continue
        for t in _tasks(doc):
            cr = t.get("cron") or t.get("ansible.builtin.cron")
            if not isinstance(cr, dict) or cr.get("env") in (True, "yes", "true") or not isinstance(cr.get("name"), str):
                continue
            items = t.get("loop") or t.get("with_items")
            names = [cr["name"]]
            if "{{" in cr["name"] and isinstance(items, list):
                names = [re.sub(r"\{\{\s*item\.(\w+)\s*\}\}", lambda m, it=it: str(it.get(m[1], m[0])), cr["name"])
                         for it in items if isinstance(it, dict)]
            for n in names:
                if "{{" in n:
                    continue
                titles.setdefault(n, t.get("name"))
                if str(cr.get("state", "present")) == "present":
                    defined.setdefault(n, {"role": role, "conditional": bool(t.get("when"))})
    return titles, defined


# ───────────────────────────── egress (outbound APIs) ─────────────────────────────
def collect_egress(out):
    """Who calls which outside API, from the Squid transparent proxy's log.

    Covers traffic Squid intercepts (container egress on ports 80/443). Host
    processes and anything routed around the proxy are not seen here; the
    scripts source fills in host-side calls statically.
    """
    resolver = Resolver(out)
    since = time.time() - WINDOW_DAYS * 86400

    # Container IPs change on every redeploy and vanish while a container is
    # stopped, but the log spans a week. Keep every ip -> owner seen by past
    # runs and fall back to the most recent owner when the live map misses.
    hist_path = os.path.join(out["_outdir"], "ip-history.json")
    try:
        with open(hist_path) as fh:
            hist = json.load(fh)
    except (OSError, ValueError):
        hist = {}
    now = time.time()
    for ip, cands in resolver.by_ip.items():
        who = (("Container", cands[0]["name"]) if len(cands) == 1 or not cands[0]["pod"]
               else ("Pod", cands[0]["pod"]))
        hist.setdefault(ip, {})["|".join(who)] = now
    hist = {ip: {k: t for k, t in owners.items() if t > now - 30 * 86400} for ip, owners in hist.items()}
    hist = {ip: o for ip, o in hist.items() if o}
    with open(hist_path + ".tmp", "w") as fh:
        json.dump(hist, fh)
    os.replace(hist_path + ".tmp", hist_path)

    def owner(ip):
        o = hist.get(ip)
        return tuple(max(o, key=o.get).split("|", 1)) if o else ("Unresolved", "unresolved")

    agg, lines = {}, 0
    for e in read_json_log(SQUID_LOGS, since - 86400):
        try:
            ep = float(e.get("epoch") or 0)
        except ValueError:
            continue
        if ep < since:
            continue
        lines += 1
        sni = e.get("sni") or ""
        host = (sni if sni not in ("", "-") else e.get("domain") or "").split(":")[0].lower()
        if not host or host.endswith(OWN_DOMAIN):
            continue
        try:
            ipaddress.ip_address(host)
            name, cat, host = "Unidentified (no SNI)", "unidentified", "(ip)"
        except ValueError:
            name, cat = api_of(host)
        who = owner(e.get("src_ip") or "")
        a = agg.setdefault((who, name), {"category": cat, "requests": 0, "bytes": 0, "denied": 0,
                                         "hosts": set(), "last": 0})
        a["requests"] += 1
        a["bytes"] += int(e.get("bytes") or 0)
        a["denied"] += "DENIED" in (e.get("hierarchy") or "")
        a["hosts"].add(host)
        a["last"] = max(a["last"], ep)
    if not lines:
        raise RuntimeError(f"implausible: no Squid log lines in the last {WINDOW_DAYS} days")
    out["egress"] = [{"who_label": w[0], "who": w[1], "api": name, "category": a["category"],
                      "hosts": sorted(a["hosts"]), "requests": a["requests"], "bytes": a["bytes"],
                      "denied": a["denied"],
                      "last_seen": datetime.fromtimestamp(a["last"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
                     for (w, name), a in sorted(agg.items(), key=lambda kv: -kv[1]["requests"])]


# ───────────────────────────── ingress (internal API usage) ─────────────────────────────
STATIC_EXT = re.compile(r"\.(js|mjs|css|map|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|html?|txt|xml|webmanifest)$", re.I)
API_TOP_N = 50      # paths kept per router
API_MIN_OK = 3      # successful hits needed to count as a real API (drops scanner 404 noise)


def collect_ingress(out):
    """Which API paths behind each Traefik router are actually used, from its access log."""
    since = time.time() - WINDOW_DAYS * 86400
    skip = {r["router"] for r in out["routes"]
            if "honeypot" in r["router"] or any(b.get("to") == "honeypot" for b in r["backends"])}
    agg, usage, lines = {}, {}, 0
    for e in read_json_log(TRAEFIK_LOGS, since - 86400):
        t = e.get("StartUTC") or e.get("time") or ""
        try:
            ts = calendar.timegm(time.strptime(t[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            continue
        if ts < since:
            continue
        lines += 1
        router = (e.get("RouterName") or "").split("@")[0]
        if not router or router in skip:
            continue
        status = int(e.get("DownstreamStatus") or 0)
        u = usage.setdefault(router, {"hits": 0, "e4": 0, "e5": 0})
        u["hits"] += 1
        u["e4"] += 400 <= status < 500
        u["e5"] += status >= 500
        path = norm_path(e.get("RequestPath"))
        if STATIC_EXT.search(path):
            continue
        a = agg.setdefault((router, e.get("RequestMethod") or "?", path),
                           {"hits": 0, "ok": 0, "e4": 0, "e5": 0, "durs": [], "last": 0})
        a["hits"] += 1
        a["ok"] += status < 400
        a["e4"] += 400 <= status < 500
        a["e5"] += status >= 500
        a["last"] = max(a["last"], ts)
        if len(a["durs"]) < 5000:
            a["durs"].append((e.get("Duration") or 0) / 1e6)
    if not lines:
        raise RuntimeError(f"implausible: no Traefik access log lines in the last {WINDOW_DAYS} days")
    per_router = {}
    for (router, method, path), a in agg.items():
        if a["ok"] >= API_MIN_OK:
            per_router.setdefault(router, []).append((router, method, path, a))
    paths = []
    for rows in per_router.values():
        for router, method, path, a in sorted(rows, key=lambda r: -r[3]["hits"])[:API_TOP_N]:
            d = sorted(a["durs"])
            paths.append({"key": f"{router} {method} {path}", "router": router, "method": method, "path": path,
                          "hits": a["hits"], "errors_4xx": a["e4"], "errors_5xx": a["e5"],
                          "p95_ms": round(d[int(len(d) * .95) - 1 if len(d) > 1 else 0], 1) if d else None,
                          "last_seen": datetime.fromtimestamp(a["last"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    out["api_paths"] = paths
    out["route_usage"] = [{"router": r, "hits": u["hits"], "errors_4xx": u["e4"], "errors_5xx": u["e5"]}
                          for r, u in usage.items()]


def merge_apis(out):
    """One entry per outside API, from whichever of egress/scripts succeeded."""
    apis = {}
    if out["sources"].get("egress", {}).get("ok"):
        for e in out.get("egress", []):
            a = apis.setdefault(e["api"], {"name": e["api"], "category": e["category"], "hosts": set(),
                                           "requests": 0, "src": "egress"})
            a["hosts"] |= set(e["hosts"])
            a["requests"] += e["requests"]
    if out["sources"].get("scripts", {}).get("ok"):
        for s in out.get("scripts", []):
            for x in s["externals"]:
                a = apis.setdefault(x["api"], {"name": x["api"], "category": x["category"], "hosts": set(),
                                               "requests": 0, "src": "scripts"})
                a["hosts"] |= set(x["hosts"])
    out["apis"] = [dict(a, hosts=sorted(a["hosts"])) for a in apis.values()]


# ───────────────────────────── credentials ─────────────────────────────
# Which secret is used where, what it unlocks, and whether it is healthy.
# Inputs: vault-index.json (written at deploy time: key names + keyed
# fingerprints, never values), the roles' code (declared use), and live
# container env (observed use, fingerprinted here with the same key). The
# fingerprint key and history stay on this host; the graph only ever gets
# names, places, dates and flags.
HERE = os.environ.get("INFRA_GRAPH_DIR") or os.path.dirname(os.path.abspath(__file__))
VAULT_INDEX = os.path.join(HERE, "vault-index.json")
FP_KEY = os.path.join(HERE, ".fp-key")

# Vault keys that hold a secret (vs ids, urls, emails, coordinates...).
SECRET_NAME_RE = re.compile(r"(?i)(key|token|secret|passw|pass$|salt|auth|_pat$|license|dsn|credential|sid$)")
NOT_SECRET_RE = re.compile(r"(?i)(_ids?$|url$|uri$|email$|_lat$|_lon$|name$|domain|bucket|subnet|dns$|^ansible_user$"
                           r"|user(name)?$|zone_id|host$|port$|from$|voice_id|avatar_id|look_id|project$|chat_id"
                           r"|phone|fingerprint$|key_id$|key_type$|key_email$|key_name$|account_id$)")
ENV_SECRET_RE = re.compile(r"(?i)(token|secret|passw|api_?key|auth_?key|private_key|credential|_dsn$|_pat$)")
URL_PASSWORD_RE = re.compile(r"^[a-z][a-z0-9+.-]*://[^:/@\s]+:([^@\s]+)@", re.I)

# What a key unlocks: (name pattern, graph label, node name). First match wins.
GRANTS = [
    (r"^cloudflare_tunnel_token$", "External", "Cloudflare Edge"),
    (r"^cloudflare_|^crowdsec_cloudflare_token$", "External", "Cloudflare API"),
    (r"^r2_|^cf_s3", "External", "Cloudflare R2"),
    (r"^telegram_bot2?_token$|^telegram_webhook_secret$", "External", "api.telegram.org"),
    (r"^openai_api_key$", "External", "OpenAI"), (r"^anthropic_api_key$", "External", "Anthropic"),
    (r"gemini_api_key$", "External", "Google Gemini API"), (r"^openrouter_api_key$", "External", "OpenRouter"),
    (r"^groq_api_key$", "External", "Groq"), (r"^cohere_api_key$", "External", "Cohere"),
    (r"^xai_api_key$", "External", "xAI"), (r"^deepseek_api_key$", "External", "DeepSeek"),
    (r"^resend_api_key$|^authentik_smtp_password$", "External", "Resend SMTP"),
    (r"^maxmind_", "External", "MaxMind"), (r"abuseipdb", "External", "abuseipdb.com"),
    (r"^a?i?s{1,2}tream_api_key$|^aistream_api_key$", "External", "aisstream.io"),
    (r"wigle", "External", "WiGLE API"), (r"^vault_larouge_look_reader_", "External", "AWS dynamodb"),
    (r"^ibkr_", "External", "IBKR"), (r"^twillio_", "External", "Twilio"),
    (r"^heygen_", "External", "HeyGen"), (r"^elevenlabs_", "External", "ElevenLabs"),
    (r"^livekit_|^liveavatar_", "External", "LiveKit"), (r"^runpod_", "External", "RunPod"),
    (r"^vast_", "External", "Vast.ai"), (r"^serper_", "External", "Serper"), (r"^brave_", "External", "Brave Search"),
    (r"stripe", "External", "Stripe"), (r"posthog", "External", "PostHog"),
    (r"^github_runner_", "External", "GitHub"), (r"tailscale_authkey$", "External", "Tailscale"),
    (r"^gdrive_", "External", "Google Docs/Drive API"), (r"^alpha_vantage", "External", "Alpha Vantage"),
    (r"^google_maps|maps_api_key$", "External", "Google Maps"), (r"cesium_ion", "External", "Cesium ion"),
    (r"^acled|_acled_", "External", "ACLED"), (r"firms_map|^firma_map", "External", "NASA FIRMS"),
    (r"^nuitee", "External", "Nuitee"),
    # Internal services: the container whose access the secret controls.
    (r"^ai_stack_postgres_password$", "Container", "ai-stack-postgres"),
    (r"^pg_\w+_password$|^postgres_password$", "Container", "postgres"),
    (r"^neo4j_password$", "Container", "neo4j-db"), (r"^redis_password$", "Container", "redis"),
    (r"^authentik_", "Container", "authentik-server"),
    (r"^litellm_|^openwebui_openai_api_keys?$", "Container", "litellm"),
    (r"^openwebui_|^searxng_secret_key$", "Container", "open-webui"),
    (r"^grafana_reports_auth_token$", "Container", "grafana-reports"),
    (r"^grafana_|^image_renderer_token$", "Container", "grafana"),
    (r"^telegram_gateway_auth_token$", "Container", "telegram-gateway"),
    (r"^session_ingest_token$|^ops_session_secret$", "Container", "ops-dashboard"),
    (r"^ib_mcp_auth_token$", "Container", "ib-mcp-server"),
    (r"^session_recall_mcp_auth_token$", "Container", "session-recall-mcp"),
    (r"^timeline_context_api_key$", "Container", "timeline-context-api"),
    (r"^timeline_api_key$", "Container", "timeline-api"),
    (r"^crowdsec_bouncer|^threat_map_crowdsec_key$", "Container", "crowdsec"),
    (r"^otel_ingest_token$", "Container", "alloy"),
    (r"^pg_catalog_api_password$|^marketplace_", "Container", "catalog-api"),
    (r"^portainer_password$", "Container", "portainer"),
]


def is_secret_name(name):
    return bool(SECRET_NAME_RE.search(name)) and not NOT_SECRET_RE.search(name)


def grant_of(name):
    for pat, label, target in GRANTS:
        if re.search(pat, name, re.I):
            return label, target
    return None, None


def _fp(value, key):
    return hashlib.sha256((value + key).encode()).hexdigest()[:16]


JINJA_EXPR_RE = re.compile(r"\{\{(.*?)\}\}", re.S)
IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")


def vault_refs(text, names):
    """Vault key names used inside {{ ... }} expressions in text."""
    refs = set()
    for expr in JINJA_EXPR_RE.findall(text or ""):
        refs |= {i for i in IDENT_RE.findall(expr) if i in names}
    return refs


def role_defaults(role_dir):
    try:
        with open(os.path.join(role_dir, "defaults", "main.yml")) as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


def resolve_literal(value, defaults):
    """A templated path's literal value, when it can be known statically:
    "{{ x | default('/a/b') }}" -> "/a/b"; "{{ role.key }}" -> the role default.
    Anything else stays unresolved (None)."""
    if not isinstance(value, str):
        return None
    if "{{" not in value:
        return value
    m = re.fullmatch(r"\{\{\s*([\w.]+)\s*(?:\|\s*default\(\s*['\"]([^'\"]+)['\"]\s*\))?\s*\}\}", value.strip())
    if not m:
        return None
    node = defaults
    for part in m[1].split("."):
        node = node.get(part) if isinstance(node, dict) else None
    if isinstance(node, str) and "{{" not in node:
        return node
    return m[2]


def declared_uses(names):
    """(env injections, rendered files, files referencing each key) from the roles' code."""
    env_uses, renders, mentions = [], {}, {}
    dests, _ = repo_sources()
    src_to_dest = {}
    for dest, src in dests.items():
        src_to_dest.setdefault(src, []).append(dest)
    roles = os.path.join(REPO, "roles")
    if not os.path.isdir(roles):
        return env_uses, renders, mentions
    word = re.compile(r"\b(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")\b") if names else None
    for dirpath, dirs, files in os.walk(roles):
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__")]
        for f in files:
            p = os.path.join(dirpath, f)
            if not re.search(r"\.(ya?ml|j2|sh|py|conf|cfg|ini|json|alloy|toml)$", f):
                continue
            try:
                with open(p, errors="replace") as fh:
                    text = fh.read(2_000_000)
            except OSError:
                continue
            rel = p.replace(REPO + "/", "")
            if word:
                for n in set(word.findall(text)):
                    mentions.setdefault(n, set()).add(rel)
            if "/templates/" in p:
                for n in vault_refs(text, names):
                    for dest in src_to_dest.get(p, []):
                        renders.setdefault(n, set()).add(dest)
            if "/tasks/" in p and f.endswith((".yml", ".yaml")):
                try:
                    doc = yaml.safe_load(text)
                except Exception:
                    continue
                defaults = role_defaults(os.path.dirname(os.path.dirname(p)))
                for t in _tasks(doc):
                    pc = t.get("containers.podman.podman_container") or t.get("podman_container")
                    if isinstance(pc, dict) and isinstance(pc.get("name"), str) and "{{" not in pc["name"] \
                            and isinstance(pc.get("env"), dict):
                        for env_key, v in pc["env"].items():
                            for n in vault_refs(str(v), names):
                                env_uses.append({"container": pc["name"], "env": str(env_key), "name": n})
                    for mod in ("copy", "ansible.builtin.copy"):
                        a = t.get(mod)
                        dest = resolve_literal(a.get("dest"), defaults) if isinstance(a, dict) else None
                        if isinstance(a, dict) and isinstance(a.get("content"), str) and dest:
                            for n in vault_refs(a["content"], names):
                                renders.setdefault(n, set()).add(dest)
    return env_uses, renders, mentions


def collect_creds(out):
    with open(VAULT_INDEX) as fh:
        index = json.load(fh)
    with open(FP_KEY) as fh:
        key = fh.read().strip()
    if not index or not key:
        raise RuntimeError("implausible: empty vault index or fingerprint key")

    by_name = {}
    for e in index:
        by_name.setdefault(e["name"], []).append(e)
    secrets = {n for n in by_name if is_secret_name(n)}
    # Match against every key, then promote keys whose value turns up where a
    # secret lives (a secret-looking env var, or a token/key/password file):
    # usage beats naming (e.g. cloudflare_access_metrics holds a token).
    fp_owner = {}
    for n, entries in by_name.items():
        for e in entries:
            if not e["empty"]:
                fp_owner.setdefault(e["fp"], set()).add(n)
    SECRET_FILE_RE = re.compile(r"(?i)(token|key|secret|passw|cred|\.env$|rclone\.conf$)")
    for c in out["containers"]:
        for k, v in env_of(c).items():
            if v and ENV_SECRET_RE.search(k):
                for val in [v] + URL_PASSWORD_RE.findall(v):
                    secrets |= fp_owner.get(_fp(val, key), set())
    for sc in out.get("scripts", []):
        for path in sc.get("reads", []):
            if SECRET_FILE_RE.search(os.path.basename(path)):
                try:
                    if os.path.getsize(path) <= 65536:
                        with open(path, errors="replace") as fh:
                            secrets |= fp_owner.get(_fp(fh.read().strip(), key), set())
                except OSError:
                    pass
    fp_owner = {fp: ns & secrets for fp, ns in fp_owner.items() if ns & secrets}

    # Observed: fingerprint every live env value (and passwords inside URLs).
    observed = []      # {container, env, fp, names}
    unmanaged = []     # secret-looking env values that match no vault key
    for c in out["containers"]:
        for k, v in env_of(c).items():
            cands = [v] + URL_PASSWORD_RE.findall(v)
            hits = set()
            for val in cands:
                if val:
                    hits |= fp_owner.get(_fp(val, key), set())
            if hits:
                observed.append({"container": c["name"], "env": k, "fp": _fp(v, key), "names": sorted(hits)})
            elif ENV_SECRET_RE.search(k) and v and not v.startswith(("/", "http://", "https://")) and len(v) >= 12:
                unmanaged.append({"container": c["name"], "env": k})

    env_decl, renders, mentions = declared_uses(set(by_name))
    scripts = out.get("scripts", [])

    # Observed in files: token and config files that scripts read. Fingerprint
    # the whole content and each "key = value" / "KEY=value" value, so a file
    # links to its secret however Ansible wrote it (indirect lookups, templated
    # destinations). Small text files only.
    file_hits = {}
    for path in sorted({f for sc in scripts for f in sc.get("reads", [])}):
        try:
            if os.path.getsize(path) > 65536:
                continue
            with open(path, errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        cands = [text.strip()] + [m.strip().strip("\"'") for m in
                                  re.findall(r"(?m)^\s*[\w.-]+\s*[=:]\s*(.+?)\s*$", text)]
        for val in cands:
            if len(val) >= 8:
                for n in fp_owner.get(_fp(val, key), ()):
                    file_hits.setdefault(n, set()).add(path)

    # Rotation history: when did each key's current fingerprint first appear?
    hist_path = os.path.join(out["_outdir"], "creds-state.json")
    try:
        with open(hist_path) as fh:
            hist = json.load(fh)
    except (OSError, ValueError):
        hist = {}
    run = out["run"]

    creds = []
    for n in sorted(secrets):
        entries = by_name[n]
        main = next((e for e in entries if e["file"] == "vault.yml"), entries[0])  # root vault wins in site.yml
        fps = {e["fp"] for e in entries if not e["empty"]}
        h = hist.setdefault(n, {})
        if not main["empty"]:
            h.setdefault(main["fp"], run)
        containers = {}
        for o in observed:
            if n in o["names"]:
                containers.setdefault(o["container"], {"env": o["env"], "observed": True, "matches_vault": True})
        for d in env_decl:
            if d["name"] == n:
                live = next((o for o in observed if o["container"] == d["container"] and o["env"] == d["env"]), None)
                slot = containers.setdefault(d["container"], {"env": d["env"], "observed": False})
                slot["declared"] = True
                if live is None:
                    live_val = next((env_of(c).get(d["env"]) for c in out["containers"] if c["name"] == d["container"]), None)
                    # Declared from this key but the running value matches nothing in the vault.
                    slot["matches_vault"] = False if live_val else None
        files = sorted(set(renders.get(n, [])) | file_hits.get(n, set()))
        users = sorted({s["path"] for s in scripts
                        if s["path"] in files or set(s.get("reads", [])) & set(files)})
        label, target = grant_of(n)
        others = sorted(set().union(*(fp_owner.get(f, set()) for f in fps)) - {n}) if fps else []
        mentioned = sorted(m for m in mentions.get(n, []) if "vault" not in m)
        creds.append({
            "name": n,
            "vault_files": sorted({e["file"] for e in entries}),
            "duplicate_in_file": any(e["occurrences"] > 1 for e in entries),
            "conflict": len(fps) > 1,                 # same key, different values in the two vault files
            "empty": all(e["empty"] for e in entries),
            "reused_as": others,                      # the same secret under other names
            "rotated_at": h.get(main["fp"]) if not main["empty"] else None,
            "tracking_since": min(h.values()) if h else run,
            "containers": [{"container": c, **v} for c, v in sorted(containers.items())],
            "drift": any(v.get("matches_vault") is False for v in containers.values()),
            "files": files,
            "scripts": users,
            "grants_label": label, "grants": target,
            "referenced_in": mentioned[:20],
            # Nothing in this repo or on this host uses it. It may still be used
            # off-box (the laptop, another project), so this is a prompt to
            # check, not proof it is dead.
            "unreferenced": not containers and not files and not mentioned,
        })
    tmp = hist_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(hist, fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, hist_path)

    out["credentials"] = creds
    out["unmanaged_secrets"] = unmanaged
    out["vault_other_keys"] = sorted(set(by_name) - secrets)


# ───────────────────────────── exposure (public endpoints) ─────────────────────────────
# Everything reachable from outside this box, and what guards it:
#   ports      host listeners, judged against the real iptables/ip6tables INPUT
#              rules for a NEW connection from the internet, the tailnet and
#              the container network;
#   hostnames  Traefik routes, joined with Cloudflare DNS/tunnel and the
#              Cloudflare Access app that covers them (cf-exposure.json,
#              exported at deploy time: no secrets, no addresses);
#   workers    Cloudflare Workers and their routes.
CF_EXPOSURE = os.path.join(HERE, "cf-exposure.json")
TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
# Who is knocking, for each audience: (iface, source address).
AUDIENCES = {
    "internet": ("eth0", {"4": "203.0.113.5", "6": "2001:db8::5"}),
    "tailnet": ("tailscale0", {"4": "100.100.100.100", "6": "fd7a:115c:a1e0::1"}),
    "containers": ("podman1", {"4": "10.89.0.250", "6": "fd00::250"}),
}
AUTH_MW_RE = re.compile(r"(?i)auth|bearer|basic|forward|token|oidc|access")


def _listeners():
    rows = []
    for proto, flag in (("tcp", "-tlnp"), ("udp", "-ulnp")):
        for line in run(["netstat", flag]).splitlines():
            parts = line.split()
            if len(parts) < 4 or not parts[0].startswith(proto):
                continue
            addr, _, port = parts[3].rpartition(":")
            prog = next((p for p in parts[4:] if re.match(r"^\d+/", p)), "")
            rows.append({"proto": proto, "addr": addr.strip("[]"), "port": int(port),
                         "process": prog.split("/", 1)[-1].rstrip(":") if prog else ""})
    seen, uniq = set(), []
    for r in rows:
        k = (r["proto"], r["addr"], r["port"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def _bind_scope(addr):
    a = addr.split("%")[0]
    if a in ("0.0.0.0", "::", "*", ""):
        return "all"
    try:
        ip = ipaddress.ip_address(a)
    except ValueError:
        return "unknown"
    if ip.is_loopback:
        return "loopback"
    if ip in (TAILNET_V4 if ip.version == 4 else TAILNET_V6):
        return "tailnet"
    return "private" if ip.is_private else "public"


def _fw(cmd):
    """INPUT and every chain it jumps into. `iptables -S` over ALL chains fails
    here (a netavark nftables rule iptables cannot print), so read chain by
    chain and skip any single unreadable one."""
    policies, chains, todo = {}, {}, ["INPUT"]
    builtin = {"ACCEPT", "DROP", "REJECT", "RETURN", "LOG", "MARK", "CONNMARK", "MASQUERADE", "DNAT", "SNAT"}
    while todo:
        name = todo.pop()
        if name in chains:
            continue
        chains[name] = []
        try:
            text = run([cmd, "-S", name])
        except RuntimeError:
            if name == "INPUT":
                raise
            continue
        for line in text.splitlines():
            t = line.split()
            if len(t) >= 3 and t[0] == "-P":
                policies[t[1]] = t[2]
            elif len(t) >= 2 and t[0] == "-A":
                chains[name].append(t[2:])
                tgt, _ = _opt(t, "-j")
                if tgt and tgt not in builtin and tgt not in chains:
                    todo.append(tgt)
    return policies, chains


def _opt(tokens, name):
    """(value, negated) of an iptables option in a rule's token list."""
    for i, tok in enumerate(tokens):
        if tok == name and i + 1 < len(tokens):
            return tokens[i + 1], i > 0 and tokens[i - 1] == "!"
    return None, False


def _fw_verdict(fw, proto, port, iface, src, chain="INPUT", depth=0):
    """'accept' / 'drop' for a NEW connection, following jumps into custom chains."""
    policies, chains = fw
    if depth > 8:
        return None
    for r in chains.get(chain, []):
        if "--ctstate" in r or "--state" in r:
            continue  # established/related only: not a new inbound connection
        p, pneg = _opt(r, "-p")
        if p and ((p == proto) == pneg):
            continue
        dport, _ = _opt(r, "--dport") if "--dport" in r else _opt(r, "--dports")
        if dport:
            ports = set()
            for part in dport.split(","):
                lo, _, hi = part.partition(":")
                ports |= set(range(int(lo), int(hi or lo) + 1)) if lo.isdigit() else set()
            if port not in ports:
                continue
        i, ineg = _opt(r, "-i")
        if i:
            hit = iface.startswith(i[:-1]) if i.endswith("+") else iface == i
            if hit == ineg:
                continue
        s, sneg = _opt(r, "-s")
        if s:
            try:
                hit = ipaddress.ip_address(src) in ipaddress.ip_network(s, strict=False)
            except ValueError:
                hit = False
            if hit == sneg:
                continue
        target, _ = _opt(r, "-j")
        if target == "ACCEPT":
            return "accept"
        if target in ("DROP", "REJECT"):
            return "drop"
        if target == "RETURN":
            return None
        if target in chains:
            v = _fw_verdict(fw, proto, port, iface, src, target, depth + 1)
            if v:
                return v
    return policies.get("INPUT", "ACCEPT").lower() if chain == "INPUT" else None


def _access_for(host, path, apps):
    """Most specific Cloudflare Access app covering host/path, and its verdict."""
    best, rank = None, -1
    for a in apps:
        dom_host, _, dom_path = (a.get("domain") or "").partition("/")
        if dom_host == host:
            r = 2
        elif dom_host.startswith("*.") and host.endswith(dom_host[1:]):
            r = 1
        else:
            continue
        if dom_path:
            if not (path or "/").lstrip("/").startswith(dom_path):
                continue
            r += 2
        if r > rank:
            best, rank = a, r
    if not best:
        return "none", None
    pol = set(best.get("policies") or [])
    verdict = ("bypass" if "bypass" in pol else "identity" if "allow" in pol
               else "service-token" if "non_identity" in pol else "deny" if pol == {"deny"} else "unknown")
    return verdict, best.get("domain")


def collect_exposure(out):
    with open(CF_EXPOSURE) as fh:
        cf = json.load(fh)
    fw4, fw6 = _fw("iptables"), _fw("ip6tables")
    eps = []

    # Ports on the host: one row per (proto, port, process, bind scope, IP
    # version); a resolver bound on several bridge addresses is one service.
    grouped = {}
    for l in _listeners():
        scope = _bind_scope(l["addr"])
        if scope == "loopback":
            continue
        k = (l["proto"], l["port"], l["process"], scope, ":" in l["addr"])
        grouped.setdefault(k, dict(l, addresses=0))["addresses"] += 1
    for l in grouped.values():
        scope = _bind_scope(l["addr"])
        v6 = ":" in l["addr"]
        fam = "6" if v6 else "4"
        fw = fw6 if v6 else fw4
        reach = []
        for aud, (iface, srcs) in AUDIENCES.items():
            src = srcs[fam]
            if scope == "tailnet" and aud != "tailnet":
                continue
            if scope == "private" and aud == "internet":
                continue
            if _fw_verdict(fw, l["proto"], l["port"], iface, src) == "accept":
                reach.append(aud)
        flags = []
        if "internet" in reach and l["process"] not in ("sshd", "tailscaled"):
            flags.append("reachable from the internet")
        eps.append({"key": f'{l["proto"]}/{l["port"]}@{"v6" if v6 else "v4"}:{scope}', "kind": "port",
                    "name": f'{l["process"] or "?"} {l["proto"]}/{l["port"]} (IPv{fam}, {scope}' + (f', {l["addresses"]} addresses' if l["addresses"] > 1 else "") + ")",
                    "proto": l["proto"], "port": l["port"],
                    "process": l["process"], "bind": scope, "ip_version": int(fam), "reachable": reach,
                    "access": None, "via": "direct", "middlewares": [], "route_key": None, "flags": flags})
    for chain_name, fw in (("v4", fw4), ("v6", fw6)):
        for r in fw[1].get("INPUT", []) + fw[1].get("FW6-INPUT", []):
            dport, _ = _opt(r, "--dport")
            s, _ = _opt(r, "-s")
            i, _ = _opt(r, "-i")
            if dport and dport.isdigit() and not s and not i and _opt(r, "-j")[0] == "ACCEPT":
                port = int(dport)
                if not any(e["kind"] == "port" and e["port"] == port and e["ip_version"] == (6 if chain_name == "v6" else 4)
                           and e["bind"] in ("all", "public") for e in eps):
                    eps.append({"key": f'fw-open/{port}@{chain_name}', "kind": "port", "name": f"firewall-open {port} (IPv{6 if chain_name == 'v6' else 4}, nothing listening)",
                                "proto": "tcp", "port": port, "process": "", "bind": "none", "ip_version": 6 if chain_name == "v6" else 4,
                                "reachable": [], "access": None, "via": "direct", "middlewares": [], "route_key": None,
                                "flags": ["firewall allows a port nothing listens on"]})

    # Hostnames behind Cloudflare.
    dns = cf.get("dns", [])
    tunnel_hosts = {i.get("hostname") for t in cf.get("tunnels", []) for i in t.get("ingress", []) if i.get("hostname")}
    def dns_for(host):
        exact = [d for d in dns if d["name"] == host and d["type"] in ("A", "AAAA", "CNAME")]
        if exact:
            return exact
        zone = ".".join(host.split(".")[1:])
        return [d for d in dns if d["name"] == f"*.{zone}" and d["type"] in ("A", "AAAA", "CNAME")]
    for rt in out.get("routes", []):
        host = rt.get("host")
        if not host:
            continue
        recs = dns_for(host)
        if any(h == host or (h.startswith("*.") and host.endswith(h[1:])) for h in tunnel_hosts) or \
                any((d.get("target") or "").endswith("cfargotunnel.com") for d in recs):
            via = "cloudflare-tunnel"
        elif any(d["proxied"] for d in recs):
            via = "cloudflare-proxy"
        elif recs:
            via = "dns-direct"
        else:
            via = "not-in-dns"
        access, app = _access_for(host, rt.get("path"), cf.get("access_apps", []))
        mws = rt.get("middlewares", [])
        flags = []
        if via in ("cloudflare-tunnel", "cloudflare-proxy") and access in ("none", "bypass") \
                and not any(AUTH_MW_RE.search(m) for m in mws):
            flags.append("public: relies on the app's own sign-in")
        if via.startswith("cloudflare") and not mws:
            flags.append("no Traefik middlewares at all (no CrowdSec, rate limit or security headers)")
        if any(d["to_this_host"] and not d["proxied"] for d in recs):
            flags.append("DNS points straight at this host (reveals origin, skips Cloudflare)")
        # NOTE: Traefik's internal-only allowlist is the container network
        # itself, which includes cloudflared, so it does NOT stop tunnel
        # traffic. It is listed but never counted as protection.
        eps.append({"key": f'https://{host}{rt.get("path") or ""}#{rt["router"]}', "kind": "hostname",
                    "name": f'{host}{rt.get("path") or ""}', "host": host, "path": rt.get("path"), "proto": "https",
                    "port": 443, "process": "", "bind": None, "ip_version": None,
                    "reachable": ["internet"] if via.startswith("cloudflare") else [],
                    "access": access, "access_app": app, "via": via, "middlewares": mws,
                    "route_key": rt["key"], "flags": flags})

    for w in cf.get("workers", []):
        routes = [r["pattern"] for r in cf.get("worker_routes", []) if r.get("script") == w]
        eps.append({"key": f"worker/{w}", "kind": "worker", "name": w, "proto": "https", "port": 443, "process": "",
                    "bind": None, "ip_version": None, "reachable": ["internet"], "access": None, "via": "cloudflare-worker",
                    "middlewares": [], "route_key": None, "routes": routes, "flags": []})
    out["public_endpoints"] = eps
    out["cf_exported_at"] = cf.get("exported_at")


# ───────────────────────────── pipelines (CI/CD) ─────────────────────────────
# Every CI/CD definition in the workspace and whether it can actually run.
# A GitHub workflow only runs in a repo pushed to GitHub, so a definition in a
# plain copy of upstream code (n8n, bolt.diy, fabric...) is inert. Status for
# runnable GitHub pipelines comes from the public API (private repos need a
# token this host does not have: reported as unknown, not as healthy).
WORKSPACE_ROOTS = ["/workspace/vscode-projects", "/workspace/pycharm-projects"]
GITHUB_OWNER = "Kwaku9"
PIPELINE_SKIP_DIRS = {"node_modules", ".worktrees", "worktrees", "__pycache__", ".venv", "venv", "dist", "build"}
DEPLOY_HINTS = [
    (r"ansible-playbook", "ansible"), (r"\bssh\b|\bscp\b|\brsync\b", "ssh"),
    (r"docker (push|buildx)|podman push|ghcr\.io", "container-registry"),
    (r"wrangler (deploy|publish)|cloudflare/wrangler-action", "cloudflare-workers"),
    (r"gcloud (run|app|functions) deploy|google-github-actions/deploy", "google-cloud"),
    (r"npm publish|pypi|twine upload", "package-registry"), (r"gh release|softprops/action-gh-release", "github-release"),
    (r"eas (build|submit|update)", "expo-eas"), (r"kubectl|helm ", "kubernetes"),
]


def _repo_of(path):
    d = path if os.path.isdir(path) else os.path.dirname(path)
    while d and d != "/":
        if os.path.exists(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return None


def _origin(repo):
    try:
        url = run(["git", "-C", repo, "remote", "get-url", "origin"], timeout=10).strip()
    except Exception:
        return None
    # github.com URLs and SSH host aliases (git@github-marketplace:Owner/repo.git)
    m = re.search(r"github[\w.-]*[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
    return f"{m[1]}/{m[2]}" if m else url


def _deploy_hints(text):
    return sorted({name for pat, name in DEPLOY_HINTS if re.search(pat, text, re.I)})


def _gh_get(path):
    req = urllib.request.Request("https://api.github.com/" + path,
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "infra-graph"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _parse_pipeline(path):
    with open(path, errors="replace") as fh:
        text = fh.read(500_000)
    base = os.path.basename(path)
    p = {"file": path, "secrets": sorted(set(re.findall(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)", text))),
         "deploys": _deploy_hints(text), "triggers": [], "runner": None}
    if "/.github/workflows/" in path:
        doc = yaml.safe_load(text) or {}
        on = doc.get("on", doc.get(True))  # PyYAML reads a bare `on:` key as True
        p["triggers"] = [on] if isinstance(on, str) else sorted(on) if isinstance(on, (list, dict)) else []
        runners = {str(j.get("runs-on")) for j in (doc.get("jobs") or {}).values() if isinstance(j, dict) and j.get("runs-on")}
        p.update(system="github-actions", name=doc.get("name") or base, runner=", ".join(sorted(runners)) or None)
    elif base == "cloudbuild.yaml":
        p.update(system="google-cloud-build", name=f"cloud build ({os.path.basename(os.path.dirname(path))})",
                 triggers=["configured in Google Cloud"], runner="google-cloud-build")
    elif base == "wrangler.toml":
        name = (re.search(r'(?m)^name\s*=\s*"([^"]+)"', text) or [None, base])[1]
        routes = re.findall(r'pattern\s*=\s*"([^"]+)"', text)
        p.update(system="cloudflare-workers", name=f"worker {name}", triggers=["manual: wrangler deploy"],
                 runner="cloudflare", routes=routes, workers_dev="workers_dev = false" not in text)
    elif base == "eas.json":
        doc = json.loads(text or "{}")
        p.update(system="expo-eas", name=f"eas ({os.path.basename(os.path.dirname(path))}): " + ", ".join(sorted((doc.get("build") or {}).keys())),
                 triggers=["manual: eas build/submit"], runner="expo-eas")
    elif base in (".gitlab-ci.yml", "Jenkinsfile"):
        p.update(system="gitlab-ci" if base.startswith(".gitlab") else "jenkins", name=base)
    else:
        return None
    return p


def collect_pipelines(out):
    pipes, repos_seen = [], {}
    for root in WORKSPACE_ROOTS:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in PIPELINE_SKIP_DIRS and not d.startswith("C:")]
            if dirpath.count("/") > 9:
                dirs[:] = []
            cands = []
            if dirpath.endswith("/.github/workflows"):
                cands = [f for f in files if f.endswith((".yml", ".yaml"))]
            cands += [f for f in files if f in ("cloudbuild.yaml", "wrangler.toml", "eas.json", ".gitlab-ci.yml", "Jenkinsfile")]
            for f in cands:
                path = os.path.join(dirpath, f)
                try:
                    p = _parse_pipeline(path)
                except Exception as exc:  # a broken definition is still a finding
                    p = {"file": path, "name": os.path.basename(path), "system": "unparseable", "error": str(exc)[:120],
                         "secrets": [], "deploys": [], "triggers": [], "runner": None}
                if not p:
                    continue
                repo = _repo_of(path)
                if repo and repo not in repos_seen:
                    repos_seen[repo] = _origin(repo)
                origin = repos_seen.get(repo) if repo else None
                own = bool(origin) and origin.split("/")[0].lower() == GITHUB_OWNER.lower()
                if not repo:
                    state = "inert: not a git repo (copied code)"
                elif p["system"] == "github-actions" and not (origin and "/" in origin and "://" not in origin):
                    state = "inert: repo has no GitHub remote"
                elif p["system"] == "github-actions" and not own:
                    state = "upstream repo (not yours)"
                else:
                    state = "runnable"
                p.update(repo=repo, origin=origin, own=own or (bool(repo) and not origin), state=state)
                pipes.append(p)

    # Git hooks: local automation that runs on commit/merge.
    for repo in sorted({r for r in repos_seen} | {os.path.dirname(os.path.dirname(h)) for h in
                                                   glob.glob("/workspace/*/*/.git/hooks")}):
        for h in sorted(glob.glob(os.path.join(repo, ".git", "hooks", "*"))):
            if h.endswith(".sample") or not os.access(h, os.X_OK) or not os.path.isfile(h):
                continue
            with open(h, errors="replace") as fh:
                text = fh.read(100_000)
            calls = sorted(set(re.findall(r"(/(?:opt|usr/local|workspace)/[\w./-]+|\b[\w-]+\.(?:sh|py))", text)))[:8]
            pipes.append({"file": h, "name": f"git {os.path.basename(h)} hook", "system": "git-hook",
                          "triggers": [os.path.basename(h)], "runner": "local", "secrets": [], "deploys": _deploy_hints(text),
                          "calls": calls, "repo": repo, "origin": _origin(repo), "own": True, "state": "runnable"})

    # Run status, and your workflows in repos not checked out here.
    status_note = None
    try:
        local = {p["origin"] for p in pipes if p.get("origin")}
        own_repos = [r["full_name"] for r in _gh_get(f"users/{GITHUB_OWNER}/repos?per_page=100&type=owner")]
        for full in own_repos[:60]:
            wfs = _gh_get(f"repos/{full}/actions/workflows").get("workflows", [])
            if not wfs:
                continue
            runs = _gh_get(f"repos/{full}/actions/runs?per_page=30").get("workflow_runs", [])
            for wf in wfs:
                last = next((r for r in runs if r.get("workflow_id") == wf["id"]), None)
                match = next((p for p in pipes if p.get("origin") == full and p["file"].endswith("/" + wf["path"])), None)
                info = {"github_state": wf.get("state"),
                        "last_run": last and {"status": last["status"], "conclusion": last["conclusion"],
                                              "event": last["event"], "at": last["created_at"]}}
                if match:
                    match.update(info)
                elif full not in local or not any(p["file"].endswith("/" + wf["path"]) for p in pipes):
                    pipes.append({"file": f"github:{full}/{wf['path']}", "name": wf.get("name") or wf["path"],
                                  "system": "github-actions", "triggers": [], "runner": None, "secrets": [], "deploys": [],
                                  "repo": None, "origin": full, "own": True,
                                  "state": "runnable (GitHub only, not checked out here)", **info})
    except Exception as exc:  # rate limit or no network: definitions still count
        status_note = f"GitHub status unavailable: {exc}"[:160]
    if not pipes:
        raise RuntimeError("implausible: no pipeline definitions found")
    out["pipelines"] = pipes
    out["pipelines_note"] = status_note


# ───────────────────────────── alert rules ─────────────────────────────
# What each vmalert / Grafana rule watches and where it pages, so anything
# nobody is alerted about stands out. Rules are written against METRICS, so a
# rule's targets are worked out from the metric families in its expression;
# `up{job=...}` goes through VictoriaMetrics' scrape config to containers.
VMALERT_CONTAINER = "vmalert"
VM_CONTAINER = "victoriametrics"
# metric-name pattern -> (label, target). Target "*" = every container.
METRIC_TARGETS = [
    (r"^(podman_container_|container:)", "Container", "*"),
    (r"^pg_", "Container", ["postgres", "ai-stack-postgres", "authentik-postgres"]),
    (r"^neo4j_collector_", "ScheduledJob", "neo4j metrics"),
    (r"^neo4j_", "Container", "neo4j-db"),
    (r"^redis_", "Container", "redis"),
    (r"litellm", "Container", "litellm"),
    (r"^cloudflared_", "Container", "cloudflared"),
    (r"^traefik", "Container", "traefik"),
    (r"^webui_", "Container", "open-webui"),
    (r"^otelcol_", "Container", "alloy"),
    (r"^squid_", "Host", None),
    (r"^vps_backup_", "ScheduledJob", "vps-daily-backup"),
    (r"^trivy_", "ScheduledJob", "trivy-scan-metrics"),
    (r"^honeypot_evidence", "ScheduledJob", "honeypot evidence export"),
    (r"^honeypot_", "Container", "honeypot"),
    (r"^catalog_api_", "Container", "catalog-api"),
    (r"^crowdsec_cloudflare_", "ScheduledJob", "crowdsec-cloudflare-sync"),
    (r"^crowdsec_|^cs_", "Container", "crowdsec"),
    (r"^(instance:node_|node_)", "Host", None),
    (r"^authentik_", "Container", "authentik-server"),
    (r"^infra_graph_", "ScheduledJob", "infra-graph-sync"),
]
PROMQL_WORDS = {"sum", "rate", "increase", "absent", "avg_over_time", "max_over_time", "min_over_time", "count", "by",
                "on", "and", "or", "unless", "without", "clamp_min", "clamp_max", "histogram_quantile", "time", "max",
                "min", "avg", "topk", "bottomk", "irate", "delta", "deriv", "label_replace", "abs", "ignoring",
                "group_left", "group_right", "bool", "offset", "count_over_time", "sum_over_time", "vector", "scalar",
                "le", "le_", "inf"}


def _expr_metrics(expr):
    """Metric names used in a PromQL/MetricsQL expression, with their {...} selectors."""
    out = []
    for m in re.finditer(r"([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(\{[^}]*\})?", expr or ""):
        name, sel = m[1], m[2] or ""
        start = m.start()
        if name.lower() in PROMQL_WORDS or (start > 0 and expr[start - 1] in "\"'=~!"):
            continue
        nxt = expr[m.end():m.end() + 1]
        if nxt == "(" and not sel:   # a function call, not a metric
            continue
        if re.fullmatch(r"\d.*", name):
            continue
        out.append((name, sel))
    return out


def _scrape_jobs(out, resolver):
    """job -> containers (or the host) from VictoriaMetrics' scrape config."""
    vm = next((c for c in out["containers"] if c["name"] == VM_CONTAINER), None)
    src = next((m["source"] for m in (vm or {}).get("mounts", []) if m.get("dest") == "/etc/victoriametrics"), None)
    jobs = {}
    if not src:
        return jobs
    with open(os.path.join(src, "scrape.yml")) as fh:
        cfg = yaml.safe_load(fh) or {}
    for j in cfg.get("scrape_configs", []):
        tgts = []
        for sc in j.get("static_configs", []):
            for t in sc.get("targets", []):
                host, _, port = t.partition(":")
                if host in ("host.containers.internal", "host-gateway"):
                    tgts.append(("Host", out["host"]))
                    continue
                r = resolver.resolve(host, port, VM_CONTAINER)
                if r:
                    tgts.append(("Container", r) if r in resolver.by_name else ("Pod", r))
                    continue
                # A pod address (or localhost inside one) whose listener the
                # resolver cannot pin down: the job name usually names the
                # container (job litellm -> litellm); else credit the pod.
                pod = host if host in resolver.pod_members else \
                    (vm["pod"] if host in ("localhost", "127.0.0.1") and vm and vm["pod"] else None)
                if pod:
                    members = [c["name"] for c in resolver.pod_members.get(pod, [])]
                    jn = j["job_name"]
                    hit = next((m for m in members if m == jn), None) or \
                        next((m for m in members if m == jn + "-server"), None) or \
                        next((m for m in members if m.startswith(jn + "-")), None)
                    tgts.append(("Container", hit) if hit else ("Pod", pod))
        jobs[j["job_name"]] = tgts
    return jobs


def _watches(expr, jobs, host):
    """(targets, covers_all_containers) for one rule expression."""
    targets, all_containers = set(), False
    for name, sel in _expr_metrics(expr):
        if name == "up":
            pos = re.findall(r'job\s*=\s*"([^"]+)"', sel)
            neg = re.findall(r'job\s*!=\s*"([^"]+)"', sel)
            rx = re.findall(r'job\s*=~\s*"([^"]+)"', sel)
            chosen = [j for j in jobs if (not pos and not rx or j in pos or any(re.fullmatch(r, j) for r in rx))
                      and j not in neg]
            for j in chosen:
                targets |= set(jobs[j])
            continue
        for pat, label, target in METRIC_TARGETS:
            if re.search(pat, name):
                if target == "*":
                    all_containers = True
                elif label == "Host":
                    targets.add(("Host", host))
                else:
                    for t in (target if isinstance(target, list) else [target]):
                        targets.add((label, t))
                break
    return sorted(targets), all_containers


def collect_alerts(out):
    resolver = Resolver(out)
    jobs = _scrape_jobs(out, resolver)
    host = out["host"]
    rules, notes = [], []

    # vmalert: definitions from its mounted rule files, live state from its API.
    vma = next((c for c in out["containers"] if c["name"] == VMALERT_CONTAINER), None)
    rules_dir = next((m["source"] for m in (vma or {}).get("mounts", []) if m.get("dest") == "/etc/vmalert/rules"), None)
    notifier = next((a.split("=", 1)[1] for a in (vma or {}).get("_cmd", []) if a.startswith("-notifier.url=")), None)
    notifies = resolver.resolve(*(URL_RE.match(notifier)["host"], URL_RE.match(notifier)["port"])) if notifier and URL_RE.match(notifier) else None
    live = {}
    if vma and vma["state"] == "running":
        ip = next((v for v in (resolver.by_name[vma["name"]]["networks"] or {}).values() if v), None)
        try:
            with urllib.request.urlopen(f"http://{ip}:8880/api/v1/rules", timeout=10) as r:
                for g in json.load(r)["data"]["groups"]:
                    for x in g["rules"]:
                        live[(g["name"], x["name"])] = x
        except Exception as exc:
            notes.append(f"vmalert API unavailable: {exc}"[:120])
    else:
        notes.append("vmalert not running: definitions only, no live state")
    for f in sorted(glob.glob(os.path.join(rules_dir or "/nonexistent", "*.yml"))):
        with open(f) as fh:
            doc = yaml.safe_load(fh) or {}
        for g in doc.get("groups", []):
            for x in g.get("rules", []):
                if "alert" not in x:
                    continue
                expr = " ".join(str(x.get("expr", "")).split())
                tg, allc = _watches(expr, jobs, host)
                lv = live.get((g["name"], x["alert"]), {})
                rules.append({"key": f'vmalert/{g["name"]}/{x["alert"]}', "source": "vmalert", "group": g["name"],
                              "name": x["alert"], "severity": (x.get("labels") or {}).get("severity"),
                              "expr": expr[:500], "for": x.get("for"), "watches": [{"label": l, "name": n} for l, n in tg],
                              "covers_all_containers": allc, "state": lv.get("state"), "health": lv.get("health"),
                              "last_error": (lv.get("lastError") or "")[:200] or None,
                              "notifies": notifies, "file": f})

    # Grafana unified alerting (same admin login the grafana source uses).
    try:
        env = env_of(next(c for c in out["containers"] if c["name"] == "grafana"))
        tok = base64.b64encode(f'{env["GF_SECURITY_ADMIN_USER"]}:{env["GF_SECURITY_ADMIN_PASSWORD"]}'.encode()).decode()
        req = urllib.request.Request("http://127.0.0.1:3000/api/v1/provisioning/alert-rules",
                                     headers={"Authorization": "Basic " + tok})
        with urllib.request.urlopen(req, timeout=20) as r:
            for x in json.load(r):
                expr = " ".join(str((q.get("model") or {}).get("expr", "")) for q in x.get("data", []))
                tg, allc = _watches(expr, jobs, host)
                rules.append({"key": f'grafana/{x["uid"]}', "source": "grafana", "group": x.get("ruleGroup"),
                              "name": x.get("title"), "severity": (x.get("labels") or {}).get("severity"),
                              "expr": expr[:500], "for": x.get("for"), "watches": [{"label": l, "name": n} for l, n in tg],
                              "covers_all_containers": allc, "state": None, "health": None,
                              "last_error": None, "notifies": "grafana-contact-points", "file": None,
                              "paused": x.get("isPaused", False)})
    except Exception as exc:
        notes.append(f"Grafana rules unavailable: {exc}"[:120])
    if not rules:
        raise RuntimeError("implausible: no alert rules found")

    # Coverage: what has a rule about it specifically.
    watched = {(w["label"], w["name"]) for r in rules for w in r["watches"]}
    out["alert_rules"] = rules
    out["alert_coverage"] = {
        "containers_unwatched": sorted(c["name"] for c in out["containers"] if ("Container", c["name"]) not in watched
                                       and ("Pod", c["pod"]) not in watched),
        "jobs_unwatched": sorted(j["name"] for j in out.get("jobs", []) if ("ScheduledJob", j["name"]) not in watched),
        "no_container_down_rule": not any("state" in r["expr"] and "podman_container" in r["expr"] for r in rules),
    }
    out["alerts_note"] = "; ".join(notes) or None


# ───────────────────────────── remote hosts (pushed snapshots) ─────────────────────────────
# Machines this host cannot reach (the Fedora laptop) push a snapshot over SSH
# to inventory-ingest, which stores inventory/<host>.json. Each becomes a Host
# with its pipelines, timers/cron and listening ports.
INVENTORY_DIR = os.path.join(HERE, "inventory")
REMOTE_STALE_SECS = 3 * 86400


def _remote_port_reach(p, zones):
    """Who can reach a listening port on a firewalld machine: (reach, notes)."""
    try:
        ip = ipaddress.ip_address(p["addr"]) if p["addr"] not in ("*", "0.0.0.0", "::", "") else None
    except ValueError:
        ip = None
    if ip is not None and ip.is_loopback:
        return [], []
    def port_open(entries):
        # firewalld entries: "22/tcp" or ranges "1025-65535/tcp" (Fedora
        # Workstation's default zone opens that whole range).
        for e in entries or []:
            rng, _, proto = e.partition("/")
            lo, _, hi = rng.partition("-")
            if proto == p["proto"].rstrip("6") and lo.isdigit() and int(lo) <= p["port"] <= int(hi or lo):
                return True
        return False
    reach = set()
    for z, info in (zones or {}).items():
        ifaces = info.get("interfaces") or []
        opened = info.get("target") in ("ACCEPT", "default+accept") or port_open(info.get("ports"))
        if not opened:
            continue
        if any(i.startswith("tailscale") for i in ifaces):
            reach.add("tailnet")
        if any(not i.startswith(("tailscale", "lo", "podman", "docker", "virbr")) for i in ifaces) or info.get("sources"):
            reach.add("lan")
    if ip is not None and ip in TAILNET_V4 or (ip is not None and ip.version == 6 and ip in TAILNET_V6):
        reach &= {"tailnet"}
    return sorted(reach), ([] if zones else ["no firewalld data: exposure unknown"])


def collect_remote(out):
    files = sorted(glob.glob(os.path.join(INVENTORY_DIR, "*.json")))
    hosts, pipes, jobs, eps = [], [], [], []
    now = time.time()
    for f in files:
        with open(f) as fh:
            d = json.load(fh)
        h = d["host"]
        try:
            age = now - calendar.timegm(time.strptime(d.get("received_at", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            age = None
        repos = d.get("repos", [])
        hosts.append({"name": h, "hostname": d.get("hostname"), "os": d.get("os"), "received_at": d.get("received_at"),
                      "stale": age is None or age > REMOTE_STALE_SECS, "repos": len(repos),
                      "repos_dirty": sum(1 for r in repos if r.get("dirty")),
                      "repos_unpushed": sum(1 for r in repos if r.get("unpushed"))})
        for p in d.get("pipelines", []):
            origin = p.get("origin")
            own = bool(origin) and str(origin).split("/")[0].lower() == GITHUB_OWNER.lower()
            if p.get("system") == "git-hook":
                state = "runnable"
            elif p.get("system") == "github-actions" and not (origin and "/" in str(origin) and "://" not in str(origin)):
                state = "inert: repo has no GitHub remote"
            elif p.get("system") == "github-actions" and not own:
                state = "upstream repo (not yours)"
            else:
                state = "runnable"
            pipes.append(dict(p, file=f'{h}:{p["file"]}', host=h, own=own or not origin, state=state))
        for t in d.get("timers", []):
            failing = t.get("result") not in (None, "", "success") or (t.get("exit_status") not in (None, "", "0"))
            jobs.append({"name": f'{h}: {t.get("unit")}', "host": h, "schedule": t.get("next"), "kind": f'systemd-{t.get("scope")}',
                         "command": t.get("command"), "last_result": t.get("result"), "exit_status": t.get("exit_status"),
                         "failing": bool(failing)})
        for i, c in enumerate(d.get("cron", [])):
            parts = c["line"].split(None, 5)
            jobs.append({"name": f'{h}: cron {i + 1}', "host": h, "schedule": " ".join(parts[:5]), "kind": "cron",
                         "command": parts[5] if len(parts) > 5 else c["line"], "last_result": None, "exit_status": None,
                         "failing": False})
        zones = d.get("firewall_zones") or {}
        seen = set()
        for p in d.get("ports", []):
            if p.get("port") is None:
                continue
            reach, notes = _remote_port_reach(p, zones)
            k = (p["proto"], p["port"], p.get("process"))
            if k in seen or (not reach and not notes):
                continue
            seen.add(k)
            eps.append({"key": f'{h}:{p["proto"]}/{p["port"]}/{p.get("process") or "?"}', "kind": "port", "host_name": h,
                        "name": f'{h} {p.get("process") or "?"} {p["proto"]}/{p["port"]}', "proto": p["proto"],
                        "port": p["port"], "process": p.get("process"), "reachable": reach, "via": "direct",
                        "flags": notes + (["reachable from the LAN"] if "lan" in reach else [])})
        funnel = (d.get("exposure") or {}).get("tailscale_funnel") or {}
        for hostport, on in (funnel.get("AllowFunnel") or {}).items():
            if on:
                eps.append({"key": f"{h}:funnel/{hostport}", "kind": "funnel", "host_name": h,
                            "name": f"{h} tailscale funnel {hostport}", "proto": "https", "port": None, "process": "tailscaled",
                            "reachable": ["internet"], "via": "tailscale-funnel",
                            "flags": ["PUBLIC INTERNET via Tailscale Funnel"]})
    out["remote_hosts"], out["remote_pipelines"], out["remote_jobs"], out["remote_endpoints"] = hosts, pipes, jobs, eps


# ───────────────────────────── inventory markdown ─────────────────────────────
def fmt_bytes(b):
    if b is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or unit == "TB":
            return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
        b /= 1024


def write_inventory(out, path):
    L = [f"# alpine-vps inventory", "",
         f"Generated by infra-graph collector at {out['run']}. Do not edit; regenerated nightly.", "",
         "Sources: " + ", ".join(f"{k}={'ok' if v['ok'] else 'FAILED'}" for k, v in out["sources"].items()), ""]
    L += ["## Pods and containers", "", "| Container | Pod | State | Image | Memory limit | Backed up |", "|---|---|---|---|---|---|"]
    cov = {x["container"] for x in out.get("backup", {}).get("covered", [])}
    for c in sorted(out.get("containers", []), key=lambda c: (c["pod"] or "~", c["name"])):
        L.append(f'| {c["name"]} | {c["pod"] or "standalone"} | {c["state"]} | {c["image"]} | '
                 f'{fmt_bytes(c["memory_limit"]) if c["memory_limit"] else "none"} | {"yes" if c["name"] in cov else "no"} |')
    L += ["", "## Scheduled jobs", "", "| Job | Schedule | Frequency | Runs in | Ansible-managed |", "|---|---|---|---|---|"]
    for j in out.get("jobs", []):
        L.append(f'| {j["name"]} | `{j["schedule"]}` | {j["frequency"]} | {", ".join(j["runs_in"]) or "host"} | '
                 f'{"yes" if j["managed"] else "NO"} |')
    L += ["", "## Scripts", "", "| Script | Lang | Run by | Execs into | Calls (internal) | Outside APIs | Repo source |",
          "|---|---|---|---|---|---|---|"]
    runby = {}
    for j in out.get("jobs", []):
        for p in j.get("scripts", []):
            runby.setdefault(p, []).append(j["name"])
    for s in out.get("scripts", []):
        for q in s["invokes"]:
            runby.setdefault(q, []).append(s["name"])
    for s in sorted(out.get("scripts", []), key=lambda s: s["path"]):
        L.append(f'| `{s["path"]}` | {s["lang"]} | {", ".join(runby.get(s["path"], [])) or "—"} | '
                 f'{", ".join(s["execs"]) or "—"} | {", ".join(c["to"] for c in s["calls"]) or "—"} | '
                 f'{", ".join(x["api"] for x in s["externals"]) or "—"} | '
                 f'{(s["source"] or "").replace(REPO + "/", "") or "not found"} |')
    L += ["", f"## Outside APIs (observed via Squid, last {WINDOW_DAYS} days)", "",
          "| Caller | API | Category | Requests | Denied | Last seen |", "|---|---|---|---|---|---|"]
    for e in out.get("egress", []):
        L.append(f'| {e["who"]} | {e["api"]} | {e["category"]} | {e["requests"]:,} | {e["denied"]} | {e["last_seen"]} |')
    L += ["", f"## Most-used internal API paths (Traefik, last {WINDOW_DAYS} days)", "",
          "| Router | Method | Path | Hits | 4xx | 5xx | p95 ms |", "|---|---|---|---|---|---|---|"]
    for a in sorted(out.get("api_paths", []), key=lambda a: -a["hits"])[:60]:
        L.append(f'| {a["router"]} | {a["method"]} | `{a["path"]}` | {a["hits"]:,} | {a["errors_4xx"]} | '
                 f'{a["errors_5xx"]} | {a["p95_ms"]} |')
    for rh in out.get("remote_hosts", []):
        L += ["", f'## Remote host: {rh["name"]} ({rh.get("os") or "?"}, snapshot {rh.get("received_at")}'
                  + (", STALE" if rh["stale"] else "") + ")", "",
              f'{rh["repos"]} repos ({rh["repos_dirty"]} with uncommitted changes, {rh["repos_unpushed"]} with unpushed commits)', ""]
        rp = [p for p in out.get("remote_pipelines", []) if p["host"] == rh["name"] and p.get("own")]
        L += [f'- pipeline: {p["name"]} ({p["system"]}, {p["state"]}) {p.get("origin") or ""}' for p in rp]
        L += [f'- job: {j["name"]} [{j["kind"]}] {"FAILING (" + str(j.get("last_result")) + ")" if j["failing"] else ""}'
              for j in out.get("remote_jobs", []) if j["host"] == rh["name"]]
        L += [f'- endpoint: {e["name"]} reachable from {", ".join(e["reachable"]) or "?"} {"; ".join(e["flags"])}'
              for e in out.get("remote_endpoints", []) if e["host_name"] == rh["name"]]
    ars = out.get("alert_rules", [])
    if ars:
        cov = out.get("alert_coverage", {})
        L += ["", "## Alert rules and coverage", "", out.get("alerts_note") or "",
              f'Containers with no rule about them specifically ({len(cov.get("containers_unwatched", []))}): '
              + ", ".join(cov.get("containers_unwatched", [])), "",
              f'Scheduled jobs with no rule ({len(cov.get("jobs_unwatched", []))}): ' + ", ".join(cov.get("jobs_unwatched", [])), "",
              ("No rule fires when a container stops." if cov.get("no_container_down_rule") else ""), "",
              "| Rule | Source | Severity | Watches | State | Notifies |", "|---|---|---|---|---|---|"]
        for r in sorted(ars, key=lambda r: (r["source"], r.get("group") or "", r["name"] or "")):
            w = ", ".join(x["name"] for x in r["watches"]) + (" (+ every container)" if r["covers_all_containers"] else "")
            L.append(f'| {r["name"]} | {r["source"]} | {r.get("severity") or "—"} | {w or "—"} | '
                     f'{r.get("state") or "—"}{" ⚠ " + r["last_error"] if r.get("last_error") else ""} | {r.get("notifies") or "—"} |')
    pipes = out.get("pipelines", [])
    if pipes:
        L += ["", "## CI/CD pipelines", "", out.get("pipelines_note") or "",
              "| Pipeline | System | Repo | State | Triggers | Runner | Deploys | Last run | Secrets |",
              "|---|---|---|---|---|---|---|---|---|"]
        for p in sorted(pipes, key=lambda p: (not p.get("own"), p["state"] != "runnable", p.get("origin") or "", p["name"])):
            lr = p.get("last_run") or {}
            L.append(f'| {p["name"]} | {p["system"]} | {p.get("origin") or (p.get("repo") or "—").replace("/workspace/", "")} | '
                     f'{p["state"]}{" (disabled on GitHub)" if p.get("github_state") not in (None, "active") else ""} | '
                     f'{", ".join(map(str, p.get("triggers") or [])) or "—"} | {p.get("runner") or "—"} | {", ".join(p.get("deploys") or []) or "—"} | '
                     f'{(lr.get("conclusion") or lr.get("status") or "—")} {(lr.get("at") or "")[:10]} | {", ".join(p.get("secrets") or []) or "—"} |')
    eps = out.get("public_endpoints", [])
    if eps:
        L += ["", f'## Public endpoints (Cloudflare data exported {out.get("cf_exported_at") or "?"})', "",
              "| Endpoint | Kind | Reachable from | Via | Cloudflare Access | Middlewares | Flags |", "|---|---|---|---|---|---|---|"]
        for e in sorted(eps, key=lambda e: (e["kind"], e["name"])):
            L.append(f'| {e["name"]} | {e["kind"]} | {", ".join(e["reachable"]) or "—"} | {e["via"]} | {e.get("access") or "—"} | '
                     f'{", ".join(e["middlewares"]) or "—"} | {"; ".join(e["flags"]) or "ok"} |')
    creds = out.get("credentials", [])
    if creds:
        L += ["", "## Credentials (names only; values never leave the vault)", "",
              "| Key | Unlocks | Used by | Rotated (fingerprint since) | Flags |", "|---|---|---|---|---|"]
        for c in creds:
            used = [x["container"] for x in c["containers"]] + [os.path.basename(p) for p in c["scripts"]]
            flags = [f for f, on in (("live value differs from vault", c["drift"]),
                                     ("different values in the two vault files", c["conflict"]),
                                     ("listed twice in one vault file", c["duplicate_in_file"]),
                                     ("same value as " + ", ".join(c["reused_as"]), bool(c["reused_as"])),
                                     ("unreferenced here", c["unreferenced"]), ("empty", c["empty"])) if on]
            L.append(f'| {c["name"]} | {c["grants"] or "—"} | {", ".join(used) or "—"} | '
                     f'{(c["rotated_at"] or "—")[:10]} | {"; ".join(flags) or "ok"} |')
        um = out.get("unmanaged_secrets", [])
        if um:
            L += ["", "### Secret-looking container settings that match no vault key", ""]
            L += [f'- {u["container"]}: `{u["env"]}`' for u in um]
    L += ["", "## Datastores and databases", "", "| Datastore | Engine | Container | Size | Databases |", "|---|---|---|---|---|"]
    for d in out.get("datastores", []):
        L.append(f'| {d["name"]} | {d["engine"]} | {d.get("container") or "—"} | {fmt_bytes(d["bytes"])} | '
                 + ", ".join(f'{x["db"]} ({fmt_bytes(x["bytes"])})' for x in d["databases"]) + " |")
    L += ["", "## Database clients (live connections)", "", "| Database | Client | Role | Conns | Can write |", "|---|---|---|---|---|"]
    for d in out.get("datastores", []):
        for db in d["databases"]:
            for cl in db["clients"]:
                L.append(f'| {db["name"]} | {cl["who"]} | {cl["user"]} | {cl["conns"]} | {"yes" if cl["writes"] else "no"} |')
    L += ["", "## Largest tables", "", "| Table | Rows | Size |", "|---|---|---|"]
    tables = [t for d in out.get("datastores", []) for db in d["databases"] for t in db["tables"]]
    for t in sorted(tables, key=lambda t: -t["bytes"])[:40]:
        L.append(f'| {t["name"]} | {t["rows"]:,} | {fmt_bytes(t["bytes"])} |')
    L += ["", "## Routes", "", "| Host | Path | Backend | Middlewares |", "|---|---|---|---|"]
    for r in sorted(out.get("routes", []), key=lambda r: r["key"]):
        L.append(f'| {r["host"] or "—"} | {r["path"] or ""} | {", ".join(b["to"] or "?" for b in r["backends"])} | '
                 f'{", ".join(r["middlewares"]) or "none"} |')
    L += ["", "## MCP servers", "", "| Server | Scope | Transport | Runs in | Status |", "|---|---|---|---|---|"]
    for m in sorted(out.get("mcp_servers", []), key=lambda m: (m["scope"], m["name"])):
        L.append(f'| {m["name"]} | {m["scope"]}{(" (" + m["where"] + ")") if m.get("where") else ""} | {m["transport"]} | '
                 f'{m.get("container") or m.get("pod") or ("remote" if m["status"] in ("remote", "account-connector") else "host")} | {m["status"]} |')
    L += ["", "## Dashboards", "", "| Dashboard | Folder | Datasources |", "|---|---|---|"]
    dsn = {d["uid"]: d["name"] for d in out.get("datasources", [])}
    for d in sorted(out.get("dashboards", []), key=lambda d: d["title"]):
        L.append(f'| {d["title"]} | {d["folder"]} | {", ".join(dsn.get(u, u) for u in d["datasources"])} |')
    with open(path + ".tmp", "w") as fh:
        fh.write("\n".join(L) + "\n")
    os.replace(path + ".tmp", path)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "/opt/compose/infra-graph"
    os.makedirs(outdir, exist_ok=True)
    out = {"run": now_iso(), "host": HOST, "sources": {}, "_outdir": outdir}
    steps = [("podman", collect_podman), ("db", collect_dbs), ("cron", collect_cron), ("scripts", collect_scripts),
             ("traefik", collect_traefik), ("ingress", collect_ingress), ("egress", collect_egress),
             ("creds", collect_creds), ("exposure", collect_exposure), ("pipelines", collect_pipelines),
             ("alerts", collect_alerts), ("remote", collect_remote),
             ("grafana", collect_grafana), ("backup", collect_backup), ("mcp", collect_mcp)]
    # A source is skipped (not run, not reconciled) when one it builds on failed.
    needs = {"db": ["podman"], "traefik": ["podman"], "grafana": ["podman"], "backup": ["podman"],
             "mcp": ["podman"], "scripts": ["podman", "cron"], "ingress": ["traefik"], "egress": ["podman"],
             "creds": ["podman"], "exposure": ["traefik"], "alerts": ["podman", "cron"]}
    for name, fn in steps:
        t0 = time.time()
        failed = [n for n in needs.get(name, []) if not out["sources"].get(n, {}).get("ok")]
        if failed:
            out["sources"][name] = {"ok": False, "error": f"skipped: {', '.join(failed)} source failed", "secs": 0}
            continue
        try:
            fn(out)
            out["sources"][name] = {"ok": True, "secs": round(time.time() - t0, 1)}
        except Exception as e:
            out["sources"][name] = {"ok": False, "error": str(e)[:300], "secs": round(time.time() - t0, 1)}
    merge_apis(out)
    out.pop("_outdir", None)
    for c in out.get("containers", []):  # never let raw env or argv leave this process
        c.pop("_env", None)
        c.pop("_cmd", None)
    with open(os.path.join(outdir, "infra.json.tmp"), "w") as fh:
        json.dump(out, fh)
    os.replace(os.path.join(outdir, "infra.json.tmp"), os.path.join(outdir, "infra.json"))
    write_inventory(out, os.path.join(outdir, "INVENTORY.md"))
    print(json.dumps({"run": out["run"], "sources": out["sources"],
                      "counts": {k: len(out.get(k, [])) for k in
                                 ("pods", "containers", "networks", "jobs", "datastores", "routes", "dashboards", "datasources",
                                  "mcp_servers", "scripts", "apis", "egress", "api_paths", "credentials",
                                  "unmanaged_secrets", "public_endpoints", "pipelines", "alert_rules",
                                  "remote_hosts", "remote_pipelines", "remote_jobs", "remote_endpoints")},
                      "db_warnings": out.get("db_warnings", [])}, indent=1))
    return 0 if all(s["ok"] for s in out["sources"].values()) else 2


if __name__ == "__main__":
    sys.exit(main())
