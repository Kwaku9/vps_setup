# Tetragon — eBPF Runtime Security (Observation & Enforcement)

Kernel-level eBPF monitoring and in-kernel enforcement for the Alpine VPS. Tetragon
attaches BPF programs to kernel hooks and either **observes** behavior (emits events) or
**enforces** policy (SIGKILLs the offending process in-kernel). This document describes the
full setup, how the pieces interconnect, every active hook, and the operational runbooks.

> Companion: `vps_setup/docs/tetragon-deep-dive.md` is an incident-driven narrative of how
> this configuration was hardened. **This README is the reference for the running system.**

---

## 1. At a glance

| | |
|---|---|
| Engine | `quay.io/cilium/tetragon:v1.6.0` (privileged podman container, `pid_mode: host`) |
| Managed by | Ansible — `roles/security` (toggles in `all.yml` → `security.tetragon`) |
| Current mode | **observe-only** (`enforce: false`) — alerts, never kills |
| Event log | `/var/log/tetragon/events.json` → Alloy → Loki (`job=tetragon`) |
| Metrics | `:2112` → Alloy → VictoriaMetrics |
| Alerts | `tetragon-alerter` (1-min cron) → Telegram |
| Dashboard | Grafana **"Tetragon — Security Behavior Baseline"** (`uid: tetragon-baseline`) |
| Emergency stop | `podman rm -f tetragon && rm -rf /sys/fs/bpf/tetragon` (see §9) |

---

## 2. How it all connects

```
                          ┌─────────────────────────────────────────────┐
                          │  KERNEL (eBPF kprobes, host-wide via pid_ns) │
                          │  tcp_connect · security_file_open ·          │
                          │  security_file_permission · sys_mount ·      │
                          │  (dormant) sys_execve                         │
                          └───────────────┬─────────────────────────────┘
                                          │ events (filtered in-kernel by selectors)
                  ┌───────────────────────▼────────────────────────┐
                  │  tetragon container  (privileged, pid_mode:host)│
   policies ─────▶│  loads /etc/tetragon/tetragon.tp.d/*.yaml       │
   (ro mount)     │   • 10-observe.yaml  → action: Post             │
                  │   • 20-enforce.yaml  → action: Sigkill (if on)  │
                  │   • 99-panic-claude  → armed via killswitch     │
                  └──────┬───────────────────────────────┬─────────┘
                         │ JSON events                    │ /metrics :2112
            ┌────────────▼───────────┐                    │
            │ /var/log/tetragon/     │                    │
            │   events.json          │                    │
            └──────┬──────────┬──────┘                    │
                   │          │                           │
   ┌───────────────▼──┐   ┌───▼──────────────────┐   ┌────▼──────────────┐
   │ tetragon-alerter │   │ Grafana Alloy        │   │ Grafana Alloy     │
   │ (cron 1m)        │   │ loki.source.file     │   │ prometheus.scrape │
   │ WATCH + SUPPRESS │   │ → loki.process parse │   │ → remote_write    │
   └────────┬─────────┘   └──────────┬───────────┘   └────────┬──────────┘
            │ Telegram               │ Loki (job=tetragon)    │ VictoriaMetrics
            ▼                        ▼                        ▼
        operator              Grafana dashboards         Grafana dashboards
        (high-signal)         (baseline / forensics)     (resource / volume)
```

Two **independent** consumers of `events.json`:
- **Alloy → Loki** ships *every* event for baseline analytics and dashboards (function-agnostic).
- **tetragon-alerter → Telegram** ships only *high-signal* events, after a SUPPRESS filter.

This separation is the core design principle (§5).

---

## 3. The container

Deployed by `roles/security/tasks/main.yml` (tag `tetragon`). It runs with high privilege
because eBPF + host-wide visibility require it:

| Setting | Value | Why |
|---|---|---|
| `privileged` | true | load BPF, attach kprobes |
| `pid_mode` / `cgroupns` | `host` | **see every process on the host AND in every container** |
| `memory` | `128m` | hard ceiling (it runs near this cap) |
| volume | `/sys/kernel/btf/vmlinux:ro` | BTF — kernel type info for portable eBPF |
| volume | `/sys/fs/bpf:rw` | where BPF programs/maps/links are **pinned** |
| volume | `/sys/kernel/debug:rw`, `/proc:ro` | kprobe + process introspection |
| volume | `/var/log/tetragon:rw` | event output (`events.json`) |
| volume | `/opt/compose/tetragon/policies:ro` → `/etc/tetragon/tetragon.tp.d` | the live policies |

Env: `TETRAGON_EXPORT_FILENAME=/var/log/tetragon/events.json`,
`TETRAGON_TRACING_POLICY_DIR=/etc/tetragon/tetragon.tp.d`,
`TETRAGON_SERVER_ADDRESS=127.0.0.1:54321`, `TETRAGON_METRICS_SERVER=:2112`.

> **`pid_mode: host` is load-bearing for understanding false positives:** a policy meant for
> "containers" also governs the host's `sshd`, shells, and package manager. Several incidents
> traced back to this — see the deep-dive doc.

---

## 4. The policy model

Tetragon policies are Kubernetes-style YAML (`kind: TracingPolicy`). Each lists **kprobes**;
each kprobe declares **args** (typed, so Tetragon can read them) and **selectors** that decide
when to act. Within one selector, all `match*` clauses are **AND**ed.

### Action spectrum

| Action | Effect | Risk |
|---|---|---|
| `Post` | emit an event to `events.json` (alert/observe) | safe — never changes behavior |
| `Sigkill` | **kill the process in-kernel** | dangerous — a false positive terminates real work |

### Two-file split (the toggle)

`all.yml`:
```yaml
security:
  tetragon:
    enabled: true     # deploy Tetragon at all
    enforce: false    # load the SIGKILL layer
    version: "v1.6.0"
```

| File | Loaded when | Action | Role |
|---|---|---|---|
| `10-observe.yaml` | always (`enabled: true`) | `Post` | the detection floor — broad, for baseline |
| `20-enforce.yaml` | only `enforce: true` (**deleted** when false) | `Sigkill` | kill layer — narrow, near-zero-FP only |
| `99-panic-claude.yaml` | staged dormant; armed by `claude-killswitch` | `Sigkill` | emergency brake for a runaway `claude` CLI |

The Ansible task at `tasks/main.yml` deploys `20-enforce.yaml` when `enforce: true` and
**removes** it when `enforce: false`, so flipping the flag is a clean rollback.

### Selector operators used here

- `matchBinaries` — filter by executing binary. `In` / `NotIn`. **Compares the *resolved*
  path** (e.g. `/usr/bin/python3.14`, not the `python3` symlink) — see §10.
- `matchArgs` — filter an argument value:
  - `Prefix` / `Postfix` — path starts-with / ends-with.
  - `Mask` — bitwise test (`(value & mask) != 0`), used on access masks.
  - `NotDAddr` — destination IP/CIDR (only valid on a `sock` arg).
- `matchActions` — `Post` or `Sigkill`.

---

## 5. Three-layer design (the mental model)

Detection, alerting, and enforcement are **decoupled** and tuned independently. This is the
single most important idea for working on this system:

| Layer | Mechanism | Tuning principle |
|---|---|---|
| **COLLECT** | `10-observe` → `events.json` → Loki | Keep **broad**. Log benign-but-interesting behavior (e.g. SSH login auth) — it's baseline data. Don't allowlist here just to quiet alerts. |
| **ALERT** | `tetragon-alerter` → Telegram | Suppress known-benign noise via `SUPPRESS` (still logged to Loki). Only high-signal pings reach the operator. |
| **ENFORCE** | `20-enforce` → SIGKILL | Kill **only** near-zero-false-positive signatures. If a deploy or routine op can trigger it, it does not belong here. |

Concretely: `sshd → /etc/shadow` and `claude → .credentials.json` are **logged** (baseline),
**suppressed** (no Telegram), and **not enforced** (no kill). A reverse shell to a public IP is
all three.

---

## 6. Active hooks

### `10-observe.yaml` (action: `Post`)

| # | kprobe | Watches | Allowlist (`NotIn`) |
|---|---|---|---|
| 1 | `tcp_connect` | a shell (`/bin/sh`,`bash`,`busybox`,`ash`) connecting to a **non-private** dest (`NotDAddr` excludes loopback / RFC1918 / link-local / tailnet `100.64.0.0/10`) | — |
| 2 | `__x64_sys_mount` | any `mount()` (container-escape primitive; noisy, observe-only) | — |
| 3a | `security_file_open` | open of `*podman/podman.sock` or `*docker.sock` (container-control socket) | — |
| 3b | `security_file_open` | **read** of `*vault.yml`, `*.credentials.json`, `/etc/shadow`, `*id_rsa`, `*id_ed25519` | ansible, ansible-playbook, python3, sshd, ssh, su, login, passwd. **`sshd-session` deliberately NOT allowlisted** here so its `/etc/shadow` reads are logged for the login-auth baseline. |
| 4 | `security_file_permission` | **write** (`Mask` MAY_WRITE=2) to `/etc/crontabs/`,`/etc/periodic/`,`/etc/init.d/`,`/etc/conf.d/`,`/opt/compose/tetragon/`,`/opt/compose/crowdsec/` (4a) or to `*authorized_keys`,`*.bashrc`,`*.profile` (4b) | ansible, ansible-playbook, python3, **python3.14**, crontab, apk |

### `20-enforce.yaml` (action: `Sigkill`, only when `enforce: true`)

Deliberately a **strict subset** — only signatures proven near-zero-FP against the real workload:

| kprobe | Kills | Allowlist (`NotIn`) |
|---|---|---|
| `tcp_connect` | shell → **non-private** outbound (same scoping as observe) | — |
| `security_file_open` | **read** of `*vault.yml`, `/etc/shadow`, `*id_rsa`, `*id_ed25519` (crown jewels) | ansible, ansible-playbook, python3, sshd, **sshd-session**, **sshd-auth**, ssh, su, login, passwd |

**Intentionally NOT enforced** (observe-only, by hard-won decision):
- container-control-socket opens (3a) — too much legit tooling/monitoring blast radius.
- `mount()` (2) — pure noise.
- **persistence writes (4)** — every deploy writes to these dirs (apk init scripts, ansible
  configs); the exempt-list is version-fragile (`python3.14`). FP-prone → never a kill rule.
- **`.credentials.json` reads** — main matcher is `claude` reading its own token at startup.

### `99-panic-claude.yaml` (dormant)

`execve` of a program path ending in `claude` or `/claude/cli.js` → `Sigkill`. Loaded only when
armed via `claude-killswitch arm`. **Independent of `20-enforce`** — disarming it does NOT
remove the enforcement layer, and vice-versa.

---

## 7. The alerter

`roles/security/templates/tetragon-alerter.py.j2` → `/usr/local/bin/tetragon-alerter`, run by
cron every minute.

- **Cursor:** byte-offset file `/opt/compose/textfile-collector/.tetragon-alert-offset` — each
  line is processed exactly once. (Reads with `readline()` in a `while` loop; using
  `for line in f` + `f.tell()` permanently disables `tell()` and crash-loops re-alerts — a real
  bug we hit; do not reintroduce.)
- **`WATCH`** (function → label): `tcp_connect`, `__x64_sys_mount`, `security_file_open` (reads),
  `security_file_permission` (writes).
- **`SUPPRESS`** — `(binary, path-substring)` pairs that are known-benign baseline; **logged to
  Loki, not Telegrammed**. SIGKILLs are always alerted even if suppressed. Current entries:
  - `(sshd-session | sshd-auth | sshd, /etc/shadow)` — SSH login auth
  - `(claude.exe, /root/.claude/.credentials.json)` — Claude Code reading its own token
- **Cap:** `MAX_ALERTS_PER_RUN = 10` (backlog deferred to next run).
- Message format: `🛡️ Tetragon {ALERT|KILLED}: {label} | {binary} | {file-or-dest} | fn={func}`

---

## 8. Observability pipeline

- **Logs:** Alloy `loki.source.file "tetragon_events"` tails `/var/log/tetragon/events.json`
  (Alloy has `/var/log` mounted) → `loki.process "tetragon_parse"` extracts labels →
  Loki `job=tetragon`. Stream labels: `event_type` (kprobe/exec/exit), `process_binary`,
  `parent_binary`, `kprobe_func`, `kprobe_policy`. (`action` is in the JSON line; filter with
  `|= "KPROBE_ACTION_SIGKILL"`.)
- **Metrics:** Alloy `prometheus.scrape` of `tetragon:2112` → VictoriaMetrics.
- **Dashboard:** `roles/monitoring/files/dashboards/tetragon-baseline.json` (auto-provisioned
  from `/opt/compose/dashboards`). Panels: event rates by function, POST-vs-SIGKILL, top
  binaries, binary→parent baseline, SSH-auth frequency, and live streams (SIGKILL, file reads,
  file writes, tcp_connect).

Query Loki only from inside the pod network (host can't reach it):
`podman exec grafana wget -qO- 'http://logs-pod:3100/loki/api/v1/label/kprobe_func/values'`.

---

## 9. Operations

### Enable / disable
Edit `all.yml` → `security.tetragon`:
- `enforce: false` → observe-only (kills off; `20-enforce.yaml` removed on next run).
- `enabled: false` → remove Tetragon entirely.

### Deploy
```sh
ansible-playbook site.yml --tags security,tetragon
```
> The VPS deploys from **its own** repo checkout at `/workspace/vscode-projects/vps_setup`, not
> a laptop checkout. Sync edits (scp/git) before redeploying or they won't take.

### Emergency stop (when enforcement is misbehaving)
SIGKILL'd SSH cannot be your recovery path — use the **Hostinger out-of-band console**:
```sh
podman rm -f tetragon          # remove the container
rm -rf /sys/fs/bpf/tetragon    # CRITICAL: a hard kill (exit 137) orphans the pinned
                               # eBPF programs; they keep enforcing until you remove the pins
busybox nc -w2 1.1.1.1 53 </dev/null; echo $?   # verify: must NOT be 137/Killed
```

### Validate a policy change (the dry-run harness)
Because observe and enforce share selector logic, **observe is a safe simulator for what
enforce would do.** Deploy to observe, then probe:
```sh
EV=/var/log/tetragon/events.json; B=$(wc -c < $EV)
busybox sh -c 'printf x > /etc/init.d/_t'              # rogue write  → expect a Post event
python3 -c "open('/etc/conf.d/_t','w').write('x')"     # deploy write → expect EXEMPT
busybox cat /etc/init.d/<existing> >/dev/null          # read         → expect no event
sleep 5; tail -c +$((B+1)) $EV | grep -o '"function_name":"[^"]*"\|/etc/init.d/_t\|/etc/conf.d/_t'
rm -f /etc/init.d/_t /etc/conf.d/_t
```
Confirm the policy loaded without arg errors:
`podman logs tetragon 2>&1 | grep -iE "invalid index|FuncProto|failed to load"` (want none).

### Resolve a false positive (decision tree)
1. Benign self-access noise (tool reading its own files) → add `(binary, path)` to alerter
   **`SUPPRESS`** (keeps Loki baseline, stops Telegram).
2. A tool legitimately needs the access → add its **resolved** binary path to the relevant
   **enforce allowlist** (`matchBinaries: NotIn`).
3. Inherently FP-prone signature → **drop from enforce, keep in observe**.

### Re-enable `enforce` safely — checklist
- [ ] Run observe-only through a full deploy + a normal workday; review the dashboard's SIGKILL
      and file panels for events that *would* have been kills.
- [ ] Each such event is allowlisted, suppressed, or scoped out of enforce.
- [ ] Out-of-band console access confirmed working.
- [ ] Flip `enforce: true`, redeploy, then validate scoping:
      `busybox nc -w2 <tailnet-ip> 22` (survives) vs `busybox nc -w2 1.1.1.1 53` (killed).

---

## 10. Gotchas & limitations (hard-won)

- **Orphaned eBPF on hard kill.** `podman stop/rm -f` exits `137` (SIGKILL) — *ungraceful*.
  Tetragon only unloads its BPF on a graceful stop, so pins under `/sys/fs/bpf/tetragon` keep
  enforcing with no userspace behind them. Always `rm -rf /sys/fs/bpf/tetragon` and functionally
  test after stopping.
- **Syscall kprobes only extract `index 0`.** `__x64_sys_*`/`sys_*` with `syscall: true`
  validates args against the `pt_regs` prototype, so `index 1`+ throw `invalid index … FuncProto`
  and silently don't read. That's why `mount`/`execve` hooks use only index 0, and why
  openat-based write detection is impossible here.
- **`security_file_open` has no usable open-flags arg** (`int_arg` reads 0). Masking writes there
  never fires. Use **`security_file_permission`** (`MAY_WRITE=2` mask at index 1) for write FIM.
- **`matchBinaries` compares the resolved path**, even though the event *displays* the symlink.
  `/usr/bin/python3` won't match a `python3.14` process. Also: **`ansible-playbook` runs *as*
  python3**, so the `python3` allowlist entry is what exempts ansible (the `ansible*` entries are
  effectively dead, kept only for documentation).
- **Alpine is busybox-land.** The interactive/login shell is `/bin/ash`; `wget`/`nc`/etc. are
  `/bin/busybox`. Allowlists written with a glibc mental model misfire.
- **Hook frequency / cost.** `security_file_open` and `security_file_permission` run on every
  open / read-write (filtered in-kernel). Acceptable for a security tool; watch the resource
  panels if the workload is I/O-heavy.
- **`openat` relative-path caveat (n/a today, but noted):** syscall-level path matching sees the
  raw (possibly relative) filename; LSM hooks (what we use) see the resolved path.

---

## 11. File map

| Path | Purpose |
|---|---|
| `roles/security/templates/tetragon/10-observe.yaml.j2` | observe (Post) policy |
| `roles/security/templates/tetragon/20-enforce.yaml.j2` | enforce (Sigkill) policy |
| `roles/security/templates/tetragon/99-panic-claude.yaml.j2` | dormant kill-claude policy |
| `roles/security/templates/tetragon-alerter.py.j2` | Telegram alerter (WATCH/SUPPRESS) |
| `roles/security/templates/claude-killswitch.sh.j2` | arm/disarm the panic policy |
| `roles/security/tasks/main.yml` | deploys all of the above (tag `tetragon`) |
| `roles/security/defaults/main.yml`, `all.yml` | toggles (`security.tetragon.*`) |
| `roles/monitoring/templates/alloy-config.alloy.j2` | ships events.json → Loki, scrapes :2112 |
| `roles/monitoring/files/dashboards/tetragon-baseline.json` | Grafana baseline dashboard |
| **runtime** `/opt/compose/tetragon/policies/` | live policies (mounted into container) |
| **runtime** `/var/log/tetragon/events.json` | event output |
| **runtime** `/usr/local/bin/{tetragon-alerter,claude-killswitch}` | helpers |

---

## 12. References

- `vps_setup/docs/tetragon-deep-dive.md` — incident narrative & rationale (NotebookLM-ready)
- Tetragon docs: https://tetragon.io/docs/
- Quick event query on the box: `podman exec tetragon tetra getevents -o compact`
