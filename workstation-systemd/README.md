# Workstation systemd units — MOVED

The units that lived here (`sync-claude-timeline.{service,timer}`) are now
managed by the `workstation` Ansible role, together with the other ~20 user
units, the podman quadlets, and the laptop helper scripts:

    roles/workstation/files/systemd/
    roles/workstation/defaults/main.yml     # enabled/started state per unit

Deploy them with the playbook rather than by hand:

    ansible-playbook -i inventory/hosts workstation.yml --check --diff   # drift report
    ansible-playbook -i inventory/hosts workstation.yml                  # apply

## Why this directory changed

The old instruction here was "copy the units into `~/.config/systemd/user` and
`systemctl --user enable --now`". That works, but nothing detects when it is not
followed — and it was only ever applied to these two files. The other 20 user
units on the laptop were never version-controlled at all, so a laptop rebuild
meant reconstructing them from memory. The role closes that gap and makes
`--check --diff` a drift detector, the same way `tools/check-vps-drift.sh` is
for the VPS.

Note that `sync-claude-timeline.timer` is intentionally **disabled** — the
timeline refresh is run on demand through the `/update-timeline` skill. The role
records that as the desired state; it is not an oversight to be corrected.

This directory is kept only as a pointer and can be deleted once the role has
been applied at least once.
