# Fedora sessions in OPS

The mobile Sessions page displays live Claude and Codex CLI sessions from Fedora.
The observer runs as the desktop user in a **system** service so systemd can load
a TPM-sealed credential. It watches finalized transcript records in the background;
CLI turns do not wait for a network upload. Failed batches retry without advancing
the local checkpoint. Existing archive message IDs are preserved.

## Deployment

Deploy the dashboard with the `ops-dashboard` Ansible tag. Migration 004 creates
the workstation and reply tables as the database owner. Configure allowed bridge
hosts with `management.ops_dashboard.workstation_hosts` (default: `[fedora]`).
The workstation URL is the existing tailnet HTTPS listener on port 8443. Expose only
the workstation path with:

```sh
tailscale serve --bg --https=8443 --set-path=/api/workstations http://127.0.0.1:8090/api/workstations
```

For initial workstation setup, copy `roles/workstation/files/bin/ops-session-bridge.py`
to `~/.local/bin/ops-session-bridge.py`, create
`~/.local/share/ops-session-bridge/venv` with `python3 -m venv`, and install
`websockets==15.0.1` in that venv. Pipe the derived host token directly to
`sudo python3 tools/install-ops-session-bridge.py --url "$OPS_BRIDGE_URL"`
(or invoke through `pkexec`). Set `OPS_BRIDGE_URL` to your private tailnet HTTPS
origin including port 8443; the hostname is deployment configuration, not source.
Derive the token inside the running dashboard container as
`HMAC-SHA256(SESSION_INGEST_TOKEN, "ops-workstation:v1:fedora")`, hexadecimal.
Keep the master token on the server; do not put either token in shell arguments,
logs, or plaintext files. The installer accepts the host token on stdin and seals
it to TPM2 at `/etc/credstore.encrypted/ops-session-token`.

Subsequent updates use `ansible-playbook ops-workstation.yml --ask-become-pass`
from the desktop user. The service is enabled at boot and runs as that user;
systemd decrypts its credential at startup. Check with
`systemctl status ops-session-bridge` and `journalctl -u ops-session-bridge`.
Log entries report counts and error classes, not transcript or reply contents.

## Reply and voice controls

Reply opens a composer inside the session sheet. Hide preserves its draft; a
successful Send closes the field. The server requires an operator session and a
live workstation lease. A disconnected bridge cannot accept new input. Request
IDs make browser retries idempotent; uncertain native writes are not retried
automatically. Replies expire if the workstation remains unreachable.

Codex replies enter the **existing thread's native queue** for its next turn.
Claude replies enter the existing session's messaging socket. Claude's inbound
policy still applies and may require terminal acceptance. Posting a reply does
not change CLI approval, sandbox, or permission settings. Delivery receipts
describe transport delivery, not proof of a completed assistant response.

Listen runs quantized Kokoro in a browser worker. Dictate records at most 30
seconds, stops the microphone, then runs quantized Whisper Tiny in that worker.
Dictation fills an editable draft; Send remains explicit. Closing the composer or
changing sessions cancels audio work. Model weights and WASM download on first
use and use browser caching; no audio is sent to the workstation or a speech API.
HTTPS and microphone permission are required. The single-thread WASM runtime
avoids requiring cross-origin isolation; device speed and browser memory vary.

## Verified release (2026-10-08)

84 backend tests passed, including a disposable real PostgreSQL database and
native Codex queue protocol checks. Mobile browser checks cover transcript
completeness, retained drafts, explicit send, and microphone cancellation. Real
Kokoro and Whisper Tiny browser inference completed successfully. Live production
checks verified both Fedora session kinds, transcript rendering, composer and
voice controls, plus anonymous API rejection. No test prompt was sent to a real
desktop session. Physical iPhone inference performance still needs device testing.

The isolated deployed release is `.ops-fedora-release-20261008` on the VPS.
The previous image is retained as `localhost/ops-dashboard:pre-fedora-20261008`.
Merge the feature pull request before a normal source deployment to retain these
changes. Stopping `ops-session-bridge` disables workstation sync without changing
either CLI session.
