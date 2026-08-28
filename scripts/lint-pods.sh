#!/bin/sh
# lint-pods.sh — fail when a NEW container is declared outside a pod.
#
# WHY
#   Podman was chosen over Docker for a future Kubernetes port: a Podman pod maps
#   1:1 onto a Kubernetes Pod; a standalone container does not and becomes
#   migration debt. The rule "new services go in <service>-pod" was agreed
#   2026-06-01 and violated nine times in the twelve weeks after — not through
#   disagreement, but because nothing enforced it.
#
# WHY A BASELINE, NOT A HARD FAIL
#   There are ~30 pre-existing violations. A check that fails on all of them from
#   day one is a check somebody disables within a week. This ratchets instead:
#   the existing backlog is recorded in scripts/pods-baseline.txt and tolerated,
#   anything NEW fails the build. Shrinking the baseline is then a visible,
#   reviewable diff rather than an invisible aspiration.
#
# Usage:  scripts/lint-pods.sh            fail on new violations
#         scripts/lint-pods.sh --update   re-record the baseline (shrink only)
set -eu
cd "$(dirname "$0")/.."
python3 - "${1:-}" <<'PY'
import re, sys, glob, os

MODE = sys.argv[1] if len(sys.argv) > 1 else ''
BASE = 'scripts/pods-baseline.txt'
# Edge/control plane: become their own Deployment in K8s, or never migrate.
ALLOW = {'traefik', 'cloudflared', 'ansible-deployment'}

found = set()
for path in sorted(glob.glob('roles/*/tasks/*.yml')):
    lines = open(path, encoding='utf-8', errors='replace').read().split('\n')
    i = 0
    while i < len(lines):
        if 'containers.podman.podman_container:' in lines[i]:
            ind = len(lines[i]) - len(lines[i].lstrip())
            name, has_pod, absent = None, False, False
            j = i + 1
            while j < len(lines):
                l = lines[j]
                if l.strip() and (len(l) - len(l.lstrip())) <= ind and not l.lstrip().startswith('#'):
                    break
                m = re.match(r'\s*name:\s*(.+?)\s*$', l)
                if m and name is None: name = m.group(1).strip('"\'')
                if re.match(r'\s*pod:\s*\S', l): has_pod = True
                if re.match(r'\s*state:\s*absent', l): absent = True
                j += 1
            nm = (name or '?').strip()
            d = re.search(r"default\('([^']+)'\)", nm)
            nm = d.group(1) if d else nm
            # `state: absent` tasks REMOVE a container; pod membership is meaningless.
            if not has_pod and not absent and nm not in ALLOW:
                found.add(f"{path}::{nm}")
            i = j
        else:
            i += 1

known = set()
if os.path.exists(BASE):
    known = {l.strip() for l in open(BASE) if l.strip() and not l.startswith('#')}

if MODE == '--update':
    with open(BASE, 'w') as f:
        f.write("# Containers declared outside a pod, tolerated for now.\n")
        f.write("# Shrink this file; never grow it. See scripts/lint-pods.sh.\n")
        for e in sorted(found): f.write(e + "\n")
    print(f"  baseline recorded: {len(found)} known violation(s)")
    sys.exit(0)

new = found - known
fixed = known - found
if fixed:
    print(f"  {len(fixed)} baseline entr(y/ies) resolved — run --update to shrink the baseline:")
    for e in sorted(fixed): print(f"    + {e}")
if new:
    print(f"\n  {len(new)} NEW container(s) declared outside a pod:\n")
    for e in sorted(new):
        p, n = e.split('::', 1)
        print(f"    {n:<46} {p}")
    print("\n  Add `pod: <service>-pod`, or add to ALLOW in scripts/lint-pods.sh")
    print("  with a comment explaining why it cannot be podded.\n")
    sys.exit(1)
print(f"  pods-first: OK — no new standalone containers ({len(found)} in baseline backlog)")
PY
