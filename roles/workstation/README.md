# `workstation` role

Manages the **Fedora laptop**, not the VPS. Everything here is user-level state
under `$HOME` — `systemd --user` units, rootless podman quadlets, and the helper
scripts those units call. No task needs `sudo`.

    tools/ansible-workstation.sh build    # once
    tools/ansible-workstation.sh check    # drift report (--check --diff)
    tools/ansible-workstation.sh apply    # converge

## Why a separate controller container

VPS deploys run through `localhost/ansible-vps:latest`, which is
`python:3.12-alpine`. That image **cannot** run this role: Alpine uses OpenRC
rather than systemd, so it ships no `systemctl` and none is installable
(`apk search systemd` is empty). Ansible's `systemd_service` module shells out
to `systemctl`, so the controller for a systemd host has to be systemd-based.

`Dockerfile.workstation` builds a Fedora-based sibling —
`localhost/ansible-workstation:latest` — pinned to the same `ansible-core`
(2.20.3) so playbook behaviour matches the VPS controller.

It manages the *host's* user services, not its own, because
`tools/ansible-workstation.sh` bind-mounts `$HOME` and `$XDG_RUNTIME_DIR` and
runs with `--userns=keep-id`. `systemctl --user` inside the container then
speaks to the laptop's real user manager. Those mounts are load-bearing; don't
`podman run` the image without them.

Keeping Ansible in a container also keeps it out of `~/.local/bin`, where the
previous `ansible*` entries rotted into stubs that failed on every invocation
while still satisfying `command -v`.

## What it covers

| Kind | Count | Location |
|---|---|---|
| `systemd --user` units | 22 | `files/systemd/` → `~/.config/systemd/user/` |
| podman quadlets | 4 | `files/containers/` → `~/.config/containers/systemd/` |
| helper scripts | 5 | `files/bin/` → `~/.local/bin/`, `files/scripts/` → `~/scripts/` |

Units owned by *other* repos are deliberately out of scope — the role does not
deploy or touch them:

- `ai-tool-navigator{,-monitor}.{service,timer}` → `ai-tool-navigator/deploy/`
- `pineapple-recon.{service,timer}` → `pineapple-recon-logger/`
- `archivist-pg.container` → `archivist/deploy/`
- `rerank-gpu.container` → `vps_setup/tools/fedora-gpu-rerank/`

## State is descriptive, not aspirational

Every `enabled`/`state` value in `defaults/main.yml` was read off the running
machine on 2026-08-07, so a converge run against an unchanged laptop is a no-op.

Several units are `disabled` **on purpose**. Do not "fix" them:

- `ptt-computer-use` — the 6GB GPU cannot host the PTT stack and this at once.
- `sync-claude-timeline` — now run on demand via `/update-timeline`.
- `vps-tts-daemon` — superseded by `vps-tts-tunnel`.
- `neo4j-vps-tunnel` — superseded by the tailnet route.
- `buildfolio-heatmap` — run by hand when the portfolio needs it.

## Quadlets are deployed but not state-managed

The `.container` files are written and the generator reloaded, but the services
they generate are never enabled/started/restarted by this role. `whisper-gpu`
backs daily push-to-talk and `llama-embed-gpu` backs OpenWebUI's RAG embedding;
a converge run is the wrong moment to cycle either. Restart them deliberately:

    systemctl --user restart whisper-gpu.service

## ollama.container, and the two things around it that this role does NOT own

Added 2026-09-20. It is the answer model for the Knowledge Hub demo, and it
replaced a bare `podman run` whose entire configuration existed only inside the
running container: `restart: no`, no unit file, nothing on disk. A stop would
have meant rebuilding it from memory.

Two pieces of its setup sit outside this role, and both will silently break the
demo if they are changed without the other half being updated:

1. **`tailscale serve` maps `:8445` → `127.0.0.1:11434`.** That is host state,
   not a file, and nothing here manages it. The container binds loopback only
   on purpose, so if that mapping is dropped the phone loses the model even
   though the container is perfectly healthy. Check with `tailscale serve status`.

2. **`OLLAMA_ORIGINS` is a browser allowlist, not a convenience.** The demo is a
   static page on a *different* origin calling this server directly, so every
   origin serving it has to be named in the quadlet or the preflight is refused.
   This bit on 2026-09-20: the demo moved to `rag.demo.nucybersec.com` while the
   allowlist still named only the old `web.app` host, so the model was reachable,
   healthy, and returned 403 to every browser. Anything that changes where the
   demo is served has to change this list in the same pass.

`OLLAMA_KEEP_ALIVE=30s` is deliberate and is about VRAM, not latency. The 6GB
GPU already carries the embedder, whisper and the faces model; the default
holds a model resident for five minutes after the last token, and this ran at
`30m`, so one question parked 1.7GB for half an hour. Measured after the change:
1798 MiB idle → 3526 MiB during a question → 1798 MiB again 45s later.

## Secrets

No credentials live in this role. `neo4j-sync.sh` and `pg-sync.sh` source them
at runtime from `~/scripts/secrets.env`, which is `chmod 600`, gitignored, and
**not** deployed by Ansible. If you want that file managed too, template it from
`vault.yml` rather than committing it.
