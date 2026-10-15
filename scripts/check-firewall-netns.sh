#!/bin/bash
# check-firewall-netns.sh — validate roles/security/templates/firewall.sh.j2 together with the generated
# zone rules (roles/security/files/zone-*.rules) in a THROWAWAY network namespace.
#
# WHY: the firewall script runs as root at every boot under `set -e`. A bad rule can leave the host in
# default-DROP with no SSH accept. This renders the real template with the real `security` settings from
# all.yml, executes it for real with the real iptables/kernel, and probes with real packets, all inside
# `unshare -n -m` (its own empty netfilter and private mounts). The host's own firewall is never touched.
#
# Checks (each prints PASS or FAIL; exit status is non-zero if any FAIL):
#   1  the script applies cleanly TWICE (idempotent), no warnings, exit 0
#   2  rule counts match the generated files; every zone rule precedes the generic tcp/22 accept
#   3  host SSH per zone: granted pod connects; any other pod in that zone, a pod in another zone, and an
#      un-granted port are dropped; a NON-zone interface still reaches sshd (the control)
#   4  a packet from the public side addressed to a zone is dropped (not accepted by ZONE_AUDIT)
#   5  a failing command inside each generated block does not abort the script: exit 0, warnings printed,
#      INPUT policy DROP with the SSH and loopback accepts still present
#
# Needs: root, util-linux `unshare`, iproute2, iptables, python3 with jinja2 and PyYAML.
# Usage: scripts/check-firewall-netns.sh
set -u
cd "$(dirname "$0")/.."
[ "$(id -u)" -eq 0 ] || { echo "run as root (needs unshare -n)"; exit 2; }
command -v unshare >/dev/null || { echo "unshare not found"; exit 2; }
python3 -c 'import jinja2, yaml' 2>/dev/null || { echo "python3 needs jinja2 and PyYAML"; exit 2; }

WORK=$(mktemp -d /tmp/fwcheck.XXXXXX)
cleanup() {
    # `ip netns add` leaves an empty marker file under /run/netns even from a private mount namespace.
    for f in /run/netns/fc*; do
        [ -f "$f" ] && [ ! -s "$f" ] && ! grep -q " $f " /proc/self/mountinfo && rm -f "$f"
    done
    rm -rf "$WORK"
}
trap cleanup EXIT

# ---- render the real template: good rules, and a copy with one failing command injected in each block
python3 - "$WORK" <<'PY' || exit 2
import pathlib, sys, yaml, jinja2
work = pathlib.Path(sys.argv[1]); root = pathlib.Path("roles/security")
allv = yaml.safe_load(pathlib.Path("all.yml").read_text())
def render(files_dir, out):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(root / "templates")), undefined=jinja2.ChainableUndefined)
    env.globals["lookup"] = lambda kind, name: (files_dir / name).read_text()
    out.write_text(env.get_template("firewall.sh.j2").render(security=allv["security"]))
render(root / "files", work / "good.sh")
bad = work / "bad"; bad.mkdir()
for n in ("zone-input.rules", "zone-forward.rules"):
    lines = (root / "files" / n).read_text().splitlines()
    lines.insert(len(lines) // 3, "iptables -A NO_SUCH_CHAIN_FOR_TEST -j ACCEPT")   # must fail
    (bad / n).write_text("\n".join(lines) + "\n")
render(bad, work / "bad.sh")
PY
bash -n "$WORK/good.sh" && bash -n "$WORK/bad.sh" || { echo "FAIL rendered script has a syntax error"; exit 1; }

# ---- facts from the real data, passed to the namespace script
eval "$(PYTHONPATH=tools python3 - <<'PY'
import ipaddress
from netseg import model
m = model.load("network/zones.yml", "network/flows.yml")
host_flow = [f for f in m.expanded_flows() if f.dst == "host" and f.src_pod]
g = host_flow[0]; z = m.zones[g.src]; pod = z.pods[g.src_pod]
other = next(ip for ip in z.network.hosts() if ip not in (pod.ip, z.gateway))
w = next(x for x in m.zones.values() if x.key != z.key and x.pods)
wip = next(iter(w.pods.values())).ip
dz = next(x for x in m.zones.values() if x.pods and x.key not in (z.key, w.key))
target = next(iter(dz.pods.values()))
print(f"ZONES={len(m.zones)}")
print(f"G_BR={z.bridge}; G_CIDR={z.network}; G_GW={z.gateway}; G_POD={pod.ip}; G_OTHER={other}; G_PREFIX={z.network.prefixlen}")
print(f"W_BR={w.bridge}; W_GW={w.gateway}; W_POD={wip}; W_PREFIX={w.network.prefixlen}")
print(f"DST_ZONE_IP={target.ip}")
PY
)"
INPUT_RULES=$(grep -c '^iptables -A INPUT -i br-' roles/security/files/zone-input.rules)
export ZONES G_BR G_GW G_POD G_OTHER G_PREFIX W_BR W_GW W_POD W_PREFIX DST_ZONE_IP INPUT_RULES WORK

cat > "$WORK/inner.sh" <<'INNER'
#!/bin/bash
set +e
ok() { echo "PASS  $1"; }
no() { echo "FAIL  $1"; FAILED=1; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else no "$1 (got '$2', expected '$3')"; fi; }
FAILED=0
ip link set lo up

# ---- 1. clean apply, twice
for i in 1 2; do
    bash "$WORK/good.sh" start > "$WORK/g$i.log" 2>&1; rc=$?
    check "1  apply #$i exits 0" "$rc" 0
    check "1  apply #$i prints no warnings" "$(grep -c WARNING "$WORK/g$i.log")" 0
done

# ---- 2. counts and ordering
check "2  zone INPUT rules match the generated file" "$(iptables -S INPUT | grep -c -e '-i br-')" "$INPUT_RULES"
check "2  one host-SSH denial per zone" "$(iptables -S INPUT | grep -c host-ssh-denied)" "$ZONES"
check "2  two jumps into ZONE_FWD" "$(iptables -S FORWARD | grep -c -e '-j ZONE_FWD')" 2
check "2  anti-spoof rules: 3 per zone" "$(iptables -S FORWARD | grep -c -e '-j ZONE_DENY')" "$((ZONES * 3))"
g=$(iptables -S INPUT | grep -n -e '-p tcp -m tcp --dport 22 -j ACCEPT' | head -1 | cut -d: -f1)
zl=$(iptables -S INPUT | grep -n -e '-i br-' | tail -1 | cut -d: -f1)
[ -n "$g" ] && [ -n "$zl" ] && [ "$zl" -lt "$g" ] && ok "2  every zone rule precedes the generic tcp/22 accept" || no "2  zone rules must precede the generic tcp/22 accept (zone last=$zl generic=$g)"
check "2  INPUT default policy is DROP" "$(iptables -S INPUT | head -1)" "-P INPUT DROP"

# ---- 3. real packets to the host's sshd
pod() { n=$1; br=$2; gwcidr=$3; ipc=$4; gw=$5
    ip link show "$br" >/dev/null 2>&1 || { ip link add "$br" type bridge; ip addr add "$gwcidr" dev "$br"; ip link set "$br" up; }
    ip netns add "$n"; ip link add "h$n" type veth peer name "c$n"; ip link set "h$n" master "$br" up; ip link set "c$n" netns "$n"
    ip netns exec "$n" ip link set lo up; ip netns exec "$n" ip addr add "$ipc" dev "c$n"; ip netns exec "$n" ip link set "c$n" up
    ip netns exec "$n" ip route add default via "$gw"
}
probe() { ip netns exec "$1" python3 -c "import socket;socket.create_connection(('$2',$3),2);print('CONNECTED')" 2>&1 | tail -1 | sed 's/.*[Tt]imed out.*/TIMEOUT/'; }
python3 -c "
import socket
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('0.0.0.0',22)); s.listen(16)
while True:
    c,_=s.accept(); c.close()
" &
LP=$!; sleep 1
pod fc1 "$G_BR" "$G_GW/$G_PREFIX" "$G_POD/$G_PREFIX" "$G_GW"
pod fc2 "$G_BR" "$G_GW/$G_PREFIX" "$G_OTHER/$G_PREFIX" "$G_GW"
pod fc3 "$W_BR" "$W_GW/$W_PREFIX" "$W_POD/$W_PREFIX" "$W_GW"
pod fc4 brfcleg 10.89.0.1/24 10.89.0.5/24 10.89.0.1
check "3  granted pod reaches host sshd" "$(probe fc1 "$G_GW" 22)" CONNECTED
check "3  other address in the same zone is dropped" "$(probe fc2 "$G_GW" 22)" TIMEOUT
check "3  pod in another zone is dropped (template accepts 22 for all)" "$(probe fc3 "$W_GW" 22)" TIMEOUT
check "3  control: a non-zone interface still reaches sshd" "$(probe fc4 10.89.0.1 22)" CONNECTED
check "3  granted pod, un-granted port is dropped" "$(probe fc1 "$G_GW" 9999)" TIMEOUT
kill "$LP" 2>/dev/null

# ---- 4. public-side packet addressed to a zone
sysctl -qw net.ipv4.ip_forward=1
ip netns add fcx; ip link add fcext type veth peer name fcx0; ip link set fcx0 netns fcx
ip addr add 192.0.2.1/24 dev fcext; ip link set fcext up
ip netns exec fcx ip link set lo up; ip netns exec fcx ip addr add 192.0.2.2/24 dev fcx0; ip netns exec fcx ip link set fcx0 up
ip route add default via 192.0.2.2; ip netns exec fcx ip route add "${DST_ZONE_IP%.*}.0/24" via 192.0.2.1
a0=$(iptables -L ZONE_AUDIT -n -v -x | awk '/ACCEPT/{print $1}'); d0=$(iptables -L ZONE_DENY -n -v -x | awk '/DROP/{print $1}')
ip netns exec fcx python3 -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.sendto(b'x',('$DST_ZONE_IP',5432))"; sleep 1
a1=$(iptables -L ZONE_AUDIT -n -v -x | awk '/ACCEPT/{print $1}'); d1=$(iptables -L ZONE_DENY -n -v -x | awk '/DROP/{print $1}')
check "4  public-side packet to a zone is not accepted by ZONE_AUDIT" "$a1" "$a0"
[ "$d1" -gt "$d0" ] && ok "4  ...and is dropped by ZONE_DENY" || no "4  ZONE_DENY drop counter did not increase ($d0 -> $d1)"

# ---- 5. failure injection
bash "$WORK/bad.sh" start > "$WORK/bad.log" 2>&1; rc=$?
check "5  a failing command in each block does not abort the script" "$rc" 0
check "5  the INPUT block failure is reported" "$(grep -c 'WARNING: zone INPUT rules failed' "$WORK/bad.log")" 1
check "5  the FORWARD block failure is reported" "$(grep -c 'WARNING: zone FORWARD rules failed' "$WORK/bad.log")" 1
check "5  script still finishes" "$(grep -c 'Firewall started successfully' "$WORK/bad.log")" 1
check "5  INPUT policy still DROP" "$(iptables -S INPUT | head -1)" "-P INPUT DROP"
check "5  generic ssh accept still present" "$(iptables -S INPUT | grep -c -e '-p tcp -m tcp --dport 22 -j ACCEPT')" 1
check "5  loopback accept still present" "$(iptables -S INPUT | grep -c -e '-i lo -j ACCEPT')" 1
check "5  legacy forward accepts still installed" "$([ "$(iptables -S FORWARD | grep -c -e '-s 10.89.0.0/24 -j ACCEPT')" -ge 1 ] && echo yes || echo no)" yes

[ "$FAILED" -eq 0 ] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit "$FAILED"
INNER

before=$(iptables -L -n 2>/dev/null | grep -c '^Chain ZONE_')
timeout 300 unshare -n -m bash "$WORK/inner.sh"; rc=$?
after=$(iptables -L -n 2>/dev/null | grep -c '^Chain ZONE_')
if [ "$before" = "$after" ]; then echo "PASS  host firewall untouched (zone chains: $before before, $after after)"; else echo "FAIL  host zone chains changed: $before -> $after"; rc=1; fi
exit "$rc"
