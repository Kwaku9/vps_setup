#!/usr/bin/env bash
# Build/start the local Ansible controller for the laptop, then run the
# workstation playbook through it.
#
#   tools/ansible-workstation.sh build          # build the image (once)
#   tools/ansible-workstation.sh up             # start the long-running container
#   tools/ansible-workstation.sh check          # --check (drift report). NOT --diff: it renders vault values into the log.
#   tools/ansible-workstation.sh apply          # converge for real
#   tools/ansible-workstation.sh shell          # poke around inside
#   tools/ansible-workstation.sh voice debian   # Claude Code reply voice on the Debian GPU (Debian voice mode ON, Strata paused)
#   tools/ansible-workstation.sh voice laptop   # back to the laptop Voicebox (then Debian voice mode OFF, Strata back)
#   tools/ansible-workstation.sh down           # stop + remove
#
# Mirrors the VPS pattern (a long-lived container driven by `podman exec`), but
# the mounts below are what make it able to manage the HOST's user services
# rather than the container's own. They are load-bearing — don't `podman run`
# this image by hand without them.
set -euo pipefail

IMAGE=localhost/ansible-workstation:latest
NAME=ansible-workstation
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

UID_="$(id -u)"
GID_="$(id -g)"
RUNDIR="/run/user/${UID_}"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

build() {
  podman build -f "$REPO/Dockerfile.workstation" -t "$IMAGE" "$REPO"
}

up() {
  if podman container exists "$NAME"; then
    podman start "$NAME" >/dev/null 2>&1 || true
    return
  fi
  [ -d "$RUNDIR" ] || die "$RUNDIR missing — run this from a desktop login session."

  # --userns=keep-id      : the container's UID matches the host user, so files
  #                         written into $HOME are owned correctly on the host.
  # -v $HOME:$HOME        : file tasks must land on the real laptop, not inside
  #                         the container's throwaway filesystem.
  # -v $RUNDIR            : this is the bit that makes `systemctl --user` inside
  #                         the container control the HOST's user systemd — it
  #                         speaks to the session bus / private socket in here.
  # label=disable         : Fedora's SELinux would otherwise block access to the
  #                         runtime dir and $HOME across the container boundary.
  # --pid=host            : REQUIRED, and non-obvious. `systemctl --user` does not
  #                         use the D-Bus session bus — it connects to the private
  #                         socket $XDG_RUNTIME_DIR/systemd/private, which
  #                         authenticates the caller with SO_PEERCRED. From a
  #                         separate PID namespace the host cannot translate the
  #                         peer's PID, auth fails, and every systemctl call dies
  #                         with "Failed to connect to user scope bus via local
  #                         transport: No data available". Sharing the host PID
  #                         namespace makes the credentials resolvable.
  #                         (`busctl --user` works either way — dbus-broker does
  #                         not need the PID — so it is a misleading smoke test.)
  podman run -d --name "$NAME" \
    --userns=keep-id \
    --user "${UID_}:${GID_}" \
    --pid=host \
    --security-opt label=disable \
    -v "$HOME:$HOME" \
    -v "$RUNDIR:$RUNDIR" \
    -v "$REPO:/ansible" \
    -e HOME="$HOME" \
    -e USER="${USER:-$(id -un)}" \
    -e LOGNAME="${USER:-$(id -un)}" \
    -e XDG_RUNTIME_DIR="$RUNDIR" \
    -e DBUS_SESSION_BUS_ADDRESS="unix:path=${RUNDIR}/bus" \
    -w /ansible \
    "$IMAGE" >/dev/null
}

run_pb() {
  up
  podman exec -w /ansible "$NAME" \
    ansible-playbook -i inventory/hosts workstation.yml "$@"
}

# The speech_voice_backend lever: records the choice in the role defaults (so a later plain `apply` keeps it),
# converges the laptop, and switches the Debian side with debian-server's own tool. Order matters: Debian voice
# comes up BEFORE the laptop points at it, and the laptop moves back BEFORE Strata takes the Debian GPU again.
voice() {
  local target="${1:-}" debian_tool="$REPO/../debian-server/tools/voice-mode.sh"
  case "$target" in debian|laptop) ;; *) die "usage: $0 voice {debian|laptop}" ;; esac
  sed -i "s/^speech_voice_backend: .*/speech_voice_backend: $target/" "$REPO/roles/workstation/defaults/main.yml"
  grep -q "^speech_voice_backend: $target$" "$REPO/roles/workstation/defaults/main.yml" || die "could not set the lever"
  if [ "$target" = debian ]; then
    [ -x "$debian_tool" ] && "$debian_tool" on
    run_pb
  else
    run_pb
    [ -x "$debian_tool" ] && "$debian_tool" off
  fi
  echo "reply voice backend: $target"
}
case "${1:-}" in
  build) build ;;
  up)    up; echo "$NAME is up" ;;
  check) shift; run_pb --check "$@" ;;
  apply) shift; run_pb "$@" ;;
  shell) up; podman exec -it "$NAME" /bin/bash ;;
  voice) shift; voice "${1:-}" ;;
  down)  podman rm -f "$NAME" >/dev/null 2>&1 || true; echo "$NAME removed" ;;
  *)     die "usage: $0 {build|up|check|apply|shell|voice debian|laptop|down}" ;;
esac
