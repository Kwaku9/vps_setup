# MCP Servers Role

Deploys and configures Model Context Protocol (MCP) servers for Claude Code CLI integration.

## Overview

This role:
1. Builds container images from source directories
2. Deploys MCP server containers (HTTP or stdio transport)
3. Generates `/root/.claude/mcp_settings.json` dynamically
4. Configures health checks and monitoring

## Requirements

- `claude-prep` role must run first (installs Claude CLI, creates /workspace)
- `container-runtime` role (Podman)
- MCP server source code in `/workspace/` directories

## Usage

### Full Deployment
```bash
ansible-playbook -i hosts site.yml --tags "mcp"
```

### Individual Servers
```bash

# Deploy only Google Docs MCP
ansible-playbook -i hosts site.yml --tags "mcp-google"

# Regenerate config only
ansible-playbook -i hosts site.yml --tags "mcp-config"
```

### Force Rebuild
```bash
ansible-playbook -i hosts site.yml --tags "mcp" -e "mcp_build.force_rebuild=true"
```

## Available Tags

| Tag | Description |
|-----|-------------|
| `mcp` | All MCP server tasks |
| `mcp-google` | Google Docs/Drive MCP |
| `mcp-context7` | Context7 protocol MCP |
| `mcp-ib` | Interactive Brokers trading MCP |
| `mcp-trade` | Trade replay/analysis MCP |
| `mcp-scrapy` | Scrapy web scraping MCP |
| `mcp-whisper` | Whisper speech-to-text MCP |
| `mcp-voice` | Voice hooks integration MCP |
| `mcp-config` | Generate mcp_settings.json only |
| `mcp-build` | Build container images only |
| `mcp-health` | Health checks only |

## Configuration

### all.yml Variables

```yaml
mcp_servers:
  workspace_base: "/workspace"
  config_dir: "/root/.claude"
  data_dir: "/opt/podman-data/mcp"
  network: "enterprise_network"

  servers:
mcp_build:
  force_rebuild: false
  no_cache: false
  pull: true

mcp_runtime:
  restart_policy: "unless-stopped"
  memory_limit: "512m"
```

### Server Transport Types

**HTTP Transport (SSE):**
- Server runs as HTTP endpoint
- Claude connects via Server-Sent Events
- More reliable for containerized deployments
- Config: `type: "sse", url: "http://127.0.0.1:PORT/sse"`

**stdio Transport:**
- Server runs via container exec
- Claude pipes stdin/stdout to container
- Better for simple single-process servers
- Config: `command: "podman", args: ["exec", "-i", "container", ...]`

## Directory Structure

```
roles/mcp-servers/
├── defaults/
│   └── main.yml           # Default server configurations
├── tasks/
│   ├── main.yml           # Main orchestration
│   ├── google-docs-mcp.yml
│   ├── context7-mcp.yml
│   ├── ib-mcp.yml
│   ├── trade-replay-mcp.yml
│   ├── scrapy-mcp.yml
│   ├── whisper-mcp.yml
│   └── voice-hooks-mcp.yml
├── templates/
│   └── mcp_settings.json.j2  # Dynamic Claude config
├── handlers/
│   └── main.yml
└── README.md
```

## Verification

After deployment:

```bash
# List configured MCP servers
claude mcp list

# Check container status
podman ps --filter "name=mcp"

# Test HTTP endpoint
curl http://127.0.0.1:3000/health

# View container logs
```

## Troubleshooting

### Container Build Fails
```bash
# Check source directory exists

# Force rebuild
```

### Health Check Fails
```bash
# Check container is running
podman ps -a | grep mcp

# View logs

# Test endpoint manually
curl -v http://127.0.0.1:3000/health
```

### MCP Not Connecting
```bash
# Verify config
cat /root/.claude/mcp_settings.json

# Test stdio connection
podman exec -i trade-replay-mcp python /app/server.py /data/trades.csv

# Restart Claude session
# (Claude CLI auto-reloads mcp_settings.json)
```

## Dependencies

This role depends on:
- `claude-prep` - Creates workspace and installs Claude CLI
- `container-runtime` - Installs Podman

## License

MIT
