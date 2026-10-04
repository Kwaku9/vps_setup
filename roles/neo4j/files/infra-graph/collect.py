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


def collect_dbs(out):
    resolver = Resolver(out)
    warnings = []
    stores = []
    for c in out["containers"]:
        eng = engine_of(c)
        if not eng:
            continue
        ds = {"name": c["name"], "engine": eng, "container": c["name"], "state": c["state"],
              "bytes": None, "databases": [], "roles": []}
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
            "invokes": [], "execs": [], "calls": [], "routes": [], "externals": []}
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

    # A Python file naming a path is usually reading it, not running it; only
    # count paths on lines that start a process.
    lines = code.splitlines()
    if info["lang"] == "python":
        lines = [l for l in lines if re.search(r"subprocess|Popen|\brun\(|\bcall\(|check_output|os\.system|execv", l)]
    body = "\n".join(lines)
    inv = set(SCRIPT_RE.findall(body))
    inv |= {os.path.normpath(os.path.join(os.path.dirname(path), r)) for r in REL_SCRIPT_RE.findall(body)}
    info["invokes"] = sorted(p for p in inv if p != path and is_script(p))

    # Which repo file deployed it: the Ansible task whose dest is this path;
    # else an identical files/ copy; else a lone same-named candidate.
    dests, names = sources
    cands = names.get(script_stem(info["name"]), [])
    full = hashlib.sha1(raw).hexdigest() if st.st_size <= len(raw) else None
    exact = [c for c in cands if full and sha1_file(c) == full]
    info["source"] = dests.get(path) or (exact[0] if exact else (cands[0] if len(cands) == 1 else None))
    return info


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
             ("grafana", collect_grafana), ("backup", collect_backup), ("mcp", collect_mcp)]
    # A source is skipped (not run, not reconciled) when one it builds on failed.
    needs = {"db": ["podman"], "traefik": ["podman"], "grafana": ["podman"], "backup": ["podman"],
             "mcp": ["podman"], "scripts": ["podman", "cron"], "ingress": ["traefik"], "egress": ["podman"]}
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
                                  "mcp_servers", "scripts", "apis", "egress", "api_paths")},
                      "db_warnings": out.get("db_warnings", [])}, indent=1))
    return 0 if all(s["ok"] for s in out["sources"].values()) else 2


if __name__ == "__main__":
    sys.exit(main())
