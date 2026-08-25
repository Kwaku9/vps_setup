#!/bin/sh
# Reboot-durability snapshot / verification.
# Managed by Ansible (roles/boot-services).
#
# WHY: "everything comes back after a reboot" was never actually provable on this
# host. Pods have repeatedly failed to return (neo4j-pod, llama-embed-pod, both
# coders, honeypot, threat-map) and the loss was only ever noticed later, by
# accident. This turns that into a command:
#
#   verify-boot-durability snapshot   # BEFORE the reboot: record what is up
#   <reboot>
#   verify-boot-durability verify     # AFTER: exit 1 if anything did not return
#
# Semantics: a MISSING service fails. An EXTRA service does not — coming back
# with more than you had is not a loss. Ordering is never drift.
set -u

STATE_DIR=/var/lib/boot-durability
SNAP="$STATE_DIR/expected.txt"

collect() {
    # pods
    podman pod ps --format '{{.Name}}|{{.Status}}' 2>/dev/null \
        | awk -F'|' '$2=="Running"{print "pod:"$1}'
    # containers (pod infra excluded — it is an implementation detail of the pod)
    podman ps --format '{{.Names}}' 2>/dev/null \
        | grep -vE '^[0-9a-f]{12}-infra$' | sed 's/^/ctr:/'
    # host services that are load-bearing but are NOT containers. squid is here
    # because a dead squid fails CLOSED: the NAT REDIRECTs stay and every
    # container's :443 is steered at a dead port.
    for s in squid node-exporter crond fail2ban sshd chronyd; do
        rc-service "$s" status >/dev/null 2>&1 && echo "svc:$s"
    done
    # egress interception plumbing: rules present AND something listening
    iptables -t nat -L PREROUTING -n 2>/dev/null | grep -qE 'REDIRECT.*(3128|3129)' \
        && echo "net:squid-redirect-rules"
    netstat -tln 2>/dev/null | grep -qE ':(3128|3129)' && echo "net:squid-listening"
}

# Pure diff — fails iff something in BEFORE is absent from AFTER.
do_diff() {
    before="$1"; after="$2"; missing=0
    sort -u "$before" 2>/dev/null > /tmp/.bd_b; sort -u "$after" 2>/dev/null > /tmp/.bd_a
    while IFS= read -r item; do
        [ -z "$item" ] && continue
        grep -qxF "$item" /tmp/.bd_a || { echo "MISSING: $item"; missing=$((missing + 1)); }
    done < /tmp/.bd_b
    while IFS= read -r item; do
        [ -z "$item" ] && continue
        grep -qxF "$item" /tmp/.bd_b || echo "extra (not a failure): $item"
    done < /tmp/.bd_a
    rm -f /tmp/.bd_b /tmp/.bd_a
    if [ "$missing" -gt 0 ]; then
        echo "FAIL: $missing service(s) did not come back"; return 1
    fi
    echo "PASS: everything present"; return 0
}

case "${1:-}" in
    snapshot)
        mkdir -p "$STATE_DIR"; collect | sort -u > "$SNAP"
        echo "snapshot written: $SNAP ($(wc -l < "$SNAP") entries)"; cat "$SNAP"
        ;;
    verify)
        [ -f "$SNAP" ] || { echo "no snapshot at $SNAP — run 'snapshot' before rebooting" >&2; exit 2; }
        now=$(mktemp); collect | sort -u > "$now"
        do_diff "$SNAP" "$now"; rc=$?; rm -f "$now"; exit $rc
        ;;
    --diff)
        do_diff "$2" "$3"; exit $?
        ;;
    *)
        echo "usage: $0 {snapshot|verify|--diff BEFORE AFTER}" >&2; exit 2
        ;;
esac
