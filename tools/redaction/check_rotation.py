#!/usr/bin/env python3
"""Answer one question about a leaked credential: is it still the live value?

THE QUESTION
------------
You are handed a list of secrets someone says leaked. For each one you need to
know whether it is STILL IN USE -- i.e. whether it is the value the estate is
currently deployed with -- or whether it has already been rotated away.

HOW IT ANSWERS
--------------
Each candidate is HMAC'd with the same key that built the registry and looked up
against the registry's unfiltered `all_values` index (every vault value, not the
redaction subset -- see build_secret_registry.py for why those differ).

  HIT  -> the leaked string IS the value currently in the vault. NOT rotated.
          You also learn which vault key it is, so you know what to rotate.
  MISS -> it is NOT the current deployed value.

WHAT A MISS DOES AND DOES NOT PROVE
-----------------------------------
A miss proves the string is not what the estate deploys today. That is strong
evidence of rotation, but it is NOT proof the credential is dead: only the
provider can tell you whether an old AWS key still authenticates. A key can also
be live at the provider while the vault has moved on (someone rotated the vault
but never revoked the old one) -- which is the dangerous case, and precisely the
one a miss would otherwise let you dismiss.

So: HIT means "rotate this now". MISS means "verify revocation at the provider",
not "safe".

Nor does a miss mean the secret was never yours -- a credential that never lived
in the vault (a pasted third-party token, an ad-hoc key) misses for that reason
alone. The registry only knows what the vault knows.

NO PLAINTEXT IN THE TRANSCRIPT
------------------------------
Candidates are read from a FILE, one per line -- never from argv (visible in
`ps`, captured verbatim in transcripts) and never pasted into a session. Output
names vault keys and match/no-match only. No candidate value is ever echoed,
including on error.

Usage:
  ./check_rotation.py --registry R.json --hmac-key-file K --candidates leaked.txt
  ./check_rotation.py --registry R.json --hmac-key-file K --scan-corpus DIR
  ./check_rotation.py --selftest
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Reuse the scanner's pattern set so --scan-corpus finds the same things the
# inventory did. Kept local (not imported) so this tool has no dependency on a
# script living in ~/session-archive.
CRED_PATTERNS = [
    ("aws_access_key_id",    re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_key",       re.compile(r"aws_secret_access_key[\"'\s:=]+([A-Za-z0-9/+=]{40})", re.I)),
    ("google_api_key",       re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("github_token",         re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b")),
    ("github_pat",           re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b")),
    ("anthropic_key",        re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{20,}\b")),
    ("openai_key",           re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9\-_]{32,}\b")),
    ("slack_token",          re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("telegram_bot_token",   re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b")),
    ("tailscale_key",        re.compile(r"\btskey-[a-z]+-[A-Za-z0-9\-]{10,}\b")),
    ("age_secret_key",       re.compile(r"\bAGE-SECRET-KEY-1[A-Z0-9]{50,}\b")),
    ("db_uri_password",      re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s:@/]+:([^\s@/]{6,})@")),
    ("pgpassword_env",       re.compile(r"PGPASSWORD[=:\s\"']+([^\s\"';|&]{6,})")),
]


def h(key: bytes, value: str) -> str:
    return hmac.new(key, value.strip().encode("utf-8"), hashlib.sha256).hexdigest()


def load_registry(path: Path, key: bytes) -> dict:
    reg = json.loads(path.read_text())
    expect = hashlib.sha256(key).hexdigest()[:12]
    if reg.get("key_id") != expect:
        raise SystemExit(
            f"KEY MISMATCH: registry was built with key_id={reg.get('key_id')}, "
            f"this key is {expect}.\n"
            "Every lookup would MISS and the report would read 'all rotated' -- "
            "the most dangerous possible wrong answer. Refusing to run."
        )
    if not reg.get("all_values"):
        raise SystemExit("registry has no all_values index -- rebuild it")
    return reg


def check(reg: dict, key: bytes, candidates: list[str]) -> list[dict]:
    idx = reg["all_values"]
    out = []
    for i, cand in enumerate(candidates, 1):
        c = cand.strip()
        if not c:
            continue
        entry = idx.get(h(key, c))
        out.append({
            "n": i,
            # Identify the candidate WITHOUT revealing it. 4 chars of prefix plus
            # length is enough to match up against an external list by eye.
            "fingerprint": f"{c[:4]}...({len(c)} chars)",
            "live": entry is not None,
            "vault_key": entry["label"] if entry else None,
        })
    return out


def scan_corpus(root: Path):
    """Extract credential-shaped strings from the JSONL archive."""
    found: dict[str, dict] = {}
    files = sorted(root.rglob("*.jsonl"))
    for i, f in enumerate(files, 1):
        if i % 500 == 0:
            print(f"  scanned {i:,}/{len(files):,} files...", flush=True)
        try:
            with f.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    for name, pat in CRED_PATTERNS:
                        for m in pat.finditer(line):
                            val = (m.group(1) if m.groups() else m.group(0)).strip()
                            e = found.setdefault(val, {"kind": name, "hits": 0, "files": set()})
                            e["hits"] += 1
                            e["files"].add(f.name)
        except OSError:
            continue
    return files, found


def selftest() -> int:
    """CONTROL: a known-live value must HIT and a known-absent one must MISS.

    Testing only the hit side is worthless here -- a matcher that returns True
    for everything passes it. Testing only the miss side is worse: a matcher
    that returns False for everything passes, and reports every leaked
    credential as 'already rotated'. That is the failure this tool exists to
    avoid, so both halves are asserted.
    """
    key = b"selftest-key-not-a-real-secret"
    live = "wJalrXUtnFEMIK7MDENGbPxRfiCYQWERTZUIOPAS"
    rotated = "OLDKEYaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    reg = {
        "key_id": hashlib.sha256(key).hexdigest()[:12],
        "all_values": {h(key, live): {"label": "aws_secret_access_key", "len": len(live)}},
    }
    res = check(reg, key, [live, rotated])
    fail = False
    if not res[0]["live"]:
        print("CONTROL FAILED -- a value that IS in the vault reported as rotated.")
        fail = True
    if res[1]["live"]:
        print("CONTROL FAILED -- a value NOT in the vault reported as live.")
        fail = True
    if res[0]["vault_key"] != "aws_secret_access_key":
        print("CONTROL FAILED -- hit did not name the right vault key.")
        fail = True
    # The key-mismatch guard must actually fire. Without it, running with the
    # wrong key produces an all-miss report that reads "everything is already
    # rotated" -- the most dangerous wrong answer this tool could give. Exercise
    # load_registry() for real against a temp file rather than simulating it.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(reg, fh)
        regpath = Path(fh.name)
    try:
        load_registry(regpath, b"a-completely-different-key")
        print("CONTROL FAILED -- wrong key was ACCEPTED. Every lookup would miss and "
              "the report would wrongly read 'all rotated'.")
        fail = True
    except SystemExit:
        pass          # expected
    finally:
        regpath.unlink(missing_ok=True)

    if fail:
        return 1
    print("CONTROL PASSED -- live value HIT, rotated value MISSED, key guard fires.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry")
    ap.add_argument("--hmac-key-file")
    ap.add_argument("--candidates", help="file of leaked values, one per line (mode 0600)")
    ap.add_argument("--scan-corpus", help="JSONL archive dir: cross-check what actually leaked")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    print("running control first...")
    if selftest() != 0:
        return 1
    print()

    if not (args.registry and args.hmac_key_file):
        print("--registry and --hmac-key-file are required", file=sys.stderr)
        return 2

    key = Path(args.hmac_key_file).read_bytes().strip()
    reg = load_registry(Path(args.registry), key)
    print(f"registry key_id={reg['key_id']} — {len(reg['all_values'])} vault values indexed\n")

    if args.candidates:
        cands = Path(args.candidates).read_text().splitlines()
        rows = check(reg, key, cands)
        live = [r for r in rows if r["live"]]
        print(f"{'#':>3}  {'candidate':22} {'status':12} vault key")
        print("-" * 72)
        for r in rows:
            status = "STILL LIVE" if r["live"] else "not current"
            print(f"{r['n']:>3}  {r['fingerprint']:22} {status:12} {r['vault_key'] or '-'}")
        print("-" * 72)
        print(f"\n{len(live)} of {len(rows)} are the CURRENT deployed value — rotate these now.")
        print(f"{len(rows) - len(live)} are not current. That is evidence of rotation, NOT proof")
        print("of revocation — confirm at the provider before considering them dead.")
        return 0

    if args.scan_corpus:
        root = Path(args.scan_corpus)
        print(f"scanning {root} for credential-shaped strings...")
        files, found = scan_corpus(root)
        print(f"\nscanned {len(files):,} files, {len(found):,} distinct credential-shaped values\n")

        rows = check(reg, key, list(found))
        by_val = {r["fingerprint"]: r for r in rows}

        live_rows = []
        for val, meta in found.items():
            r = by_val.get(f"{val[:4]}...({len(val)} chars)")
            if r and r["live"]:
                live_rows.append((meta["kind"], r["fingerprint"], r["vault_key"],
                                  meta["hits"], len(meta["files"])))

        print(f"{'kind':20} {'value':22} {'vault key':30} {'hits':>6} {'files':>6}")
        print("-" * 92)
        for kind, fp, vk, hits, nf in sorted(live_rows, key=lambda x: -x[3]):
            print(f"{kind:20} {fp:22} {vk or '-':30} {hits:6,} {nf:6,}")
        print("-" * 92)
        print(f"\n{len(live_rows)} of {len(found)} leaked values are STILL THE LIVE VALUE.")
        print("These are unrotated and exposed in the corpus. Rotate them.")
        kinds = Counter(k for k, *_ in live_rows)
        for k, c in kinds.most_common():
            print(f"   {c:3}  {k}")
        print(f"\n{len(found) - len(live_rows)} leaked values are not current vault values —")
        print("either already rotated, or never vault-managed. Neither is proof of revocation.")
        return 0

    print("nothing to do: pass --candidates or --scan-corpus", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:                     # noqa: BLE001 - deliberate
        print(f"FATAL: {type(e).__name__} (message suppressed — may contain a credential)",
              file=sys.stderr)
        sys.exit(3)
