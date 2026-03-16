# Git-Crypt Encryption Map

## Philosophy

**PUBLIC (free tier):** A working minimal skeleton. Clone it, run it, get a basic
stack up — Traefik, OpenWebUI, basic monitoring. No enterprise tuning, no advanced
integrations. Shows WHAT components exist and that they CAN be deployed. Modular —
users add layers of complexity as they grow.

**ENCRYPTED (premium tier):** The full enterprise wiring. Tuned memory/CPU values,
multi-pod architecture, OTEL pipelines, SSO integration, CrowdSec security stack,
Cloudflare zero-trust, trading systems, 20+ Grafana dashboards with custom panels,
backup orchestration. Months of integration work that turns building blocks into a
production platform.

**Principle:** You know it exists. You can see the file names, the role structure,
the config schemas. But the contents that make it all work together — that's premium.

---

## PUBLIC — Working Minimal Skeleton

These files let someone deploy a basic stack from scratch.

```
# ─────────────────────────────────────────────
# Project Structure & Metadata
# ─────────────────────────────────────────────
README.md                          # Project overview, component list, quick-start guide
LICENSE                            # License file
.gitignore
.gitattributes                     # git-crypt filter definitions
.dockerignore
ansible.cfg                        # Standard Ansible config
requirements.yml                   # Ansible Galaxy dependencies
package.json                       # Node dependency metadata
Dockerfile                         # Ansible container build (educational)

# ─────────────────────────────────────────────
# Inventory (sanitized example)
# ─────────────────────────────────────────────
inventory/hosts                    # Example with placeholder IPs

# ─────────────────────────────────────────────
# Site playbook (role list only — shows the modular structure)
# ─────────────────────────────────────────────
site.yml                           # Shows what roles exist and their order

# ─────────────────────────────────────────────
# Defaults — minimal config schemas (NO tuned values)
# Shows what's configurable, not how it's tuned
# ─────────────────────────────────────────────
roles/base/defaults/main.yml
roles/container-runtime/defaults/main.yml
roles/shared-services/defaults/main.yml
roles/monitoring/defaults/main.yml
roles/security/defaults/main.yml
roles/authentication/defaults/main.yml
roles/ai-stack/defaults/main.yml
roles/management/defaults/main.yml
roles/frontend/defaults/main.yml
roles/backup/defaults/main.yml
roles/app_deployment/defaults/main.yml
roles/backend/defaults/main.yml
roles/cloudflare/defaults/main.yml
roles/cloudflared/defaults/main.yml
roles/claude-prep/defaults/main.yml
roles/gemini-prep/defaults/main.yml
roles/journey-tracker/defaults/main.yml
roles/worldview/defaults/main.yml
roles/mcp-servers/defaults/main.yml
roles/trading/defaults/main.yml

# ─────────────────────────────────────────────
# Handlers — restart triggers (no logic, just service names)
# ─────────────────────────────────────────────
roles/*/handlers/main.yml          # All handler files

# ─────────────────────────────────────────────
# Standalone Dockerfiles & package manifests
# (Open source component builds — no integration logic)
# ─────────────────────────────────────────────
roles/trading/files/backtrader/Dockerfile
roles/trading/files/backtrader/requirements.txt
roles/trading/files/lightweight-charts/Dockerfile
roles/trading/files/lightweight-charts/package.json

# ─────────────────────────────────────────────
# Docker Compose references (standalone, non-Ansible)
# ─────────────────────────────────────────────
docker-compose.yml
docker-compose-openwebui.yml

# ─────────────────────────────────────────────
# Simple utility playbooks (non-integration)
# ─────────────────────────────────────────────
create-user.yml                    # Basic user creation
setup-podman-socket.yml            # Podman socket setup
upgrade-podman.yml                 # Podman upgrade steps

# ─────────────────────────────────────────────
# Workers — standalone Cloudflare Workers apps
# ─────────────────────────────────────────────
workers/webhook-handler/package.json
workers/webhook-handler/tsconfig.json
workers/webhook-handler/wrangler.toml
workers/webhook-handler/src/index.ts
workers/webhook-handler/src/types/env.d.ts
workers/webhook-handler/src/lib/response.ts

# ─────────────────────────────────────────────
# Dashboard Catalog (names + descriptions only)
# ─────────────────────────────────────────────
# NOTE: A DASHBOARD_CATALOG.md will be created listing
# all dashboard names and what they monitor — but the
# actual JSON files are encrypted.

# ─────────────────────────────────────────────
# Claude skills (structure only, educational)
# ─────────────────────────────────────────────
.claude/skills/add-poi/SKILL.md
.claude/skills/spy-options-trading/SKILL.md
```

---

## ENCRYPTED — Full Enterprise Platform

Everything below requires a decryption key to access.
File names are visible; contents are binary blobs.

```
# ═══════════════════════════════════════════════════════════
# GLOBAL CONFIGURATION (tuned values, pod definitions)
# ═══════════════════════════════════════════════════════════
all.yml                            # Tuned memory, CPU shares, pod topology, endpoints
model_tiers.yml                    # AI model pricing/routing strategy

# ═══════════════════════════════════════════════════════════
# ARCHITECTURE & DESIGN DOCUMENTS
# ═══════════════════════════════════════════════════════════
architecture.drawio                # Detailed architecture diagrams
architecture2.drawio               # Additional architecture diagrams
docs/trading-system-guide.md       # Trading system documentation

# ═══════════════════════════════════════════════════════════
# GRAFANA DASHBOARDS (full panel JSON)
# ═══════════════════════════════════════════════════════════
dashboards/agent-performance.json
dashboards/ai-agent-observatory.json
dashboards/ai-provider-comparison.json
dashboards/ai-stack.json
dashboards/cli-session-replay.json
dashboards/cloudflare.json
dashboards/container-metrics.json
dashboards/container-overview.json
dashboards/container-status.json
dashboards/crowdsec-blocklist.json
dashboards/crowdsec-threats.json
dashboards/dependency-health.json
dashboards/e2e-traces.json
dashboards/host-incident.json
dashboards/infrastructure.json
dashboards/ingress.json
dashboards/project-analytics.json
dashboards/security-auth.json
dashboards/session-explorer.json
dashboards/session-replay.json
dashboards/threat-intelligence.json
dashboards/trading-iv.json
dashboards/trading-iv-overview.json
dashboards/trivy-cve-detail.json
dashboards/trivy-vulnerabilities.json
dashboards/user-experience.json
dashboards/dashboards/12331_rev1.json
dashboards/dashboards/16337_rev13.json
dashboards/dashboards/16337_rev14.json
dashboards/dashboards/17080_rev1.json
dashboards/dashboards/17813_rev2.json
dashboards/dashboards/21112_rev2.json
roles/monitoring/files/dashboards/*.json       # All provisioned dashboard JSON

# ═══════════════════════════════════════════════════════════
# SHARED SERVICES — Traefik + DB + CrowdSec plugin wiring
# ═══════════════════════════════════════════════════════════
roles/shared-services/tasks/main.yml
roles/shared-services/tasks/trading-schema.yml
roles/shared-services/templates/traefik.yml.j2
roles/shared-services/templates/traefik-dynamic.yml.j2

# ═══════════════════════════════════════════════════════════
# MONITORING — 5-pod OTEL pipeline, scrapers, crons
# ═══════════════════════════════════════════════════════════
roles/monitoring/tasks/main.yml
roles/monitoring/tasks/grafana-oidc.yml
roles/monitoring/tasks/grafana-alerting.yml
roles/monitoring/tasks/image-renderer.yml
roles/monitoring/tasks/checkmk-setup.yml
roles/monitoring/templates/alloy-config.alloy.j2
roles/monitoring/templates/grafana-dashboards.yml.j2
roles/monitoring/templates/grafana-datasources.yml.j2
roles/monitoring/templates/loki-config.yml.j2
roles/monitoring/templates/tempo-config.yml.j2
roles/monitoring/templates/vmscrape.yml.j2
roles/monitoring/templates/prometheus-alerts.yml.j2
roles/monitoring/templates/prometheus-recording.yml.j2
roles/monitoring/templates/authentik-events-metrics.py.j2
roles/monitoring/templates/cloudflare-zone-metrics.py.j2
roles/monitoring/templates/cloudflare-access-metrics.py.j2
roles/monitoring/templates/crowdsec-geo-feed.py.j2
roles/monitoring/templates/trivy-scan-metrics.py.j2
roles/monitoring/templates/telegram-notify.sh.j2
roles/monitoring/templates/telegram-notify.conf.j2
roles/monitoring/templates/daily-services-check.sh.j2
roles/monitoring/templates/daily-security-check.sh.j2
roles/monitoring/templates/daily-market-notify.sh.j2
roles/monitoring/templates/daily-ingest.sh.j2
roles/monitoring/templates/dep-health-check.sh.j2
roles/monitoring/files/podman-metrics.sh
roles/monitoring/files/ivscan-daily.py
roles/monitoring/files/position-sync.py

# ═══════════════════════════════════════════════════════════
# SECURITY — Firewall, CrowdSec, Trivy, Tetragon, Squid
# ═══════════════════════════════════════════════════════════
roles/security/tasks/main.yml
roles/security/tasks/crowdsec.yml
roles/security/templates/firewall.sh.j2
roles/security/templates/crowdsec-acquis.yaml.j2
roles/security/templates/crowdsec-profiles.yaml.j2
roles/security/templates/crowdsec-http-notifier.yaml.j2
roles/security/templates/crowdsec-middleware.yml.j2
roles/security/templates/crowdsec-daily-report.sh.j2
roles/security/templates/threat-feed-checker.py.j2
roles/security/templates/fail2ban-metrics.sh.j2
roles/security/templates/trivy-scan.sh.j2
roles/security/templates/security-check.sh.j2
roles/security/templates/squid.conf.j2
roles/security/templates/squid-report.py.j2
roles/security/templates/jail.local.j2
roles/security/templates/ossec.conf.j2
roles/security/templates/traefik-logrotate.j2
roles/security/templates/wazuh-agent-ossec.conf.j2
roles/security/templates/opensearch_dashboards.yml.j2
roles/security/templates/tetragon-policy.yaml.j2
roles/security/files/tetragon/01-file-integrity.yaml
roles/security/files/tetragon/02-rootkit-malware.yaml
roles/security/files/tetragon/03-network-monitoring.yaml
roles/security/files/tetragon/04-zero-trust-enforce.yaml

# ═══════════════════════════════════════════════════════════
# AUTHENTICATION — Authentik SSO full integration
# ═══════════════════════════════════════════════════════════
roles/authentication/tasks/main.yml
roles/authentication/tasks/sso-setup.yml
roles/authentication/tasks/cloudflare-integration.yml

# ═══════════════════════════════════════════════════════════
# AI STACK — OpenWebUI + LiteLLM + n8n + SearXNG wiring
# ═══════════════════════════════════════════════════════════
roles/ai-stack/tasks/main.yml
roles/ai-stack/tasks/litellm-setup.yml
roles/ai-stack/tasks/openwebui-setup.yml
roles/ai-stack/tasks/openwebui-branding.yml
roles/ai-stack/tasks/authentik-apps.yml
roles/ai-stack/tasks/authentik-branding.yml
roles/ai-stack/tasks/seed-webui-db.yml
roles/ai-stack/templates/litellm-config.yml.j2
roles/ai-stack/templates/searxng-settings.yml.j2
roles/ai-stack/templates/searxng-limiter.toml.j2
roles/ai-stack/templates/seed-webui-config.py.j2
roles/ai-stack/files/openwebui-custom.css

# ═══════════════════════════════════════════════════════════
# CLOUDFLARE — Tunnel, DNS, Zero-Trust Access
# ═══════════════════════════════════════════════════════════
roles/cloudflare/tasks/main.yml
roles/cloudflare/tasks/tunnel.yml
roles/cloudflare/tasks/tunnel-config.yml
roles/cloudflare/tasks/dns.yml
roles/cloudflare/tasks/dns-record.yml
roles/cloudflare/tasks/access.yml
roles/cloudflare/tasks/zone-settings.yml
roles/cloudflare/tasks/traefik-acme.yml
roles/cloudflare/templates/cloudflared-config.yml.j2
roles/cloudflare/templates/traefik-acme.yml.j2
roles/cloudflare/templates/traefik-dynamic.yml.j2
roles/cloudflared/tasks/main.yml
roles/cloudflared/templates/cloudflared-config.yml.j2

# ═══════════════════════════════════════════════════════════
# MCP SERVERS — Build + deploy pipeline
# ═══════════════════════════════════════════════════════════
roles/mcp-servers/tasks/main.yml
roles/mcp-servers/tasks/telegram-gateway.yml
roles/mcp-servers/tasks/context7-mcp.yml
roles/mcp-servers/tasks/google-docs-mcp.yml
roles/mcp-servers/tasks/ib-mcp.yml
roles/mcp-servers/tasks/n8n-mcp.yml
roles/mcp-servers/tasks/scrapy-mcp.yml
roles/mcp-servers/templates/mcp_settings.json.j2

# ═══════════════════════════════════════════════════════════
# INFRASTRUCTURE ROLES — Deploy + configure logic
# ═══════════════════════════════════════════════════════════
roles/base/tasks/main.yml
roles/base/templates/vps-aliases.sh.j2
roles/container-runtime/tasks/main.yml
roles/container-runtime/templates/podman.initd.j2
roles/container-runtime/templates/podman-compose-wrapper.sh.j2
roles/container-runtime/templates/policy.json.j2
roles/container-runtime/templates/registries.conf.j2
roles/container-runtime/templates/storage.conf.j2
roles/management/tasks/main.yml
roles/frontend/tasks/main.yml
roles/frontend/templates/index.html.j2
roles/frontend/templates/nginx.conf.j2
roles/app_deployment/tasks/main.yml
roles/backend/tasks/main.yml
roles/claude-prep/tasks/main.yml
roles/claude-prep/tasks/transfer-claude-environment.yml
roles/claude-prep/tasks/transfer-session-history.yml
roles/claude-prep/tasks/transfer-workspace-agents.yml
roles/gemini-prep/tasks/main.yml
roles/journey-tracker/tasks/main.yml
roles/journey-tracker/templates/nginx.conf.j2
roles/journey-tracker/templates/traefik-journey-tracker.yml.j2
roles/worldview/tasks/main.yml
roles/worldview/templates/worldview.env.j2

# ═══════════════════════════════════════════════════════════
# BACKUP/RESTORE — Orchestration
# ═══════════════════════════════════════════════════════════
roles/backup/tasks/main.yml
roles/backup/tasks/setup.yml
roles/backup/tasks/backup.yml
roles/backup/tasks/restore.yml
roles/backup/templates/backup.sh.j2
roles/backup/templates/restore.sh.j2

# ═══════════════════════════════════════════════════════════
# TRADING — Strategies, data pipeline, crons
# ═══════════════════════════════════════════════════════════
roles/trading/tasks/main.yml
roles/trading/tasks/backtrader.yml
roles/trading/tasks/data-ingestion.yml
roles/trading/tasks/cron-jobs.yml
roles/trading/tasks/lightweight-charts.yml
roles/trading/tasks/backtest-schema.yml
roles/trading/files/ibkr-ohlc-ingest.py
roles/trading/files/mt5-ohlc-ingest.py
roles/trading/files/ohlc-resample.py
roles/trading/files/runner.py
roles/trading/files/backtrader/runner.py
roles/trading/files/cpcv_walkforward.py
roles/trading/files/exhaustion_confluence.py
roles/trading/files/exhaustion_confluence_v2.py
roles/trading/files/exhaustion_confluence_v2b.py
roles/trading/files/exhaustion_confluence_v3.py
roles/trading/files/exhaustion-trades.html
roles/trading/files/exhaustion-viewer.html
roles/trading/files/lightweight-charts/app.js
roles/trading/files/lightweight-charts/index.html
roles/trading/files/lightweight-charts/style.css
roles/trading/files/lightweight-charts/nginx.conf

# ═══════════════════════════════════════════════════════════
# UTILITY PLAYBOOKS & TOOLS
# ═══════════════════════════════════════════════════════════
hardening.yml
main.yml
claude-restore.yml
claude-transfer.yml
migrate-cgroups-v2.yml
migrate-dev-environment.yml
transfer-workspace-agents.yml
backend-info.txt.j2
services-info.txt.j2
tools/claude-approval-hook.js
tools/generate_architecture.py
tools/dca_backtest_chart.py
tools/dca_simulation.py
tools/stop_recovery.py
tools/yt-transcript.py
tools/yt-transcript-worker/worker.js
tools/yt-transcript-worker/wrangler.toml
tools/yt-transcript-worker/.wrangler/cache/cf.json
tools/package.json
workers/webhook-handler/src/lib/authentik.ts
workers/webhook-handler/src/routes/admin.ts
workers/webhook-handler/src/routes/github.ts
workers/webhook-handler/src/routes/health.ts
workers/webhook-handler/src/routes/stripe.ts
```

---

## Summary

| Category | Count | Visibility | Why |
|----------|-------|------------|-----|
| README + license | 2 | **PUBLIC** | Attract users, explain the project |
| site.yml (role list) | 1 | **PUBLIC** | Shows modular structure |
| Defaults (config schemas) | ~20 | **PUBLIC** | Shows what's tunable, no values |
| Handlers (restart triggers) | ~10 | **PUBLIC** | No logic, just names |
| Dockerfiles + manifests | ~5 | **PUBLIC** | Open source builds |
| Docker Compose refs | 2 | **PUBLIC** | Quick-start alternative |
| Utility playbooks (basic) | 3 | **PUBLIC** | User management, upgrades |
| Workers (standalone) | 4 | **PUBLIC** | Independent apps |
| Inventory (example) | 1 | **PUBLIC** | Sanitized template |
| Claude skills | 2 | **PUBLIC** | Educational |
| **all.yml (tuned config)** | **1** | **ENCRYPTED** | Enterprise tuning IP |
| **Architecture diagrams** | **2** | **ENCRYPTED** | Detailed design IP |
| **Dashboards (40+ JSON)** | **~40** | **ENCRYPTED** | Panel/query design IP |
| **Task files (all roles)** | **~75** | **ENCRYPTED** | Deployment orchestration IP |
| **Templates (all roles)** | **~60** | **ENCRYPTED** | Service wiring IP |
| **Scripts + strategies** | **~25** | **ENCRYPTED** | Custom tooling IP |
| **Utility playbooks (advanced)** | **~10** | **ENCRYPTED** | Migration/hardening IP |
| **Tools** | **~10** | **ENCRYPTED** | Integration utilities |
| **Docs (detailed)** | **1** | **ENCRYPTED** | Trading system guide |

**~50 public files** — skeleton, schemas, structure
**~234 encrypted files** — the full enterprise platform

---

## What the Free User Experience Looks Like

```
$ git clone https://github.com/Kwaku9/vps_setup.git
$ ls roles/
ai-stack/  authentication/  backup/  base/  cloudflare/  container-runtime/
frontend/  management/  mcp-servers/  monitoring/  security/  shared-services/
trading/  ...

$ cat roles/monitoring/defaults/main.yml     # ← readable config schema
$ cat roles/monitoring/tasks/main.yml        # ← binary blob (encrypted)
$ cat dashboards/infrastructure.json         # ← binary blob (encrypted)

$ cat site.yml                               # ← see the role order
$ cat README.md                              # ← understand the vision
```

They see the WHAT. They pay for the HOW.
