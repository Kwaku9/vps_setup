#!/usr/bin/env python3
"""infra-graph collector: discover what is ACTUALLY running and emit infra.json.

Every fact comes from a live source on this host, never from a hand-written map:

  podman   pods, containers, networks, IPs, mounts, limits   (podman inspect)
  cron     scheduled jobs                                    (/etc/crontabs/root)
  db       datastores, databases, tables, live connections   (pg/neo4j/redis catalogs, sqlite files)
  traefik  routes, middlewares, backends                     (/opt/compose/traefik/dynamic/*.yml)
  grafana  dashboards, datasources, panel->datasource links  (Grafana HTTP API)
  backup   which mounts/volumes the nightly backup covers    (/usr/local/bin/vps-backup)

Output is one JSON document consumed by load-infra.cypher via apoc.load.json.
Each source reports ok/failed in `sources`; the loader only reconciles (deletes
stale nodes for) sources that succeeded, so one broken API can never wipe a
slice of the graph.

Secrets: credentials are read from container metadata at runtime and passed to
child processes through the environment, never argv, and never written to the
output. Connection strings are reduced to host/port/db before they are stored.

Stdlib + PyYAML only (both present on the host).
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import base64
from datetime import datetime, timezone

import yaml

HOST = "alpine-vps"
DYNAMIC_DIR = "/opt/compose/traefik/dynamic"
CRONTAB = "/etc/crontabs/root"
BACKUP_SCRIPT = "/usr/local/bin/vps-backup"
SQLITE_ROOTS = ["/opt/podman-data", "/opt/compose"]

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
    out = {"run": now_iso(), "host": HOST, "sources": {}}
    steps = [("podman", collect_podman), ("db", collect_dbs), ("cron", collect_cron),
             ("traefik", collect_traefik), ("grafana", collect_grafana), ("backup", collect_backup), ("mcp", collect_mcp)]
    for name, fn in steps:
        t0 = time.time()
        if name != "podman" and not out["sources"].get("podman", {}).get("ok") and name in ("db", "traefik", "grafana", "backup", "mcp"):
            out["sources"][name] = {"ok": False, "error": "skipped: podman source failed", "secs": 0}
            continue
        try:
            fn(out)
            out["sources"][name] = {"ok": True, "secs": round(time.time() - t0, 1)}
        except Exception as e:
            out["sources"][name] = {"ok": False, "error": str(e)[:300], "secs": round(time.time() - t0, 1)}
    for c in out.get("containers", []):  # never let raw env or argv leave this process
        c.pop("_env", None)
        c.pop("_cmd", None)
    with open(os.path.join(outdir, "infra.json.tmp"), "w") as fh:
        json.dump(out, fh)
    os.replace(os.path.join(outdir, "infra.json.tmp"), os.path.join(outdir, "infra.json"))
    write_inventory(out, os.path.join(outdir, "INVENTORY.md"))
    print(json.dumps({"run": out["run"], "sources": out["sources"],
                      "counts": {k: len(out.get(k, [])) for k in
                                 ("pods", "containers", "networks", "jobs", "datastores", "routes", "dashboards", "datasources", "mcp_servers")},
                      "db_warnings": out.get("db_warnings", [])}, indent=1))
    return 0 if all(s["ok"] for s in out["sources"].values()) else 2


if __name__ == "__main__":
    sys.exit(main())
