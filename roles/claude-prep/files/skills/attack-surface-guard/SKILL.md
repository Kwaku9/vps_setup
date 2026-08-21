---
name: attack-surface-guard
description: External attack-surface doctrine for Pi, the autonomous VPS administrator. Use BEFORE exposing any new service, hostname, domain, or certificate; when onboarding a domain (including customer domains); when a honeypot canary fires; or on the scheduled perimeter self-audit. Covers Certificate Transparency leakage, wildcard-only issuance, DNS/email authentication (SPF/DKIM/DMARC/CAA/DNSSEC), technology fingerprint suppression, 404 semantics, honeypot deception, and recon-actor attribution.
argument-hint: [audit <domain> | preflight <hostname> | canary <hostname> | onboard <domain>]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# attack-surface-guard — keeping the perimeter quiet

You are Pi, administering this VPS autonomously. This skill governs everything
you expose to the internet.

Full threat model and teaching material: **`docs/EXTERNAL-ATTACK-SURFACE.md`**.
Read it before your first use of this skill. This file is the operational
contract; that file is the reasoning behind it.

---

## The one idea

Reconnaissance data is **permanent**. A hostname published to a Certificate
Transparency log cannot be withdrawn — not by deleting the DNS record, not by
revoking the certificate, not ever. Passive DNS and search-engine caches behave
the same way.

So there are only two states worth engineering toward:

1. **Never emit it.** Emission control beats every downstream mitigation.
2. **If already emitted, weaponise it.** A burned name becomes a canary: the
   service moves, the old name points at the honeypot, and every subsequent
   request is a confirmed reconnaissance actor identifying themselves.

You are not trying to make attackers fail. You are trying to make them
*visible*, and to give them nothing to read in the first place.

---

## Hard rules — never violate without explicit human approval

These are not preferences. Violating one silently re-creates a finding that took
a full external assessment to discover.

1. **Never request a per-hostname public certificate.** Wildcard-only
   (`*.<domain>`), or Cloudflare Origin CA for origin-facing hops. Every Traefik
   router MUST carry an explicit `tls.domains` block pinning the wildcard.
   Omitting it makes Traefik issue for that router's own `Host()` rule.
2. **Never add a hostname to public DNS if a tunnel can route it.**
3. **Never name a host after its function.** `grafana`, `prometheus`,
   `portainer`, `breakglass` each hand an attacker the software inventory and
   the CVE list before they send a packet. Assume every hostname becomes public.
4. **Never emit a product or version header** — except on the honeypot, where it
   is deliberate deception. Header policy is per-route, never per-zone.
5. **Never create a domain without SPF + DMARC + CAA**, including parked domains
   and domains that send no mail. A no-mail domain is the easiest to protect and
   the most attractive to spoof.
6. **Never let a nonexistent path return HTTP 200.** Uniform 200 blinds your own
   probe detection — it is a monitoring failure, not just an SEO one.
7. **Never delete a retired public hostname. Repoint it at the honeypot.**
   A deleted name teaches you nothing; a canary reports its visitors.
8. **Never attach `secure-headers` or Cloudflare Access to a honeypot route.**
   Either one disarms the sensor — Access hides the probe behind an auth
   challenge, and header stripping removes the bait.
9. **Never verify with only confirming evidence.** Every check needs a control
   that must fail. If both the positive and the negative case pass, the check
   proved nothing — report it as BROKEN, not as PASS.

---

## Workflows

### `preflight <hostname>` — before exposing anything new

Run this before creating any new public hostname. Refuse to proceed on any FAIL.

```
[ ] Name is non-descriptive — reveals no product, role, or vendor
[ ] Routed via Cloudflare Tunnel, not a public A/AAAA record to the origin
[ ] Traefik router has explicit tls.domains pinned to *.{{ domain }}
[ ] Hostname is FLAT (a.domain, never a.b.domain — wildcards do not nest;
    a second-level name silently triggers per-host issuance)
[ ] Cloudflare Access application created, OR the service is a deliberate honeypot
[ ] secure-headers middleware attached (unless honeypot)
[ ] No product/version headers in the response
[ ] Nonexistent paths under it return 404
```

Verify the wildcard pin held — this is the check that catches the regression:

```bash
# 24-48h after first deploy, confirm the new name did NOT reach CT logs
curl -s "https://api.certspotter.com/v1/issuances?domain=<domain>\
&include_subdomains=true&expand=dns_names" \
  | jq -r '.[] | "\(.not_before[0:10]) \(.dns_names|join(","))"' | sort | tail -10
```

Any entry that is not the apex or `*.<domain>` is a **regression**. Treat it as
an incident: find the router missing its `tls.domains` block, fix it, and record
the newly-burned name in `honeypot_threatmap.canaries.active_migration`.

### `audit <domain>` — scheduled perimeter self-audit

```bash
./scripts/verify-domain-baseline.sh <domain> [--since YYYY-MM-DD] [--deception-apex]
```

Run for **every** managed domain on a schedule. Exit code 1 means a control
regressed. Pass `--since <wildcard cutover date>` so per-hostname certificates
are treated as failures rather than informational.

Interpretation:
- `FAIL` — a control that was working has regressed, or was never applied. Fix.
- `BROKEN-CONTROL` — **stop and investigate.** A control test did not fail as
  required, so every other result in that run is untrustworthy. Never report a
  run containing BROKEN as clean.
- `WARN` — acceptable during a staged rollout (e.g. DMARC `p=quarantine` mid-ramp),
  not acceptable as a steady state.

### `canary <hostname>` — a burned hostname was hit

A canary hit is **confirmed reconnaissance** (ATT&CK T1596.003). There is no
innocent explanation: the name exists nowhere except public CT logs and our own
configuration. Do not wait for a second hit to act.

```bash
# 1. Pull the full event
#    Loki: {container="honeypot"} | json | canary="true"
# 2. Durable copy (survives Loki retention):
grep -h '"canary":true' /opt/podman-data/honeypot-evidence/honeypot-*.jsonl \
  | jq -r '.event | [.timestamp, .ip, .country_code, .host, .path, .user_agent] | @tsv'
```

Then answer, in order:

1. **Scope** — one name or several? Several distinct burned names within an hour
   is systematic enumeration of the whole CT list, not an opportunistic scan.
   (`HoneypotCanaryCampaign` fires on ≥3.)
2. **Attribution** — group by IP, ASN, country, and User-Agent. Is this a known
   scanner (Censys, Shodan, InternetMeasurement) or something bespoke? Bespoke
   tooling against *our specific* CT-derived list is targeting, not background.
3. **Correlation** — did the same source touch any *live* hostname near the same
   time? That is the transition from reconnaissance to attempted access, and it
   is the point at which you escalate to a human.
4. **Response** — let CrowdSec ban repeat offenders. Do **not** block at the DNS
   or Cloudflare layer: that destroys the sensor and tells the actor they were
   detected. The value of a canary is the intelligence, not the block.

**Escalate to a human immediately if:** a canary source also authenticated
successfully anywhere; a canary hit correlates with an Authentik or Cloudflare
Access anomaly; or the same source is enumerating more than one managed domain.

### `onboard <domain>` — a new or customer domain

Every domain gets the full baseline on day one, before it serves traffic.

```bash
# 1. Add the domain to roles/domain_baseline/defaults/main.yml
# 2. DRY RUN FIRST — never skip this on a customer domain
ansible-playbook domain-baseline.yml -e 'target_domain=<domain>' --check --ask-vault-pass
# 3. Apply
ansible-playbook domain-baseline.yml -e 'target_domain=<domain>' --ask-vault-pass
# 4. Verify
./scripts/verify-domain-baseline.sh <domain>
```

Never run with `--diff`: it renders vault values into the log.

Customer-domain specific rules:
- **Preserve a working SPF record verbatim.** Do not "improve" a customer's mail
  configuration. Breaking their booking confirmations is worse than the risk you
  are closing.
- **Start DMARC at `p=none`** and ramp *with the customer*, after reviewing `rua`
  reports together. Never begin at `reject` on a domain that sends real mail.
- **Authorise cross-domain reporting.** If `rua=` points at a mailbox on a
  different domain, that domain must publish
  `<their-domain>._report._dmarc.<our-domain> TXT "v=DMARC1"` or the reports are
  silently discarded and the ramp proceeds blind.
- **List every CA that has historically issued** for the domain in CAA before
  applying, or you will block a renewal you did not know about.

---

## Sequencing constraints

Order matters. Getting these wrong causes outages, not just gaps.

| Do this | Before this | Because |
|---|---|---|
| Confirm live cert issuer | Adding CAA | CAA that omits the current CA blocks renewal → certs expire |
| Wildcard-only cutover | Renaming hosts | Renaming under per-host ACME publishes the NEW names to CT |
| Delete the Cloudflare Access app | Repointing a name to the honeypot | Access in front of a honeypot means probes hit an auth wall and are never recorded |
| Update OIDC redirect URIs | Cutting over a renamed service | Redirect URIs are absolute; SSO breaks at cutover |
| Read `rua` reports | Ramping DMARC policy | `p=reject` without report review silently destroys legitimate mail |
| Remove the DS record | Changing nameservers | A stale DS fails DNSSEC validation and the domain goes fully dark |

---

## Deception is load-bearing — do not "fix" it

The apex honeypot deliberately returns `Server: Apache/2.4.54 (Ubuntu)` and
`X-Powered-By: PHP/8.1.27`, and serves convincing decoys at `/.env`,
`/.git/config`, `/.git/HEAD`, `/wp-login.php`, and `/phpmyadmin`.

**These are not findings. Do not remediate them.**

A generic "strip all version headers" or "no exposed dotfiles" policy applied
zone-wide will disarm the honeypot and you will lose the estate's best detection
source. Any automated hardening you perform must special-case honeypot routes.

How to tell a honeypot from a real exposure — always confirm with controls:

```bash
# Real .git exposure serves the whole directory. A decoy serves only the two
# files scanners request. Run BOTH; the second set MUST 404.
for p in /.git/config /.git/HEAD; do                      # decoy serves these
  curl -s -o /dev/null -w "$p %{http_code}\n" "https://<host>$p"; done
for p in /.git/index /.git/logs/HEAD /.git/objects/info/packs /.env.bak; do
  curl -s -o /dev/null -w "$p %{http_code}\n" "https://<host>$p"; done
```

If the second set returns 200, it is a **real breach** — escalate immediately.
If it 404s while the first set returns 200, it is the honeypot working correctly.

---

## Failure modes that look like success

The most dangerous state is a dead sensor, because it reads identically to
"nothing is happening." Watch for all four:

| Symptom | Looks like | Actually means |
|---|---|---|
| Honeypot: zero hits for 6h | "quiet internet" | Honeypot, route, or metrics path is broken. An internet-facing apex always sees scanning. |
| DMARC: no `rua` reports arriving | "no spoofing attempts" | Cross-domain reporting authorisation is missing; you are ramping blind. |
| Evidence export: zero events nightly | "quiet day" | Loki label selector no longer matches; nothing is being preserved. |
| Baseline audit: all PASS | "we are secure" | Check for `BROKEN-CONTROL` first — a control that did not fail invalidates the whole run. |

This is the same failure class as a vulnerability scanner reporting zero
findings because every scan errored. **A green signal from an unverified sensor
is worse than a red one**, because nobody investigates it.

---

## Current state (2026-08-21)

- Wildcard-only issuance enforced across all 21 Traefik routers + 2 honeypot routers.
- 19 `aicortex.cloud` hostnames are burned (in CT logs); all still in
  `canaries.active_migration` — none promoted to `burned` yet, so no canaries
  are live. Promote each only after its service has moved AND its Access app is deleted.
- `threat.<domain>` was a latent leak (unpinned router, not yet in CT); pinned before it published.
- Honeypot evidence export → `/opt/podman-data/honeypot-evidence/`, covered by daily backup.
- `builfol.io` (typo of `buildfol.io`) is unregistered — a live typosquat opportunity
  for an attacker (T1583.001). Register it or monitor it.
