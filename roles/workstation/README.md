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
| podman quadlets | 3 | `files/containers/` → `~/.config/containers/systemd/` |
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

## Secrets

No credentials live in this role. `neo4j-sync.sh` and `pg-sync.sh` source them
at runtime from `~/scripts/secrets.env`, which is `chmod 600`, gitignored, and
**not** deployed by Ansible. If you want that file managed too, template it from
`vault.yml` rather than committing it.
