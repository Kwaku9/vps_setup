// =============================================================================
// VPS SERVICE MAP — Neo4j graph load script
// Source of truth: docs/SERVICE-MAP.md  (live recon 2026-06-01; reconciled to live 2026-07-03 — see §13)
// Idempotent: uses MERGE everywhere. Safe to re-run; updates properties in place.
//
// NOTE: neo4j-db co-hosts TWO graphs in one DB — this service-map (Host/Network/Pod/
// Container/Datastore/Database/Role/Route/Middleware/External/Risk) AND the sessions-graph
// (Session/Message/ToolCall/Subagent/Artifact/Project/Commit). This script touches ONLY
// service-map labels; the cleanup block below is scoped by name and never deletes session nodes.
//
// Run options:
//   - cypher-shell:  cat docs/service-map.cypher | cypher-shell -u neo4j -p <pw>
//   - Neo4j Browser: paste in sections (Browser runs one statement per ; )
//   - neo4j MCP:     feed statements to write_neo4j_cypher
//
// Graph model
//   (:Host) (:Network) (:Pod) (:Container) (:Datastore) (:Database) (:Role)
//   (:Route) (:Middleware) (:External) (:Risk)
//   Rels: CONTAINS, ON_NETWORK{ip}, RUNS_ON, TUNNELS_TO, ROUTES_TO{port,path},
//         USES_MIDDLEWARE{order}, DEPENDS_ON{via,purpose,evidence}, USES_DATABASE{db,role},
//         HOSTS_DB, HAS_DATABASE, CONNECTS_AS, AUTHENTICATES_VIA, SCRAPES, SHIPS_TO{signal},
//         CALLS_EXTERNAL{purpose}, AFFECTS
// =============================================================================

// ---------- Constraints (uniqueness) ----------------------------------------
CREATE CONSTRAINT host_name      IF NOT EXISTS FOR (n:Host)       REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT network_name   IF NOT EXISTS FOR (n:Network)    REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT pod_name       IF NOT EXISTS FOR (n:Pod)        REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT container_name IF NOT EXISTS FOR (n:Container)  REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT datastore_name IF NOT EXISTS FOR (n:Datastore)  REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT database_name  IF NOT EXISTS FOR (n:Database)   REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT role_name      IF NOT EXISTS FOR (n:Role)       REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT route_host     IF NOT EXISTS FOR (n:Route)      REQUIRE n.host IS UNIQUE;
CREATE CONSTRAINT mw_name        IF NOT EXISTS FOR (n:Middleware) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT external_name  IF NOT EXISTS FOR (n:External)   REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT risk_id        IF NOT EXISTS FOR (n:Risk)       REQUIRE n.id IS UNIQUE;

// ---------- Cleanup: services no longer live (removed since 2026-06-01) -------
// Scoped by name to service-map nodes only. Idempotent (no-op if already gone).
MATCH (c:Container) WHERE c.name IN ['authentik-proxy','portainer','n8n-claude'] DETACH DELETE c;
MATCH (r:Route) WHERE r.hostname IN ['n8n.aicortex.cloud','portainer.aicortex.cloud'] DETACH DELETE r;
MATCH (ds:Datastore) WHERE ds.name IN ['portainer.db'] DETACH DELETE ds;
MATCH (db:Database) WHERE db.name IN ['n8n'] DETACH DELETE db;
// correct an earlier mis-modeled edge: timeline-context-api talks to neo4j-db (bolt), not postgres
MATCH (:Container {name:'timeline-context-api'})-[r:USES_DATABASE]->(:Datastore {name:'pg-enterprise'}) DELETE r;
MATCH (:Container {name:'timeline-context-api'})-[r:DEPENDS_ON]->(:Container {name:'postgres'}) DELETE r;

// ---------- Host & Networks --------------------------------------------------
MERGE (h:Host {name:'alpine-vps'})
  SET h.hostname='srv1234518', h.os='Alpine Linux', h.kernel='6.18.35-0-virt',
      h.runtime='Podman 5.8.3 (netavark)', h.role='production',
      h.public_ports='22,80,443', h.tailscale='100.121.252.38',
      h.disk='94GB root @ ~90% (2026-07-03)';

MERGE (n1:Network {name:'enterprise_network'}) SET n1.cidr='10.89.0.0/24', n1.gateway='10.89.0.1', n1.backend='netavark', n1.dns='enabled';
MERGE (n2:Network {name:'monitoring-net'})     SET n2.cidr='10.89.1.0/24', n2.gateway='10.89.1.1', n2.backend='netavark';
MERGE (n3:Network {name:'scraper-network'})    SET n3.cidr='10.89.2.0/24', n3.gateway='10.89.2.1', n3.backend='netavark';

// ---------- Pods (with enterprise_network IP) --------------------------------
// NB: enterprise IPs are aardvark-assigned and churn on restart; values are 2026-07-03 live.
UNWIND [
  {name:'shared-db-pod',               ip:'10.89.0.26',  status:'running'},
  {name:'ai-stack-pod',                ip:'10.89.0.22',  status:'running'},
  {name:'authentication-pod',          ip:'10.89.0.24',  status:'running'},
  {name:'authentication-worker-pod',   ip:'10.89.0.18',  status:'running'},
  {name:'metrics-pod',                 ip:'10.89.0.15',  status:'running'},
  {name:'logs-pod',                    ip:'10.89.0.17',  status:'running'},
  {name:'tempo-pod',                   ip:'10.89.0.20',  status:'running'},
  {name:'frontend-pod',                ip:'10.89.0.25',  status:'running'},
  {name:'management-pod',              ip:'10.89.0.23',  status:'running'},
  {name:'security-infra-pod',          ip:'10.89.0.14',  status:'running'},
  {name:'backend-pod',                 ip:'10.89.0.19',  status:'degraded'},
  {name:'dev-pod',                     ip:'10.89.0.71',  status:'degraded'},
  {name:'security-pod',                ip:'10.89.0.27',  status:'empty-shell'},
  {name:'neo4j-pod',                   ip:'10.89.0.7',   status:'running'},
  {name:'reports-pod',                 ip:'10.89.0.160', status:'running'},
  {name:'llama-embed-pod',             ip:'10.89.0.16',  status:'degraded'},
  {name:'pod_livekit',                 ip:null,          status:'created-empty'}
] AS p
MERGE (pod:Pod {name:p.name}) SET pod.ip=p.ip, pod.status=p.status
MERGE (net:Network {name:'enterprise_network'})
MERGE (pod)-[r:ON_NETWORK]->(net) SET r.ip=p.ip
MERGE (h:Host {name:'alpine-vps'})
MERGE (pod)-[:RUNS_ON]->(h);

// dual-homed pods on monitoring-net (2026-07-03 live IPs)
UNWIND [
  {pod:'metrics-pod', ip:'10.89.1.20'},
  {pod:'logs-pod',    ip:'10.89.1.21'},
  {pod:'tempo-pod',   ip:'10.89.1.22'}
] AS m
MERGE (pod:Pod {name:m.pod})
MERGE (net:Network {name:'monitoring-net'})
MERGE (pod)-[r:ON_NETWORK]->(net) SET r.ip=m.ip;

// ---------- Containers (in pods) ---------------------------------------------
UNWIND [
  {name:'postgres',           pod:'shared-db-pod',             image:'pgvector/pgvector:pg16',             mem:'256Mi', port:5432, status:'running', kind:'database'},
  {name:'litellm',            pod:'ai-stack-pod',              image:'litellm-database:main-latest',       mem:'512Mi', port:4000, status:'running', kind:'ai-gateway'},
  {name:'open-webui',         pod:'ai-stack-pod',              image:'open-webui:v0.9.6',                  mem:'1024Mi',port:8080, status:'running', kind:'app'},
  {name:'ai-stack-postgres',  pod:'ai-stack-pod',              image:'postgres:16-alpine',                 mem:'256Mi', port:5432, status:'running', kind:'database'},
  {name:'kokoro-tts',         pod:'ai-stack-pod',              image:'kokoro-fastapi-cpu:latest',          mem:'2048Mi',port:8880, status:'running', kind:'ai-service'},
  {name:'searxng',            pod:'ai-stack-pod',              image:'searxng:latest',                     mem:'128Mi', port:8080, status:'running', kind:'search'},
  {name:'gemini-tts-proxy',   pod:'ai-stack-pod',              image:'gemini-tts-proxy:local',             mem:'128Mi', port:5001, status:'running', kind:'ai-service'},
  {name:'authentik-server',   pod:'authentication-pod',        image:'goauthentik/server:2026.5.2',        mem:'1024Mi',port:9000, status:'running', kind:'auth'},
  {name:'authentik-postgres', pod:'authentication-pod',        image:'postgres:16-alpine',                 mem:'256Mi', port:5432, status:'running', kind:'database'},
  {name:'redis',              pod:'authentication-pod',        image:'redis:8-alpine',                     mem:'128Mi', port:6379, status:'running', kind:'cache'},
  {name:'authentik-worker',   pod:'authentication-worker-pod', image:'goauthentik/server:2026.5.2',        mem:'512Mi', status:'running',           kind:'auth'},
  {name:'victoriametrics',    pod:'metrics-pod',               image:'victoria-metrics:v1.115.0',          mem:'1536Mi',port:8428, status:'running', kind:'tsdb'},
  {name:'vmalert',            pod:'metrics-pod',               image:'vmalert:v1.115.0',                   mem:'128Mi', port:8880, status:'running', kind:'alerting'},
  {name:'grafana',            pod:'metrics-pod',               image:'grafana:13.1.0-ubuntu',              mem:'512Mi', port:3000, status:'running', kind:'app'},
  {name:'renderer',           pod:'metrics-pod',               image:'grafana-image-renderer:latest',      mem:'512Mi', port:8081, status:'running', kind:'support'},
  {name:'loki',               pod:'logs-pod',                  image:'grafana/loki:3.6.3',                 mem:'768Mi', port:3100, status:'running', kind:'logstore'},
  {name:'alloy',              pod:'logs-pod',                  image:'grafana/alloy:v1.12.2',              mem:'640Mi', port:4318, status:'running', kind:'collector'},
  {name:'tempo',              pod:'tempo-pod',                 image:'grafana/tempo:2.9.0',                mem:'1536Mi',port:3200, status:'running', kind:'tracestore'},
  {name:'nginx',              pod:'frontend-pod',              image:'nginx:1.29-alpine',                  mem:'128Mi', port:80,   status:'running', kind:'frontend'},
  {name:'worldview-dev',      pod:'frontend-pod',              image:'node:22-alpine',                     mem:'640Mi', port:5173, status:'running', kind:'frontend'},
  {name:'atlas-charts',       pod:'frontend-pod',              image:'atlas-charts:latest',                mem:'64Mi',  port:3080, status:'running', kind:'frontend'},
  {name:'journey-tracker',    pod:'frontend-pod',              image:'nginx:alpine',                       mem:'32Mi',  port:8092, status:'running', kind:'frontend'},
  {name:'ops-dashboard',      pod:'management-pod',            image:'ops-dashboard:latest',               mem:'256Mi', port:8090, status:'running', kind:'app'},
  {name:'crowdsec',           pod:'security-infra-pod',        image:'crowdsec:v1.7.8',                    mem:'128Mi', port:8180, status:'running', kind:'security'},
  {name:'ais-relay',          pod:'backend-pod',               image:'ais-relay:latest',                   mem:'128Mi', status:'exited-137',        kind:'relay'},
  {name:'expo-dev',           pod:'dev-pod',                   image:'expo-dev:latest',                    mem:'3072Mi',status:'exited-0-intentional', kind:'dev'},
  {name:'neo4j-db',           pod:'neo4j-pod',                 image:'neo4j:5-community',                  mem:'1024Mi',port:7687, status:'running', kind:'graphdb'},
  {name:'neo4j-mcp-server',   pod:'neo4j-pod',                 image:'neo4j-mcp:latest',                   mem:'256Mi',            status:'running', kind:'mcp'},
  {name:'grafana-reports',    pod:'reports-pod',               image:'grafana-reports:latest',             mem:'256Mi',            status:'running-healthy', kind:'reporting'},
  {name:'llama-embed',        pod:'llama-embed-pod',           image:'ghcr.io/ggml-org/llama.cpp:server',  mem:'512Mi', port:8080, status:'exited-degraded', kind:'ai-service'}
] AS c
MERGE (cont:Container {name:c.name})
  SET cont.image=c.image, cont.mem_limit=c.mem, cont.port=c.port, cont.status=c.status, cont.kind=c.kind, cont.deployment='pod'
MERGE (pod:Pod {name:c.pod})
MERGE (pod)-[:CONTAINS]->(cont)
MERGE (enet:Network {name:'enterprise_network'})
MERGE (cont)-[:ON_NETWORK]->(enet);

// ---------- Standalone containers --------------------------------------------
UNWIND [
  {name:'traefik',            ip:'10.89.0.245', image:'traefik:v3.7',                 mem:'128Mi', status:'running', kind:'ingress'},
  {name:'cloudflared',        ip:'10.89.0.244', image:'cloudflared:latest',           status:'running',             kind:'tunnel'},
  {name:'telegram-gateway',   ip:'10.89.0.242', image:'telegram-gateway:latest',      mem:'512Mi', port:7555, status:'running-healthy', kind:'integration'},
  {name:'telegram-coder',     ip:'10.89.0.63',  image:'telegram-gateway:latest',      mem:'512Mi', port:7556, status:'running-healthy', kind:'integration'},
  {name:'owui-coder',         ip:'10.89.0.243', image:'telegram-gateway:latest',      mem:'512Mi', port:7557, status:'running-healthy', kind:'integration'},
  {name:'google-docs-mcp',    ip:'10.89.0.44',  image:'google-docs-mcp:latest',       mem:'256Mi', port:9091, status:'running', kind:'mcp'},
  {name:'scrapy-mcp',         ip:'10.89.0.58',  image:'scrapy-mcp:latest',            mem:'128Mi', port:8888, status:'running', kind:'mcp'},
  {name:'session-recall-mcp', ip:'10.89.0.241', image:'session-recall-mcp:latest',    mem:'256Mi',            status:'running-healthy', kind:'mcp'},
  {name:'timeline-context-api',ip:'10.89.0.13', image:'timeline-context-api:latest',  mem:'256Mi', port:8080, status:'running', kind:'api'},
  {name:'decks-nginx',        ip:'10.89.0.21',  image:'nginx:1.29-alpine',            mem:'128Mi', port:80,   status:'running', kind:'frontend'},
  {name:'tetragon',           ip:'10.89.0.65',  image:'quay.io/cilium/tetragon:v1.6.0', status:'running',           kind:'security'},
  {name:'honeypot',           ip:'10.89.0.31',  image:'localhost/honeypot:latest',    mem:'256Mi', port:8099, status:'running', kind:'security'},
  {name:'threat-map',         ip:'10.89.0.32',  image:'localhost/threat-map:latest',  mem:'256Mi', port:8097, status:'running', kind:'security'},
  {name:'nomic-embed',        ip:null,          image:'ghcr.io/ggml-org/llama.cpp:server', status:'exited', kind:'ai-service'},
  {name:'qdrant-spike',       ip:null,          image:'qdrant/qdrant:latest',         status:'exited-143',           kind:'vectordb'},
  {name:'ansible-deployment', ip:null,          image:'ansible-vps:latest',           status:'running', kind:'control'}
] AS s
MERGE (cont:Container {name:s.name})
  SET cont.image=s.image, cont.mem_limit=s.mem, cont.port=s.port, cont.status=s.status, cont.kind=s.kind, cont.deployment='standalone', cont.ip=s.ip
MERGE (sh:Host {name:'alpine-vps'})
MERGE (cont)-[:RUNS_ON]->(sh)
MERGE (senet:Network {name:'enterprise_network'})
MERGE (cont)-[r:ON_NETWORK]->(senet) SET r.ip=s.ip;

// scrapy-mcp dual-homed
MERGE (sm:Container {name:'scrapy-mcp'})
MERGE (snet:Network {name:'scraper-network'})
MERGE (sm)-[r:ON_NETWORK]->(snet) SET r.ip='10.89.2.2';

// ---------- Datastores & Databases & Roles -----------------------------------
// NB: keep node MERGE + relationship MERGE in ONE statement (cypher-shell isolates ; statements).
UNWIND [
  {name:'pg-enterprise', engine:'PostgreSQL 16 (pgvector)', size:'~700MB', path:'/opt/podman-data/postgres',           host:'postgres',           note:'image migrated postgres:16-alpine -> pgvector/pgvector:pg16; trust@localhost / scram@cross-pod', requirepass:null},
  {name:'pg-ai-stack',   engine:'PostgreSQL 16', size:'90MB',  path:'/opt/podman-data/ai-stack/postgres',        host:'ai-stack-postgres',  note:'single superuser role aistack',     requirepass:null},
  {name:'pg-authentik',  engine:'PostgreSQL 16', size:'148MB', path:'named-volume:authentik-postgres-data',      host:'authentik-postgres', note:'only store outside /opt/podman-data; task-log bloat', requirepass:null},
  {name:'redis-cache',   engine:'Redis 8.4.0',   size:null,    path:'/opt/podman-data/redis',                     host:'redis',              note:'UNAUTHENTICATED — pod-isolation only', requirepass:false},
  {name:'neo4j-graph',   engine:'Neo4j 5 community (apoc)', size:'~1.6GB', path:'/opt/podman-data/neo4j',         host:'neo4j-db',           note:'co-hosts service-map graph + sessions-graph', requirepass:null},
  {name:'webui.db',      engine:'SQLite',        size:'239MB', path:'/opt/podman-data/ai-stack/openwebui',        host:'open-webui',         note:'OpenWebUI PersistentConfig/users/chats', requirepass:null},
  {name:'grafana.db',    engine:'SQLite',        size:'4.4MB', path:'grafana-data',                               host:'grafana',            note:null, requirepass:null}
] AS d
MERGE (ds:Datastore {name:d.name})
  SET ds.engine=d.engine, ds.size=d.size, ds.data_path=d.path, ds.note=d.note, ds.requirepass=d.requirepass
MERGE (c:Container {name:d.host})
MERGE (ds)-[:HOSTS_DB]->(c);

// Databases within each Postgres instance
UNWIND [
  {db:'enterprise', store:'pg-enterprise', size:'~700MB', schemas:'sessions,gateway,trading,public,openwebui,recall,spike', status:null},
  {db:'litellm',    store:'pg-ai-stack',   size:'16MB',  schemas:null, status:null},
  {db:'memory',     store:'pg-ai-stack',   size:'10MB',  schemas:null, status:'OK — pgvector 0.8.2 (was BROKEN pre-migration; §11.2 R2 resolved)'},
  {db:'authentik',  store:'pg-authentik',  size:'148MB', schemas:null, status:null}
] AS x
MERGE (db:Database {name:x.db})
  SET db.size=x.size, db.schemas=x.schemas, db.status=x.status
MERGE (ds:Datastore {name:x.store})
MERGE (ds)-[:HAS_DATABASE]->(db);

// DB roles
UNWIND [
  {role:'telegram_gw',   store:'pg-enterprise', super:false},
  {role:'ops_dashboard', store:'pg-enterprise', super:false},
  {role:'session_ingest',store:'pg-enterprise', super:false},
  {role:'grafana_ro',    store:'pg-enterprise', super:false},
  {role:'aistack',       store:'pg-ai-stack',   super:true},
  {role:'authentik',     store:'pg-authentik',  super:true}
] AS r
MERGE (role:Role {name:r.role}) SET role.superuser=r.super
MERGE (ds:Datastore {name:r.store})
MERGE (ds)-[:HAS_ROLE]->(role);

// service -> datastore (with role / db)
UNWIND [
  {svc:'telegram-gateway',    store:'pg-enterprise', db:'enterprise', role:'telegram_gw'},
  {svc:'telegram-coder',      store:'pg-enterprise', db:'enterprise', role:'telegram_gw'},
  {svc:'ops-dashboard',       store:'pg-enterprise', db:'enterprise', role:'ops_dashboard'},
  {svc:'grafana',             store:'pg-enterprise', db:'enterprise', role:'grafana_ro'},
  {svc:'session-recall-mcp',  store:'pg-enterprise', db:'enterprise', role:'session_ingest'},
  {svc:'litellm',             store:'pg-ai-stack',   db:'litellm',    role:'aistack'},
  {svc:'authentik-server',    store:'pg-authentik',  db:'authentik',  role:'authentik'},
  {svc:'authentik-worker',    store:'pg-authentik',  db:'authentik',  role:'authentik'},
  {svc:'authentik-server',    store:'redis-cache',   db:'-',          role:'-'},
  {svc:'authentik-worker',    store:'redis-cache',   db:'-',          role:'-'},
  {svc:'neo4j-mcp-server',    store:'neo4j-graph',   db:'-',          role:'-'}
] AS u
MERGE (svc:Container {name:u.svc})
MERGE (ds:Datastore {name:u.store})
MERGE (svc)-[d:USES_DATABASE]->(ds) SET d.db=u.db, d.role=u.role;

// ---------- Ingress edge: tunnel -> traefik ----------------------------------
MERGE (cf:Container {name:'cloudflared'})
MERGE (tf:Container {name:'traefik'})
MERGE (cf)-[:TUNNELS_TO {note:'Cloudflare Tunnel alpine-vps-tunnel -> https://traefik:443'}]->(tf);

// ---------- Middleware -------------------------------------------------------
UNWIND [
  {name:'crowdsec',      type:'plugin',      purpose:'CrowdSec LAPI bouncer (security-infra-pod:8180)'},
  {name:'internal-only', type:'ipAllowList', purpose:'restrict to 10.89.0.0/24 + 127.0.0.0/8'},
  {name:'secure-headers',type:'headers',     purpose:'HSTS preload, nosniff, frameDeny'},
  {name:'rate-limit',    type:'rateLimit',   purpose:'avg 300 / burst 200 / 1m'},
  {name:'authentik',     type:'forwardAuth', purpose:'DEAD/standby - outpost removed 2026-07'},
  {name:'compress',      type:'compress',    purpose:'DEAD - unreferenced'}
] AS m
MERGE (mw:Middleware {name:m.name}) SET mw.type=m.type, mw.purpose=m.purpose;

// ---------- Routes (public hostname -> backend container) --------------------
UNWIND [
  {host:'aicortex.cloud',        backend:'honeypot',            port:8099, path:'/',                mw:[]},
  {host:'grafana.aicortex.cloud',backend:'grafana',             port:3000, path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'chat.aicortex.cloud',   backend:'open-webui',          port:8080, path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'chat.aicortex.cloud',   backend:'litellm',             port:4000, path:'/vertex_ai/live',  mw:['crowdsec','internal-only','secure-headers']},
  {host:'litellm.aicortex.cloud',backend:'litellm',             port:4000, path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'tts.aicortex.cloud',    backend:'kokoro-tts',          port:8880, path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'prometheus.aicortex.cloud',backend:'victoriametrics',  port:8428, path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'auth.aicortex.cloud',   backend:'authentik-server',    port:9000, path:'/',                mw:['crowdsec','internal-only','secure-headers']},
  {host:'ops.aicortex.cloud',    backend:'ops-dashboard',       port:8090, path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'portal.aicortex.cloud', backend:'nginx',               port:80,   path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'geo.aicortex.cloud',    backend:'worldview-dev',       port:5173, path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'charts.aicortex.cloud', backend:'atlas-charts',        port:3080, path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'timeline.aicortex.cloud',backend:'journey-tracker',    port:8092, path:'/',                mw:[]},
  {host:'context.aicortex.cloud',backend:'timeline-context-api',port:8080, path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'decks.aicortex.cloud',  backend:'decks-nginx',         port:80,   path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'telegram-bot.aicortex.cloud',backend:'telegram-gateway',port:7555,path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'telegram-coder.aicortex.cloud',backend:'telegram-coder',port:7556,path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'threat.aicortex.cloud', backend:'threat-map',          port:8097, path:'/',                mw:['crowdsec']},
  {host:'otlp.aicortex.cloud',   backend:'alloy',               port:4318, path:'/',                mw:['crowdsec','internal-only','secure-headers','rate-limit']},
  {host:'otel.aicortex.cloud',   backend:'alloy',               port:4318, path:'/ (Bearer token)', mw:['crowdsec','secure-headers','rate-limit']}
] AS rt
MERGE (route:Route {host:rt.host + (CASE WHEN rt.path='/' THEN '' ELSE rt.path END)})
  SET route.hostname=rt.host, route.path=rt.path, route.tls='cloudflare-wildcard'
MERGE (be:Container {name:rt.backend})
MERGE (route)-[r:ROUTES_TO]->(be) SET r.port=rt.port, r.path=rt.path
WITH route, rt
UNWIND range(0, size(rt.mw)-1) AS i
  MERGE (mw:Middleware {name:rt.mw[i]})
  MERGE (route)-[um:USES_MIDDLEWARE]->(mw) SET um.order=i+1;

// traefik dashboard route (dead)
MERGE (rd:Route {host:'traefik.aicortex.cloud'})
  SET rd.hostname='traefik.aicortex.cloud', rd.note='DEAD - api.insecure:false, points at localhost:8080 -> 404';

// All routes terminate at traefik
MATCH (route:Route) MATCH (tf:Container {name:'traefik'})
MERGE (tf)-[:SERVES]->(route);

// ---------- East-West dependencies (DEPENDS_ON) ------------------------------
UNWIND [
  {src:'open-webui',           dst:'litellm',          via:'http:4000',  purpose:'chat completions', ev:'env+cfg'},
  {src:'open-webui',           dst:'kokoro-tts',       via:'http:8880',  purpose:'TTS audio',        ev:'env'},
  {src:'open-webui',           dst:'searxng',          via:'http:8080',  purpose:'web search',       ev:'cfg'},
  {src:'litellm',              dst:'gemini-tts-proxy', via:'http:5001',  purpose:'gemini TTS model', ev:'cfg'},
  {src:'authentik-server',     dst:'authentik-worker', via:'rpc',        purpose:'task channels',    ev:'live'},
  {src:'telegram-gateway',     dst:'litellm',          via:'http:4000',  purpose:'LLM (haiku)',      ev:'env'},
  {src:'telegram-gateway',     dst:'kokoro-tts',       via:'http:8880',  purpose:'TTS',              ev:'env'},
  {src:'telegram-gateway',     dst:'grafana',          via:'http:3000',  purpose:'dashboards',       ev:'env'},
  {src:'telegram-coder',       dst:'litellm',          via:'http:4000',  purpose:'LLM coder',        ev:'inferred'},
  {src:'owui-coder',           dst:'litellm',          via:'http:4000',  purpose:'LLM coder',        ev:'inferred'},
  {src:'ops-dashboard',        dst:'victoriametrics',  via:'http:8428',  purpose:'metrics',          ev:'env+live'},
  {src:'atlas-charts',         dst:'victoriametrics',  via:'http:8428',  purpose:'metrics proxy',    ev:'cfg'},
  {src:'threat-map',           dst:'crowdsec',         via:'http:8180',  purpose:'LAPI threat data', ev:'env'},
  {src:'threat-map',           dst:'loki',             via:'http:3100',  purpose:'log query',        ev:'env'},
  {src:'neo4j-mcp-server',     dst:'neo4j-db',         via:'bolt:7687',  purpose:'graph queries',    ev:'live'},
  {src:'session-recall-mcp',   dst:'postgres',         via:'pg:5432',    purpose:'session recall',   ev:'env'},
  {src:'timeline-context-api', dst:'neo4j-db',         via:'bolt:7687',  purpose:'graph-RAG context',ev:'env'},
  {src:'grafana-reports',      dst:'grafana',          via:'http:3000',  purpose:'render+export reports', ev:'inferred'},
  {src:'grafana-reports',      dst:'renderer',         via:'http:8081',  purpose:'PDF render',       ev:'inferred'},
  {src:'traefik',              dst:'crowdsec',         via:'http:8180',  purpose:'bouncer LAPI',     ev:'plugin'},
  {src:'grafana',              dst:'victoriametrics',  via:'http:8428',  purpose:'datasource',       ev:'cfg'},
  {src:'grafana',              dst:'loki',             via:'http:3100',  purpose:'datasource',       ev:'cfg'},
  {src:'grafana',              dst:'tempo',            via:'http:3200',  purpose:'datasource',       ev:'cfg'},
  {src:'grafana',              dst:'renderer',         via:'http:8081',  purpose:'image render',     ev:'env'},
  {src:'vmalert',              dst:'victoriametrics',  via:'http:8428',  purpose:'query/eval',       ev:'live'},
  {src:'alloy',                dst:'loki',             via:'http:3100',  purpose:'ship logs',        ev:'cfg'},
  {src:'alloy',                dst:'tempo',            via:'http:4320',  purpose:'ship traces',      ev:'cfg'},
  {src:'alloy',                dst:'victoriametrics',  via:'remote_write:8428', purpose:'ship metrics', ev:'cfg'}
] AS e
MERGE (src:Container {name:e.src})
MERGE (dst:Container {name:e.dst})
MERGE (src)-[d:DEPENDS_ON]->(dst) SET d.via=e.via, d.purpose=e.purpose, d.evidence=e.ev;

// service -> host (SSH to run claude CLI / ops). Each statement re-matches Host by key.
MATCH (h:Host {name:'alpine-vps'}) MERGE (tg:Container {name:'telegram-gateway'}) MERGE (tg)-[:DEPENDS_ON {via:'ssh', purpose:'drive claude CLI'}]->(h);
MATCH (h:Host {name:'alpine-vps'}) MERGE (od:Container {name:'ops-dashboard'})    MERGE (od)-[:DEPENDS_ON {via:'ssh', purpose:'ops actions'}]->(h);
MATCH (h:Host {name:'alpine-vps'}) MERGE (tt:Container {name:'tetragon'})         MERGE (tt)-[:DEPENDS_ON {via:'ebpf', purpose:'kernel event tracing'}]->(h);

// ---------- OTLP telemetry emitters -> alloy ---------------------------------
UNWIND ['open-webui','litellm','kokoro-tts','telegram-gateway','traefik','tetragon'] AS emitter
MERGE (em:Container {name:emitter})
MERGE (al:Container {name:'alloy'})
MERGE (em)-[:SHIPS_TO {signal:'otlp'}]->(al);

// ---------- AUTHENTICATES_VIA (OIDC) -----------------------------------------
UNWIND ['grafana','open-webui','threat-map'] AS client
MERGE (cl:Container {name:client})
MERGE (as:Container {name:'authentik-server'})
MERGE (cl)-[:AUTHENTICATES_VIA {protocol:'OIDC', issuer:'auth.aicortex.cloud'}]->(as);

// ---------- VictoriaMetrics SCRAPES ------------------------------------------
UNWIND [
  {t:'victoriametrics', port:8428}, {t:'loki', port:3100}, {t:'grafana', port:3000},
  {t:'traefik', port:8080}, {t:'litellm', port:4000}, {t:'authentik-server', port:9300},
  {t:'crowdsec', port:6060}, {t:'cloudflared', port:2000}
] AS s
MERGE (vm:Container {name:'victoriametrics'})
MERGE (tgt:Container {name:s.t})
MERGE (vm)-[r:SCRAPES]->(tgt) SET r.port=s.port;
// node-exporter on host
MERGE (vm:Container {name:'victoriametrics'})
MERGE (h:Host {name:'alpine-vps'})
MERGE (vm)-[:SCRAPES {port:9100, target:'node-exporter'}]->(h);

// ---------- External / 3rd-party services ------------------------------------
UNWIND [
  {ext:'OpenAI',        purpose:'LLM inference',  src:'litellm'},
  {ext:'Anthropic',     purpose:'LLM inference',  src:'litellm'},
  {ext:'OpenRouter',    purpose:'LLM inference',  src:'litellm'},
  {ext:'Google Vertex AI',purpose:'LLM/TTS',      src:'litellm'},
  {ext:'Google Vertex AI',purpose:'gemini TTS',   src:'gemini-tts-proxy'},
  {ext:'DeepSeek',      purpose:'LLM inference',  src:'litellm'},
  {ext:'Cohere',        purpose:'LLM inference',  src:'litellm'},
  {ext:'Groq',          purpose:'LLM inference',  src:'litellm'},
  {ext:'xAI',           purpose:'LLM inference',  src:'litellm'},
  {ext:'api.telegram.org',purpose:'bot I/O',      src:'telegram-gateway'},
  {ext:'Google Docs/Drive API',purpose:'docs ops',src:'google-docs-mcp'},
  {ext:'aisstream.io',  purpose:'AIS vessel feed',src:'ais-relay'},
  {ext:'WiGLE API',     purpose:'geo/wardriving', src:'worldview-dev'},
  {ext:'CrowdSec CAPI', purpose:'threat intel',   src:'crowdsec'},
  {ext:'Cloudflare DNS API',purpose:'ACME DNS-01',src:'traefik'},
  {ext:'Cloudflare Edge',purpose:'tunnel',        src:'cloudflared'},
  {ext:'Resend SMTP',   purpose:'transactional email',src:'authentik-server'}
] AS x
MERGE (e:External {name:x.ext})
MERGE (src:Container {name:x.src})
MERGE (src)-[c:CALLS_EXTERNAL]->(e) SET c.purpose=x.purpose;

// ---------- Risks (from SERVICE-MAP.md §11 + §13 live reconciliation) --------
UNWIND [
  {id:'R1', sev:'high',    title:'Duplicate crowdsec middleware, two different LAPI keys', affects:['traefik','crowdsec']},
  {id:'R2', sev:'resolved',title:'(RESOLVED 2026-07-03) memory DB pgvector fixed — postgres now pgvector/pgvector:pg16, vector 0.8.2', affects:['postgres']},
  {id:'R3', sev:'medium',  title:'vmalert blackholed - 16 rules notify nowhere', affects:['vmalert']},
  {id:'R4', sev:'high',    title:'honeypot+threat-map+decks+context+coders hand-deployed, NOT in Ansible (route file host-only, restored 2026-07-03)', affects:['traefik','threat-map','honeypot','decks-nginx','timeline-context-api']},
  {id:'R5', sev:'low',     title:'cloudflared config.yml is dead config (token-managed)', affects:['cloudflared']},
  {id:'R6', sev:'medium',  title:'Alloy scrape targets reference stale topology (security-infra-pod)', affects:['alloy']},
  {id:'R7', sev:'low',     title:'dep-health loki probe hits Tempo port 3200 not Loki 3100', affects:['loki','tempo']},
  {id:'R8', sev:'high',    title:'Redis unauthenticated (no requirepass)', affects:['redis']},
  {id:'R9', sev:'medium',  title:'Two app-owned Postgres superusers (aistack, authentik)', affects:['ai-stack-postgres','authentik-postgres']},
  {id:'R10',sev:'medium',  title:'pg_hba trust-on-localhost masks password drift', affects:['postgres','ai-stack-postgres','authentik-postgres']},
  {id:'R11',sev:'low',     title:'security-pod empty shell squatting ports', affects:['security-pod']},
  {id:'R12',sev:'high',    title:'Root fs @90% + unrotated podman ctr.log (1.8GB Loki log -> ENOSPC crash of loki+tempo 2026-07-03 06:10)', affects:['loki','tempo']},
  {id:'R13',sev:'low',     title:'Orphan reclaimable data: postgres-alpine-bak 830MB, qdrant-spike, nomic-embed, llama-embed', affects:['qdrant-spike','nomic-embed','llama-embed']}
] AS rk
MERGE (risk:Risk {id:rk.id}) SET risk.severity=rk.sev, risk.title=rk.title
WITH risk, rk
UNWIND rk.affects AS aff
  OPTIONAL MATCH (c:Container {name:aff})
  OPTIONAL MATCH (p:Pod {name:aff})
  FOREACH (_ IN CASE WHEN c IS NOT NULL THEN [1] ELSE [] END | MERGE (risk)-[:AFFECTS]->(c))
  FOREACH (_ IN CASE WHEN p IS NOT NULL THEN [1] ELSE [] END | MERGE (risk)-[:AFFECTS]->(p));

// =============================================================================
// VERIFY (optional — run after load):
//   MATCH (n) WHERE any(l IN labels(n) WHERE l IN ['Host','Network','Pod','Container','Datastore','Database','Role','Route','Middleware','External','Risk']) RETURN labels(n)[0] AS label, count(*) ORDER BY label;
//   MATCH (r:Route)-[x:ROUTES_TO]->(c:Container) RETURN r.host, c.name, x.port ORDER BY r.host;
//   MATCH (a:Container)-[d:DEPENDS_ON]->(b) RETURN a.name, d.purpose, b.name;
//   MATCH (risk:Risk)-[:AFFECTS]->(c) RETURN risk.severity, risk.title, collect(c.name);
// =============================================================================
