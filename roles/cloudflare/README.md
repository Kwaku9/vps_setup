# Cloudflare Role

Ansible role for Cloudflare Tunnel integration providing secure public access to internal services without exposing ports to the internet.

## Architecture

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                    Cloudflare Edge                       │
                    │              (TLS termination, DDoS, WAF)                │
                    └─────────────────────────────────────────────────────────┘
                                              │
                                              │ QUIC (outbound only)
                                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              VPS (Alpine Linux)                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    cloudflared container                             │    │
│  │                    (10.89.0.x on enterprise_network)                 │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│         Routes directly to services (bypasses Traefik)                       │
│                                    │                                         │
│    ┌───────────┬───────────┬───────────┬───────────┬───────────┐           │
│    ▼           ▼           ▼           ▼           ▼           ▼           │
│ Grafana    Portainer    n8n       Open WebUI   Prometheus   CheckMK        │
│ :3000      :9443        :5678     :8080        :9090        :5000          │
│                                                                              │
│ LiteLLM    Dockge     Traefik    Kokoro TTS   Portal       Authentik       │
│ :4000      :5001      :8080      :8880        :80          :9000           │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- All traffic routed through Cloudflare (no ports exposed to internet except SSH)
- cloudflared makes outbound connections only (no inbound firewall rules needed)
- Services accessed via container IPs on enterprise_network
- TLS terminated at Cloudflare Edge (internal traffic is HTTP)

## Public URLs

| Service | URL | Internal Target |
|---------|-----|-----------------|
| Portal | https://portal.aicortex.cloud | nginx:80 |
| Grafana | https://grafana.aicortex.cloud | grafana:3000 |
| n8n | https://n8n.aicortex.cloud | n8n-claude:5678 |
| Open WebUI | https://chat.aicortex.cloud | open-webui:8080 |
| Portainer | https://portainer.aicortex.cloud | portainer:9443 |
| Prometheus | https://prometheus.aicortex.cloud | prometheus:9090 |
| Authentik | https://auth.aicortex.cloud | authentik-server:9000 |
| CheckMK | https://checkmk.aicortex.cloud | checkmk:5000 |
| LiteLLM | https://litellm.aicortex.cloud | litellm:4000 |
| Dockge | https://dockge.aicortex.cloud | dockge:5001 |
| Traefik | https://traefik.aicortex.cloud | traefik:8080 |
| Kokoro TTS | https://tts.aicortex.cloud/web/ | kokoro-tts:8880 |

---

## Operating Modes

### Mode 1: Cloudflare Tunnel (Current)

Public access via Cloudflare with DDoS protection, WAF, and caching.

**DNS Configuration:**
```
aicortex.cloud → CNAME → <tunnel-id>.cfargotunnel.com
*.aicortex.cloud → CNAME → aicortex.cloud
```

**Pros:**
- No ports exposed (except SSH 22)
- DDoS protection included
- Global CDN/caching
- Free SSL certificates
- Zero Trust security options

**Cons:**
- Dependent on Cloudflare
- Slight latency increase
- Must update tunnel config when container IPs change

---

### Mode 2: SSH Tunneling (Fallback)

Direct access via SSH port forwarding. No public exposure.

**DNS Configuration:**
```
aicortex.cloud → A → 72.61.0.187 (VPS IP)
```

**Access Method:**
```powershell
# Windows PowerShell - tunnel multiple services
ssh -L 3000:127.0.0.1:3000 `
    -L 5678:127.0.0.1:5678 `
    -L 9090:127.0.0.1:9090 `
    -L 9443:127.0.0.1:9444 `
    -L 5001:127.0.0.1:5001 `
    -L 8081:127.0.0.1:8081 `
    root@72.61.0.187
```

```bash
# Linux/macOS
ssh -L 3000:127.0.0.1:3000 \
    -L 5678:127.0.0.1:5678 \
    -L 9090:127.0.0.1:9090 \
    -L 9443:127.0.0.1:9444 \
    -L 5001:127.0.0.1:5001 \
    -L 8081:127.0.0.1:8081 \
    root@72.61.0.187
```

Then access via `http://localhost:<port>`.

**Pros:**
- No external dependencies
- Full control
- Works offline from Cloudflare

**Cons:**
- No public access
- Must maintain SSH connection
- No DDoS protection if ports opened

---

## Enabling the Tunnel

### Prerequisites

1. **Cloudflare Account** with domain added
2. **API Token** with Zone:DNS:Edit permissions
3. **Tunnel Token** from cloudflared CLI

### Initial Setup (One-time)

```bash
# 1. Install cloudflared locally
brew install cloudflared  # macOS
# or download from https://github.com/cloudflare/cloudflared/releases

# 2. Authenticate with Cloudflare
cloudflared tunnel login

# 3. Create tunnel
cloudflared tunnel create alpine-vps

# 4. Get tunnel token (save this!)
cloudflared tunnel token alpine-vps

# 5. Get tunnel ID
cloudflared tunnel list
```

### Configure Vault

Add to `group_vars/alpine_servers/vault.yml`:
```yaml
cloudflare_email: "your-email@example.com"
cloudflare_api_token: "your-api-token"
cloudflare_zone_id: "your-zone-id"
cloudflare_tunnel_token: "your-tunnel-token"
cloudflare_account_id: "your-account-id"
domain_name: "aicortex.cloud"
```

### Deploy Tunnel

```bash
cd /workspace/vscode-projects/vps_setup
ansible-playbook -i inventory/hosts site.yml --tags cloudflare --ask-vault-pass
```

---

## Operating While Tunnel is Up

### Check Tunnel Status

```bash
# Container status
podman ps -a --filter name=cloudflared

# Tunnel health
curl -s http://127.0.0.1:2000/ready
# Returns: {"status":200,"readyConnections":4,"connectorId":"..."}

# Metrics
curl -s http://127.0.0.1:2000/metrics | grep cloudflared_tunnel

# View logs
podman logs -f cloudflared
```

### Update Tunnel Configuration

When container IPs change (after restart), update the tunnel config:

```bash
# 1. Get new IPs
for svc in grafana prometheus portainer n8n-claude open-webui; do
  ip=$(podman inspect $svc --format '{{range $k, $v := .NetworkSettings.Networks}}{{$v.IPAddress}}{{end}}')
  echo "$svc: $ip"
done

# 2. Update via Cloudflare API (or re-run Ansible)
ansible-playbook -i inventory/hosts site.yml --tags "cloudflare,tunnel" --ask-vault-pass
```

### Add New Service to Tunnel

1. Edit `roles/cloudflare/defaults/main.yml`:
```yaml
cloudflare_exposed_services:
  # ... existing services ...
  - name: myservice
    host: "myservice.{{ cf_domain }}"
    service_url: "http://myservice:8080"
    enabled: true
```

2. Create DNS record and update tunnel:
```bash
# Create CNAME record
curl -X POST "https://api.cloudflare.com/client/v4/zones/ZONE_ID/dns_records" \
  -H "Authorization: Bearer API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"type":"CNAME","name":"myservice","content":"aicortex.cloud","proxied":true}'

# Re-deploy tunnel config
ansible-playbook -i inventory/hosts site.yml --tags tunnel --ask-vault-pass
```

### Monitor Tunnel Performance

```bash
# Request count
curl -s http://127.0.0.1:2000/metrics | grep cloudflared_tunnel_total_requests

# Active connections
curl -s http://127.0.0.1:2000/metrics | grep cloudflared_tunnel_ha_connections

# Errors
curl -s http://127.0.0.1:2000/metrics | grep cloudflared_tunnel_request_errors

# Edge locations
curl -s http://127.0.0.1:2000/metrics | grep cloudflared_tunnel_server_locations
```

---

## Disconnecting the Tunnel

### Temporary Disconnect (Keep Config)

```bash
# Stop cloudflared container
podman stop cloudflared

# Services become inaccessible via public URLs
# Cloudflare returns 522 (Connection Timed Out)

# Restart when ready
podman start cloudflared
```

### Full Disconnect (Remove Tunnel)

```bash
# 1. Stop and remove container
podman stop cloudflared
podman rm cloudflared

# 2. Update DNS to point directly to VPS (for SSH tunneling)
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/ZONE_ID/dns_records/RECORD_ID" \
  -H "Authorization: Bearer API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"type":"A","name":"aicortex.cloud","content":"72.61.0.187","proxied":true}'

# 3. (Optional) Delete tunnel from Cloudflare
cloudflared tunnel delete alpine-vps
```

### What Happens When Tunnel Disconnects

| Component | Behavior |
|-----------|----------|
| Public URLs | Return Cloudflare 522 error |
| Internal services | Continue running normally |
| SSH access | Unaffected (port 22 still open) |
| DNS records | Remain pointing to tunnel (return 522) |

---

## Switching Back to SSH Tunneling

### Quick Switch (Keep Tunnel Config)

First, set your API token:
```bash
export CF_API_TOKEN="your-cloudflare-api-token"
```

1. Stop cloudflared:
```bash
podman stop cloudflared
```

2. Update DNS to A record:
```bash
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/a8990e0ce8a1d081ec1226ef3f8d49d2/dns_records/c3907e4a26c30ee46622368d7f31fda2" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"type":"A","name":"aicortex.cloud","content":"72.61.0.187","proxied":false}'
```

3. Access via SSH tunnel:
```bash
ssh -L 3000:127.0.0.1:3000 -L 5678:127.0.0.1:5678 root@72.61.0.187
```

### Restore Tunnel Later

1. Update DNS back to CNAME:
```bash
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/a8990e0ce8a1d081ec1226ef3f8d49d2/dns_records/c3907e4a26c30ee46622368d7f31fda2" \
  -H "Authorization: Bearer $CF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"type":"CNAME","name":"aicortex.cloud","content":"f9183e88-728a-4820-ac65-456f21cdb075.cfargotunnel.com","proxied":true}'
```

2. Start cloudflared:
```bash
podman start cloudflared
```

---

## Troubleshooting

### Tunnel Shows Connected but 522 Errors

Container IPs likely changed. Update tunnel config:
```bash
# Check current IPs
podman inspect grafana --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'

# Re-run Ansible to update
ansible-playbook -i inventory/hosts site.yml --tags tunnel --ask-vault-pass
```

### Tunnel Not Connecting

```bash
# Check logs
podman logs cloudflared

# Common issues:
# - Invalid tunnel token
# - Network connectivity (can container reach internet?)
# - Token expired (regenerate with `cloudflared tunnel token`)
```

### DNS Not Resolving

```bash
# Check Cloudflare DNS
dig @1.1.1.1 grafana.aicortex.cloud

# Verify record exists
curl -s "https://api.cloudflare.com/client/v4/zones/ZONE_ID/dns_records" \
  -H "Authorization: Bearer API_TOKEN" | grep grafana
```

### Service Accessible Internally but Not via Tunnel

```bash
# Test from cloudflared's network namespace
CPID=$(podman inspect cloudflared --format '{{.State.Pid}}')
nsenter -t $CPID -n curl -sI http://SERVICE_IP:PORT
```

---

## Configuration Reference

### Tunnel Config Location

- **Cloudflare Dashboard:** Zero Trust > Networks > Tunnels > alpine-vps-tunnel > Configure
- **API Endpoint:** `PUT /accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations`
- **Local Config:** `/opt/compose/cloudflare/config.yml` (overridden by API)

### Important IDs

| Resource | ID |
|----------|-----|
| Tunnel ID | `f9183e88-728a-4820-ac65-456f21cdb075` |
| Zone ID | `a8990e0ce8a1d081ec1226ef3f8d49d2` |
| Account ID | `d6d91bb928618f43d2655eb7b404acbb` |

### Ansible Tags

```bash
--tags cloudflare      # Full cloudflare role
--tags tunnel          # Tunnel deployment only
--tags dns             # DNS records only
--tags acme            # Traefik ACME only
```

---

## Security Notes

- Tunnel token stored as container environment variable
- All internal services bound to container network (not exposed to host)
- Only SSH (22) exposed to internet
- Cloudflare provides DDoS protection and WAF
- Consider enabling Cloudflare Access for additional authentication
