# Workstation systemd units

Files in this directory are user-level systemd units for the local
developer workstation (Fedora), NOT for the VPS. They drive the
daily timeline-refresh pipeline that backs https://timeline.aicortex.cloud.

## Install on a fresh workstation

```sh
# 1. Copy units into place
mkdir -p ~/.config/systemd/user
cp workstation-systemd/sync-claude-timeline.{service,timer} \
   ~/.config/systemd/user/

# 2. Allow user services to run when logged out (sudo required, one-time)
sudo loginctl enable-linger "$USER"

# 3. Activate
systemctl --user daemon-reload
systemctl --user enable --now sync-claude-timeline.timer

# 4. Verify next fire
systemctl --user list-timers sync-claude-timeline.timer
```

## Manual trigger (skip waiting for 04:00)

```sh
systemctl --user start sync-claude-timeline.service
journalctl --user -u sync-claude-timeline.service -f
```

The wrapper script itself lives at `../run-daily-timeline.sh` and
mirrors the steps documented in `~/.claude/commands/update-timeline.md`.
