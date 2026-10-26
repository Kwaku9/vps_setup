#!/bin/bash
# check-pod-wrap.sh — prove a standalone container was moved into a pod without breaking its route.
#
# Run as root on the VPS. Reusable for every phase 2 batch: only the arguments change.
#
#   scripts/check-pod-wrap.sh --pod web-public-pod --container decks-nginx \
#       --host decks.aicortex.cloud --marker "Decks · aicortex" \
#       --route-file /opt/compose/traefik/dynamic/decks.yml [--with-outage]
#
# Optional, for pods whose service is not on :80 or whose route file holds several services:
#   --port N       the container's own port (default 80); A3 dials it, A5 requires the route to use it
#   --service S    the Traefik service name whose backend URL A5 checks (default: the first url: in the file)
#   --path P       the request path for A4/K2 (default /); use a bait path for a honeypot
#   --no-route     the service has no public route (owui-coder, session-recall-mcp): A4, A5 and K2 are skipped, and
#                  the outage control K3 watches A3 instead of the end-to-end request
#   --tcp          A3 is a TCP connect to the pod's port from the traefik container, with no marker (for a
#                  bearer-authed HTTP service that cannot be fetched without its token)
#   --backend-path P  the path the BACKEND sees for A3 when Traefik rewrites it (default: --path), e.g. a
#                  replacePathRegex that turns /privacy into /privacy.html
#   Requests carry User-Agent check-pod-wrap-probe so they can be filtered out of honeypot evidence.
#
# Assertions (PASS/FAIL):
#   A1 the pod exists and is Running          A2 the container is a member of that pod
#   A3 the pod NAME serves the marker, from the traefik container (what Traefik will dial)
#   A4 end to end through Traefik: HTTP 200 and the marker (--resolve to 127.0.0.1, no DNS/CF needed)
#   A5 the live route file's backend host is the pod name
#   A6 the pod has an OpenRC unit and the container no longer has its own
#
# Controls (CONTROL-OK means it failed as required; CONTROL-BROKEN means it PASSED, so the probe
# cannot be trusted):
#   K1 the container's own name must NOT resolve from the traefik container (pod members are not
#      addressable by name; this is why the route must name the pod)
#   K2 a Host that has no router must NOT be served with the marker
#   K3 (--with-outage) stopping the pod must make A4 fail, and restarting it must make A4 pass again
#
# Exit: 0 all assertions pass and all controls failed as required
#       1 an assertion failed
#       3 every assertion passed but a control passed too: the result is untrusted
#       2 usage error
set -u

pod= ctr= host= marker= route_file= outage=0 port=80 service= path=/ backend_path= no_route=0 tcp=0
while [ $# -gt 0 ]; do
    case "$1" in
        --pod) pod=$2; shift 2 ;;
        --container) ctr=$2; shift 2 ;;
        --host) host=$2; shift 2 ;;
        --marker) marker=$2; shift 2 ;;
        --route-file) route_file=$2; shift 2 ;;
        --with-outage) outage=1; shift ;;
        --port) port=$2; shift 2 ;;
        --service) service=$2; shift 2 ;;
        --path) path=$2; shift 2 ;;
        --backend-path) backend_path=$2; shift 2 ;;
        --no-route) no_route=1; shift ;;
        --tcp) tcp=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
req="pod ctr"
[ "$no_route" -eq 1 ] || req="$req host"
[ "$tcp" -eq 1 ] || req="$req marker"
for v in $req; do
    eval "[ -n \"\${$v}\" ]" || { echo "missing --${v/ctr/container}" >&2; exit 2; }
done
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 2; }

fails=0 broken=0
pass() { echo "PASS          $1  $2"; }
fail() { echo "FAIL          $1  $2"; fails=$((fails + 1)); }
ctl_ok() { echo "CONTROL-OK    $1  $2"; }
ctl_broken() { echo "CONTROL-BROKEN $1  $2"; broken=$((broken + 1)); }

# GET https://$1/ through Traefik on loopback; prints "<code> <marker-found 0|1>".
e2e() {
    local h=$1 body code found=0
    body=$(mktemp)
    code=$(curl -sk -m 10 -A check-pod-wrap-probe --resolve "$h:443:127.0.0.1" -o "$body" -w '%{http_code}' "https://$h$path" 2>/dev/null)
    grep -qF -- "$marker" "$body" && found=1
    rm -f "$body"
    echo "${code:-000} $found"
}
e2e_ok() { [ "$(e2e "$1")" = "200 1" ]; }

skip() { echo "SKIP          $1  $2"; }

# Is the service itself answering? A TCP connect, or the marker fetched from the traefik container.
svc_up() {
    if [ "$tcp" -eq 1 ]; then
        podman exec traefik nc -z -w3 "$pod" "$port" >/dev/null 2>&1
    else
        podman exec traefik wget -q -T 5 -U check-pod-wrap-probe -O - "http://$pod:$port${backend_path:-$path}" 2>/dev/null | grep -qF -- "$marker"
    fi
}
# What K3 watches: the end-to-end request when there is a route, otherwise the service itself.
up_check() { if [ "$no_route" -eq 1 ]; then svc_up; else e2e_ok "$host"; fi; }

restart_pod() { podman pod exists "$pod" && podman pod start "$pod" >/dev/null 2>&1; }

# ---- controls --------------------------------------------------------------------------------
# K1: the container's own name must not resolve from the traefik container. A missing nslookup fails the
# same way as NXDOMAIN, so first require that a known pod name DOES resolve; otherwise K1 would pass
# vacuously and prove nothing.
if ! podman exec traefik nslookup security-infra-pod >/dev/null 2>&1; then
    ctl_broken K1 "nslookup cannot resolve the known pod name security-infra-pod from traefik; K1 would pass vacuously"
elif podman exec traefik nslookup "$ctr" >/dev/null 2>&1; then
    ctl_broken K1 "container name '$ctr' resolves from traefik (not behind a pod, or the probe cannot see DNS failure)"
else
    ctl_ok K1 "container name '$ctr' does not resolve from traefik"
fi

# K2: an unrouted Host must not look like the service.
ctl_host="zz-control.${host#*.}"
if [ "$no_route" -eq 1 ]; then
    skip K2 "no public route to compare against"
elif e2e_ok "$ctl_host"; then
    ctl_broken K2 "unrouted host $ctl_host was served with the marker"
else
    ctl_ok K2 "unrouted host $ctl_host is not served with the marker ($(e2e "$ctl_host"))"
fi

# ---- assertions ------------------------------------------------------------------------------
state=$(podman pod inspect "$pod" --format '{{.State}}' 2>/dev/null)
[ "$state" = "Running" ] && pass A1 "pod $pod is Running" || fail A1 "pod $pod state='${state:-absent}'"

pod_id=$(podman pod inspect "$pod" --format '{{.ID}}' 2>/dev/null)
ctr_pod=$(podman inspect "$ctr" --format '{{.Pod}}' 2>/dev/null)
if [ -n "$pod_id" ] && [ -n "$ctr_pod" ] && [ "${pod_id:0:12}" = "${ctr_pod:0:12}" ]; then
    pass A2 "$ctr is a member of $pod"
else
    fail A2 "$ctr pod='${ctr_pod:-none}' expected ${pod_id:0:12}"
fi

if [ "$tcp" -eq 1 ]; then what="tcp $pod:$port"; else what="http://$pod:$port${backend_path:-$path}"; fi
if svc_up; then
    pass A3 "$what answers from the traefik container"
else
    fail A3 "$what did not answer from the traefik container"
fi

if [ "$no_route" -eq 1 ]; then
    skip A4 "no public route"
elif e2e_ok "$host"; then
    pass A4 "https://$host$path -> 200 with marker through Traefik"
else
    fail A4 "https://$host$path -> $(e2e "$host") (want '200 1')"
fi

if [ "$no_route" -eq 1 ]; then
    skip A5 "no public route"
elif [ -n "$route_file" ]; then
    # The backend URL of --service (no YAML library needed: the files are generated with a fixed layout), or
    # the first url: in the file.
    if [ -n "$service" ]; then
        line=$(awk -v svc="$service" '/^  services:/{s=1} s && $0 ~ "^    "svc":[ ]*$" {f=1; next} f && /^    [A-Za-z0-9_-]+:[ ]*$/ {f=0} f && /url:/ {print; exit}' "$route_file" 2>/dev/null)
    else
        line=$(grep -m1 'url:' "$route_file" 2>/dev/null)
    fi
    hostport=$(echo "$line" | sed 's|.*://||; s|[/"].*||')
    backend=${hostport%%:*}
    case "$hostport" in *:*) bport=${hostport##*:} ;; *) bport=80 ;; esac
    if [ "$backend" = "$pod" ] && [ "$bport" = "$port" ]; then
        pass A5 "route backend is $pod:$port"
    else
        fail A5 "route backend='${backend:-none}:${bport}' want $pod:$port"
    fi
else
    fail A5 "no --route-file given"
fi

if rc-service --exists "$pod" 2>/dev/null && ! rc-service --exists "$ctr" 2>/dev/null; then
    pass A6 "OpenRC unit for $pod exists and none for $ctr"
else
    fail A6 "OpenRC: unit($pod)=$(rc-service --exists "$pod" 2>/dev/null && echo yes || echo no) unit($ctr)=$(rc-service --exists "$ctr" 2>/dev/null && echo yes || echo no)"
fi

# ---- K3: outage control (optional) -------------------------------------------------------------
if [ "$outage" -eq 1 ]; then
    if [ "$state" != "Running" ]; then
        fail K3 "cannot run the outage control: pod $pod is not Running"
    else
        trap restart_pod EXIT
        podman pod stop "$pod" >/dev/null 2>&1
        sleep 2
        if up_check; then
            ctl_broken K3 "the service still answered with pod $pod stopped"
        else
            ctl_ok K3 "the service stops answering with pod $pod stopped ($([ "$no_route" -eq 1 ] && echo "A3" || e2e "$host"))"
        fi
        podman pod start "$pod" >/dev/null 2>&1
        up=0
        for _ in $(seq 1 30); do up_check && { up=1; break; }; sleep 1; done
        if [ "$up" -eq 1 ]; then
            pass K3 "the service answers again after restarting $pod"
        else
            fail K3 "the service did not recover within 30s of restarting $pod"
        fi
        trap - EXIT
    fi
fi

echo
echo "assertion failures=$fails  controls broken=$broken"
[ "$fails" -gt 0 ] && exit 1
[ "$broken" -gt 0 ] && exit 3
exit 0
