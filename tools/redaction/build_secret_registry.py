#!/usr/bin/env python3
"""Build an HMAC-only registry of known secrets from the Ansible vault.

WHY A REGISTRY AT ALL
---------------------
Prefix-anchored patterns (AKIA, sk-ant-, ghp_, ...) catch shape-specific
credentials with ~zero false positives. They cannot catch the ones with no
distinguishing shape: AWS *secret* access keys, Cloudflare tokens, and DB
passwords. Those are just 40 random characters. The only way to match them
without guessing is to know what they are -- which the vault does.

WHY HMAC AND NOT PLAINTEXT
--------------------------
Ingestion runs on the VPS (/opt/compose/session-ingestion/ingest-sessions.py).
Shipping decrypted vault values there would create a NEW plaintext copy of all
124 secrets on the box -- strictly worse than the leak being fixed. So the
artifact that travels is hashes only, and the matcher hashes candidate tokens
out of the text to compare. Nothing plaintext is ever written to disk, here or
there.

The HMAC key must be secret: without one, a bare hash of a weak password is a
rainbow-table lookup. It is keyed, so the registry is safe at rest.

THE FALSE-POSITIVE HAZARD, AND WHY VALUES ARE FILTERED
------------------------------------------------------
Exact-matching every vault value is dangerous. If some key's value is
`postgres` or `admin`, redacting it corrupts ordinary prose across the whole
corpus -- the tier-3 lesson from the handoff, where `password_assignment` hits
were URL fragments. Values are therefore admitted only above a length and
entropy floor, and everything excluded is reported by NAME and REASON (never
value) so the exclusions can be reviewed rather than silently trusted.

This script NEVER prints a secret. Output is key names, lengths, entropies.

Usage:
  ./build_secret_registry.py --hmac-key-file KEYFILE --out registry.json
  ./build_secret_registry.py --selftest
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

VAULT_REPO = Path.home() / "Projects" / "VScdeProjects" / "vps_setup"

# Admission thresholds. A value must clear BOTH to be matchable.
#
# 12 chars: below this, collisions with ordinary text stop being hypothetical.
# 3.0 bits/char: `correcthorsebattery` is long but low-entropy and appears in
# prose; a real 40-char token sits well above 4.0. Measured distribution is
# printed by --stats so these can be tuned against reality, not taste.
MIN_LEN = 12
MIN_ENTROPY = 3.0

# Values that are structurally not credentials even when long and random-ish.
# A URL or a file path can clear the entropy floor and would be catastrophic to
# redact -- paths are load-bearing content in this corpus.
STRUCTURAL_EXCLUDE = re.compile(
    r"^(?:https?://|/|~/|\./|[A-Za-z]:\\)"       # url or path
    r"|^\S+@\S+\.\S+$"                            # bare email
    r"|^[0-9.]+$"                                 # ip / version / number
    r"|^[0-9a-f]{8}-[0-9a-f]{4}-"                 # uuid (identifiers, not secrets)
    , re.I,
)

PLACEHOLDER = re.compile(
    r"YOUR_|_HERE|EXAMPLE|PLACEHOLDER|CHANGEME|CHANGE_ME|xxxx|XXXX|\*{4,}"
    r"|<[a-z0-9_\- ]+>|REDACTED|dummy|sample|\bfake\b|test[_-]?key",
    re.I,
)

# ---------------------------------------------------------------------------
# NAME-BASED CLASSIFICATION -- the primary discriminator.
#
# A vault holds secrets AND config, and value shape cannot tell them apart:
# `NEO4J_PASSWORD` is 10 chars (below any sane length floor) and `NEO4J_URI` is
# 17 chars of high-entropy-looking text. Judging by shape alone excluded the
# real password and admitted the URI -- exactly backwards. The key NAME says
# which is which, so it decides, and shape only guards against the residue.
#
# Getting this wrong is asymmetric: admitting config corrupts the corpus
# (hostnames and URIs are load-bearing content in transcripts), while excluding
# a secret merely leaves it for the tier-1 patterns. Hence: when the name says
# config, that wins; when the name says secret but the shape looks unsafe, the
# value goes to REVIEW rather than being silently admitted or silently dropped.
# ---------------------------------------------------------------------------

SECRET_NAME = re.compile(
    r"password|passwd|secret|token|api[_-]?key|apikey|credential|privkey"
    r"|private[_-]?key|access[_-]?key|license[_-]?key|client[_-]?secret"
    r"|[_-]key$|^.*_pass$|auth[_-]?key|master[_-]?key|salt",
    re.I,
)

# Checked BEFORE the secret pattern: `gpg_key_email` contains "key" but is an
# email; `openwebui_oidc_client_id` contains "client" but is a public id.
NONSECRET_NAME = re.compile(
    r"_url$|_uri$|_host$|_hostname$|_email$|_port$|_name$|_id$|_ids$"
    r"|username|user_ids|_lat$|_lon$|domain|account_id|key_type|key_name"
    r"|_region$|_bucket$|_project$|_zone$|_endpoint$|voice_id|engine",
    re.I,
)


def shannon(s: str) -> float:
    """Bits of entropy per character."""
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def flatten(obj, prefix=""):
    """Yield (dotted_key, str_value) for every string leaf in the vault map."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from flatten(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from flatten(v, f"{prefix}[{i}]")
    elif isinstance(obj, str):
        yield prefix, obj


# A name-confirmed secret is allowed below the generic floors, but not without
# limit: an 8-char dictionary word is still catastrophic to exact-match.
SECRET_MIN_LEN = 8
SECRET_MIN_ENTROPY = 2.5


def is_placeholder(v: str) -> bool:
    """True only if the placeholder marker dominates the value.

    A 45-char random license key that happens to contain the letters 'fake'
    is not a placeholder. `YOUR_API_KEY_HERE` is. Require the match to cover a
    real fraction of the value, or the value to be short enough that a marker
    substring means the whole thing is a stub.
    """
    m = PLACEHOLDER.search(v)
    if not m:
        return False
    return len(v) < 24 or (m.end() - m.start()) / len(v) >= 0.40


def classify(label: str, value: str) -> tuple[str, str]:
    """Return (verdict, reason) where verdict is admit | exclude | review."""
    v = value.strip()
    name = label.split(".")[-1]
    if not v:
        return "exclude", "empty"

    # Config wins outright -- redacting a hostname or URI corrupts real content.
    if NONSECRET_NAME.search(name):
        return "exclude", "name_says_config"

    named_secret = bool(SECRET_NAME.search(name))

    if is_placeholder(v):
        # A named secret holding a placeholder is worth surfacing: it may mean
        # the real value lives somewhere else entirely.
        return ("review", "named_secret_but_placeholder") if named_secret else ("exclude", "placeholder")

    if STRUCTURAL_EXCLUDE.search(v):
        # A UUID-shaped api_key is still a credential; a UUID-shaped *_id is not.
        return ("admit", "named_secret_uuid_shaped") if named_secret else ("exclude", "structural")

    e = shannon(v)

    if not named_secret:
        if len(v) < MIN_LEN:
            return "exclude", f"too_short(<{MIN_LEN})"
        if e < MIN_ENTROPY:
            return "exclude", f"low_entropy({e:.2f}<{MIN_ENTROPY})"
    else:
        # Below the absolute floor, even a named secret is too collision-prone
        # to exact-match. Tier-1 patterns remain the safety net for these.
        if len(v) < SECRET_MIN_LEN:
            return "exclude", f"named_secret_but_far_too_short({len(v)}<{SECRET_MIN_LEN})"
        if e < SECRET_MIN_ENTROPY:
            return "review", f"named_secret_but_low_entropy({e:.2f})"
        # The 8..11 band: almost certainly a real credential, but short enough
        # that exact-matching it across 244 MB of text could strike real prose.
        # Refuse to decide silently -- this is the `NEO4J_PASSWORD` case.
        if len(v) < MIN_LEN:
            return "review", f"named_secret_but_short({len(v)}<{MIN_LEN})"

    if named_secret:
        return "admit", "named_secret"
    # Unnamed but long and high-entropy: probably a credential, but say so.
    return "admit", "shape_only(name_not_conclusive)"


def read_vault(repo: Path) -> dict:
    """Decrypt the vault to memory. Never touches disk.

    Runs from INSIDE the repo so ansible.cfg supplies vault_password_file --
    passing --vault-password-file as well triggers the 'vault-ids
    default,default' error on some subcommands (documented estate gotcha).
    """
    proc = subprocess.run(
        ["ansible-vault", "view", "vault.yml"],
        cwd=str(repo), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        # stderr may legitimately be shown: ansible does not echo the vault body
        # on failure, only the reason.
        raise SystemExit(f"vault decrypt failed (rc={proc.returncode}): {proc.stderr.strip()[:400]}")

    # The vault contains at least one `key:<TAB>"value"` line, which is not legal
    # YAML. Normalise the separator IN MEMORY only -- never rewrite vault.yml,
    # which is gitignored and has been destroyed once by a botched re-encrypt.
    text, retabbed = re.subn(r"(?m)^([ \t]*[A-Za-z0-9_.\-]+:)[ \t]*\t[ \t]*", r"\1 ", proc.stdout)
    if retabbed:
        names = re.findall(r"(?m)^[ \t]*([A-Za-z0-9_.\-]+):[ \t]*\t", proc.stdout)
        print(f"  note: normalised {retabbed} tab-separated vault line(s) in memory: "
              f"{', '.join(sorted(set(names))) or '(unnamed)'}")
        print("  these keys are likely UNREADABLE to Ansible itself -- worth fixing at source")

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        # NEVER let the exception through: PyYAML's message embeds the offending
        # source line, which is a secret. Report position only.
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1}" if mark else "unknown position"
        problem = getattr(e, "problem", "parse error")
        raise SystemExit(
            f"vault YAML is malformed at {where}: {problem}\n"
            f"(the offending line is NOT shown -- it contains a secret)"
        ) from None
    if not isinstance(data, dict) or not data:
        raise SystemExit(
            "vault decrypted to nothing usable. REFUSING to emit an empty registry -- "
            "this is the failure mode where a broken tool returns the hash of the empty "
            "string and looks like a real answer."
        )
    return data


def build(repo: Path, hmac_key: bytes) -> dict:
    vault = read_vault(repo)
    entries: dict[str, dict] = {}
    excluded: list[dict] = []
    review: list[dict] = []
    all_values: dict[str, dict] = {}   # EVERY value, for rotation checking
    seen_values: dict[str, str] = {}   # hmac -> first label, to collapse duplicates

    for label, value in flatten(vault):
        verdict, reason = classify(label, value)
        v = value.strip()

        # The `all` index is deliberately unfiltered. The admission filter exists
        # to stop over-redaction of free text; a rotation check compares a known
        # list against a known list, where false positives are impossible. Using
        # the redaction filter there would wrongly report config-shaped secrets
        # (and every short password) as "already rotated".
        if v:
            ah = hmac.new(hmac_key, v.encode("utf-8"), hashlib.sha256).hexdigest()
            all_values.setdefault(ah, {"label": label, "len": len(v)})

        if verdict == "review":
            review.append({"label": label, "len": len(v),
                           "entropy": round(shannon(v), 2), "reason": reason})
            continue
        if verdict == "exclude":
            excluded.append({"label": label, "len": len(v),
                             "entropy": round(shannon(v), 2), "reason": reason})
            continue
        h = hmac.new(hmac_key, v.encode("utf-8"), hashlib.sha256).hexdigest()
        if h in seen_values:
            # Same value under two vault keys -- keep the first label, note the alias.
            entries[h].setdefault("aliases", []).append(label)
            continue
        seen_values[h] = label
        entries[h] = {"label": label, "len": len(v), "entropy": round(shannon(v), 2)}

    # Length index: the matcher only needs to hash candidate tokens whose length
    # appears here, which is what makes hash-only matching tractable.
    lengths = sorted({e["len"] for e in entries.values()})

    return {
        "version": 1,
        "created": datetime.now(timezone.utc).isoformat(),
        # Identifies WHICH key built this without revealing it. A matcher whose
        # key_id disagrees with the registry's would silently match nothing.
        "key_id": hashlib.sha256(hmac_key).hexdigest()[:12],
        "min_len": MIN_LEN,
        "min_entropy": MIN_ENTROPY,
        "lengths": lengths,
        "entries": entries,
        "excluded": excluded,
        "review": review,
        # Unfiltered index of every vault value, for rotation checking only.
        # NOT used by the redactor -- see the comment in build().
        "all_values": all_values,
    }


SELFTEST_VAULT = {
    # --- must be ADMITTED (real secrets) ---
    "aws_secret_access_key": "wJalrXUtnFEMIK7MDENGbPxRfiCYQWERTZUIOPAS",
    "cloudflare_api_token": "Xk92mQp4Lz7Ry1Nv8Bw3Ct6Hs0Jd5Fg2Ae4Ui7Oq",
    "postgres_password": "Tr0ub4dor&3xKcd9Zz",
    # UUID-shaped but named a key -- the liveavatar_api_key case, wrongly
    # excluded as "structural" before names were consulted.
    "liveavatar_api_key": "6f1c2b7e-9a3d-4f58-b0c1-2d7e8a9f4b3c",
    # Long random value that merely CONTAINS a placeholder word by chance --
    # the maxmind_license_key case.
    "maxmind_license_key": "q7Rk2WsampleZx9Vb4Nm1Ct8Hs0Jd5Fg2Ae4Ui7OqLpXy",

    # --- must be EXCLUDED (config, not credentials) ---
    "db_user": "postgres",
    "admin_user": "admin",
    "some_url": "https://chat.aicortex.cloud/api/v1/endpoint",
    "repo_path": "/workspace/vscode-projects/vps_setup",
    "example_key": "YOUR_API_KEY_HERE",
    "low_entropy": "aaaaaaaaaaaaaaaaaaaa",
    "port": "5432",
    # These were wrongly ADMITTED before names were consulted. Redacting a URI
    # or an SMTP host would corrupt real content across the whole corpus.
    "NEO4J_URI": "bolt://10.89.0.44:7687",
    "authentik_smtp_host": "smtp.mailgun.org",
    "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM",

    # --- must land in REVIEW (named a secret, but shape is unsafe) ---
    # The NEO4J_PASSWORD case: a genuine secret below the generic length floor.
    "NEO4J_PASSWORD": "sh0rtPwd",
}


def selftest() -> int:
    """CONTROL: admission must admit, reject, AND defer -- and the reject side is
    the one that matters. A filter that admits everything would redact the corpus
    to rubble; a filter that admits nothing produces an empty registry that
    reports a clean scan forever. Every fixture here is a real mistake this
    classifier made on the actual vault before names were consulted."""
    key = b"selftest-key-not-a-real-secret"
    must_admit = {"aws_secret_access_key", "cloudflare_api_token", "postgres_password",
                  "liveavatar_api_key", "maxmind_license_key"}
    must_reject = {"db_user", "admin_user", "some_url", "repo_path", "example_key",
                   "low_entropy", "port", "NEO4J_URI", "authentik_smtp_host",
                   "elevenlabs_voice_id"}
    must_review = {"NEO4J_PASSWORD"}

    admitted, rejected, reviewed = set(), {}, set()
    for label, value in flatten(SELFTEST_VAULT):
        verdict, reason = classify(label, value)
        if verdict == "admit":
            admitted.add(label)
        elif verdict == "review":
            reviewed.add(label)
        else:
            rejected[label] = reason

    fail = False
    missed = must_admit - admitted
    if missed:
        print(f"CONTROL FAILED -- real secrets were NOT admitted: {sorted(missed)}")
        fail = True
    leaked = must_reject & admitted
    if leaked:
        print(f"CONTROL FAILED -- these should have been rejected: {sorted(leaked)}")
        print("  Admitting these would exact-match hostnames/URIs across the corpus.")
        fail = True
    lost = must_review - reviewed
    if lost:
        print(f"CONTROL FAILED -- these should have gone to REVIEW, not been decided "
              f"silently: {sorted(lost)}")
        fail = True

    # Positive control on the hashing itself: the same value must hash the same,
    # a different value must not. Without this, "0 matches" could mean the HMAC
    # is broken rather than that nothing matched.
    h1 = hmac.new(key, b"identical", hashlib.sha256).hexdigest()
    h2 = hmac.new(key, b"identical", hashlib.sha256).hexdigest()
    h3 = hmac.new(key, b"different", hashlib.sha256).hexdigest()
    if h1 != h2:
        print("CONTROL FAILED -- hashing is not deterministic")
        fail = True
    if h1 == h3:
        print("CONTROL FAILED -- distinct values collide; the matcher would redact everything")
        fail = True

    # And the key must actually be keyed: a different key must give a different hash.
    if h1 == hmac.new(b"other-key", b"identical", hashlib.sha256).hexdigest():
        print("CONTROL FAILED -- the HMAC key is not being used")
        fail = True

    if fail:
        return 1
    # NB: "not admitted" is the property that matters for the unsafe set -- an
    # unsafe value routed to REVIEW is still not being redacted, which is the
    # guarantee. Reporting it as a reject/review split would imply a precision
    # the control does not actually assert.
    print(f"CONTROL PASSED -- admitted {len(admitted)}/{len(must_admit)} real secrets, "
          f"kept {len(must_reject - admitted)}/{len(must_reject)} unsafe values out of the "
          f"matcher, deferred {len(must_review & reviewed)}/{len(must_review)} to review; "
          f"hashing is keyed and stable.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(VAULT_REPO))
    ap.add_argument("--hmac-key-file", help="file containing the HMAC key (mode 0600)")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--stats", action="store_true", help="print the entropy/length distribution")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    print("running control first...")
    if selftest() != 0:
        print("refusing to build a registry while the admission control is failing")
        return 1
    print()

    if not args.hmac_key_file or not args.out:
        print("--hmac-key-file and --out are required", file=sys.stderr)
        return 2

    key = Path(args.hmac_key_file).read_bytes().strip()
    if len(key) < 16:
        raise SystemExit("HMAC key is too short (<16 bytes) -- refusing")

    reg = build(Path(args.repo), key)

    n_ok, n_ex = len(reg["entries"]), len(reg["excluded"])
    print(f"vault values admitted : {n_ok}")
    print(f"vault values excluded : {n_ex}")
    print(f"vault values in REVIEW: {len(reg['review'])}")
    print(f"all values (rotation) : {len(reg['all_values'])}")

    if reg["review"]:
        print("\nREVIEW -- named like secrets but shaped unsafely. Decide each:")
        for e in sorted(reg["review"], key=lambda x: -x["len"]):
            print(f"  {e['len']:4}ch  ent={e['entropy']:.2f}  {e['reason']:34} {e['label']}")
    print(f"distinct lengths      : {len(reg['lengths'])}  {reg['lengths'][:12]}{'...' if len(reg['lengths']) > 12 else ''}")
    print(f"key_id                : {reg['key_id']}")

    by_reason = Counter(e["reason"].split("(")[0] for e in reg["excluded"])
    print("\nexclusions by reason:")
    for r, c in by_reason.most_common():
        print(f"  {c:4}  {r}")

    if args.stats:
        print("\nadmitted, by length:")
        for label, e in sorted(reg["entries"].items(), key=lambda kv: kv[1]["len"]):
            print(f"  {e['len']:4}ch  ent={e['entropy']:.2f}  {e['label']}")
        print("\nEXCLUDED -- review these; a real secret hiding here would be missed:")
        for e in sorted(reg["excluded"], key=lambda x: -x["len"]):
            print(f"  {e['len']:4}ch  ent={e['entropy']:.2f}  {e['reason']:32} {e['label']}")

    out = Path(args.out)
    out.write_text(json.dumps(reg, indent=2))
    out.chmod(0o600)
    print(f"\nwrote {out}  (HMAC only -- contains no secret values)")
    return 0


if __name__ == "__main__":
    # Blanket guard: this process holds decrypted vault content in memory, and an
    # uncaught traceback can quote it (PyYAML's ScannerError embeds the offending
    # source line -- that is not hypothetical, it leaked a live key on
    # 2026-08-10). Report the exception TYPE only; never its message or frames.
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:                     # noqa: BLE001 - deliberate
        print(f"FATAL: {type(e).__name__} (message suppressed -- may contain vault content)",
              file=sys.stderr)
        sys.exit(3)
