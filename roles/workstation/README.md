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

## local-rag-preview.service: the Knowledge Hub demo host

Added 2026-09-30, replacing a `systemd-run` **transient** unit
(`local-rag-evaluation.service`) that died on every reboot. That was fine while
it was a throwaway harness — `local-rag/ENGINE_EVALUATION.md` still tells you to
stop it when testing is finished — but it had quietly become the host for an app
installed on a phone home screen, and the `tailscale serve` `:8444` mapping
PERSISTS in tailscaled state while the transient unit did not. Net effect: a
home-screen icon that opened a dead page after any reboot, with nothing broken
enough to notice. `Linger=yes` is already set for this user, so an enabled user
unit does start at boot without a login.

Three details that matter if this is ever rewritten:

1. **The node path is the fnm DEFAULT ALIAS**
   (`~/.local/share/fnm/aliases/default/bin/node`), not the version-pinned path
   the transient unit had captured (`.../node-versions/v24.15.0/...`), which
   breaks on the next node upgrade. And not `node` off PATH: interactively that
   resolves to `/run/user/1000/fnm_multishells/<pid>_<ts>/bin/node`, which is
   per-shell and would not exist for a unit at all.
2. **`--host 127.0.0.1` is explicit and load-bearing.** `npm run preview` in
   that project's `package.json` is `vite preview --host 0.0.0.0`, which would
   put the app on every interface against the no-`0.0.0.0` estate policy. The
   phone reaches it only through `tailscale serve`.
3. **`ExecStartPre` asserts `dist/index.html` exists.** `vite preview` serves
   `dist/` and never builds, so without the guard the unit starts happily and
   serves 404s, which from a phone looks like a Tailscale or network fault.
   Control-tested: with the file moved away the unit fails with
   `exit-code` and the journal says `local-rag: dist/index.html missing -- run
   npm run build`. Read it with `journalctl --user-unit local-rag-preview` —
   note `--user-unit`, since `journalctl --user -u <name>` returns
   "No entries" for these units and looks like a logging fault when it is not.

The build has **three** HTML entries (`index.html`, `compare-engines.html`,
`measure-settled-memory.html`). Verified all three serve their own titles over
the tailnet, so nothing is being shadowed by an SPA fallback. Any replacement
static server has to resolve real files before any catch-all.

## gpu-lease-gate.service: admission control in front of Ollama

Added 2026-09-30. Ollama was the one GPU tenant that took the card without
asking. Everything else negotiates: ARCHIVIST's caption and embed passes hold a
machine-wide flock lease and check free VRAM first
(`archivist/src/archivist/gpu.py`), and `archivist-sync.sh` stops `rerank-gpu`
for its window and restores it on the way out. Ollama just loads, and on a full
card it does not fail -- it silently offloads to the CPU and keeps serving.

Measured 2026-09-30, with `archivist-vlm` mid-batch holding 3,978 MiB of the
6,144 MiB card: `qwen3:1.7b` loaded **3% on GPU / 97% on CPU** and answered one
8-passage RAG question in **199 seconds** (0.5 tok/s generate). Correct answer,
useless latency, and nothing anywhere reported that the GPU had not been used.
With the card free the same prompt runs at **10.3 tok/s**, 100% in VRAM.

`gpu-lease-gate.py` (`~/.local/bin`, this role) listens on **127.0.0.1:11435**
and takes **the same lock**, `%t/archivist-gpu.lock`. Pointing it anywhere else
would create two leases that cannot see each other, which is the whole bug.
Verified both directions with ARCHIVIST's own `gpu_lease()`: it is refused while
a gated answer streams, and it acquires again once the answer ends.

- `POST /api/chat` and `/api/generate` are gated: lease + free-VRAM check, then
  proxied with the response streamed through chunked so live token-by-token
  rendering still works. A full card returns **503** with
  `reason: gpu_busy | insufficient_vram`, not a slow answer.
- `/api/tags`, `/api/ps`, `/api/version`, `/api/show` pass through **ungated**,
  so a client can always discover the server and show that it is busy.
- `GET /gpu-lease` reports whether an answer would be admitted right now. It is
  a snapshot, not a reservation, so callers still have to handle the 503.
- It forces `keep_alive: 0` on gated requests. Ollama holds weights for
  `keep_alive` *after* a response, so releasing the lease at end-of-response
  with the quadlet's 30s would advertise a free card that still has ~1.7 GB on
  it. Set `GATE_KEEP_ALIVE=30s` in the unit to trade lease accuracy back for a
  warm conversation.
- `GATE_REQUIRED_MIB` mirrors archivist's `min_free_mib`. Defaults were measured
  via `/api/ps`, not guessed: `qwen3:1.7b` reports 1.70 GB fully resident, so
  2200 MiB is the admission floor. Re-read `/api/ps` after changing a model or
  a context size rather than trusting the table.

**The phone path is gated too, as of 2026-09-30, but by host state this role
does not own.** `tailscale serve` now maps `:8445` → `127.0.0.1:11435` (the
gate) instead of `11434` (Ollama). Set with
`tailscale serve --bg --https=8445 http://127.0.0.1:11435` — the `general` user
is the Tailscale `OperatorUser`, so it needs no sudo. Verified end to end over
the tailnet: the gate answers the CORS preflight for the `:8444` app origin
(Ollama no longer sees it, so `GATE_ORIGINS` is what matters now, not
`OLLAMA_ORIGINS`), `/api/tags` and `/gpu-lease` pass through, a real streamed
answer works, and holding the lease makes the tailnet `/api/chat` return
**503 gpu_busy**. Before this the iPhone could still trigger the 199-second
CPU-spilled answer while the desktop could not.

Because it is tailscaled state and not a file, `tailscale serve reset`, a
re-install, or a fresh machine loses it and silently returns the phone to the
ungated path. `tailscale serve status` is the check. Same class of
out-of-band config as the two items above.

It cannot protect against `whisper-gpu`, which sits at ~90 MiB idle and spikes
to 1.3-2.0 GB on a push-to-talk press that can land *after* admission. The
required-MiB floors carry headroom for it; headroom is not a guarantee, and no
admission check can be.

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
