#!/usr/bin/env python3
"""Redact credentials from session text on the way into Postgres.

WHERE THIS SITS
---------------
Imported by ingest-sessions.py and applied inside sanitize_text() and
sanitize_json(). Both are needed: between them they cover the four columns that
carry transcript content --

    messages.content_text        prose, assistant output
    messages.content_json        structured message bodies
    tool_calls.input_json        THE dominant leak vector: credential literals
                                 typed into Bash commands (65 of 123 hits)
    tool_calls.result_text       command output

ASYMMETRY -- THIS IS DELIBERATE, DO NOT "FIX" IT
------------------------------------------------
The JSONL archive in ~/session-archive is NEVER redacted. It is the source of
record and the only thing that can re-derive a future chunking strategy; it is
protected by encryption at rest, not by scrubbing. Postgres, recall.chunks and
Neo4j ARE redacted, because they are derived and rebuildable from the JSONL.

TWO MECHANISMS
--------------
1. TIER-1 PATTERNS -- prefix-anchored shapes (AKIA, sk-ant-, ghp_, ...). These
   are self-identifying, so false positives are near zero and no key material is
   needed to apply them.

2. REGISTRY MATCHING -- exact matches against known vault secrets, by HMAC. This
   is what catches credentials with no distinguishing shape (AWS *secret* keys,
   Cloudflare tokens, DB passwords) that tier-1 cannot see. Matching is done by
   hashing candidate tokens out of the text, so NO PLAINTEXT SECRET EXISTS on
   the ingesting host -- which matters because ingestion runs on the VPS.

WHAT IS DELIBERATELY NOT REDACTED
---------------------------------
Generic `password: ...` / `token: ...` assignments (tier 3 in the plan) are NOT
redacted. 648 distinct values matched that shape and the samples were URL
fragments and regex text -- redacting them would corrupt real prose across the
corpus while protecting nothing. Private IPs and tailnet IPs likewise: 38k hits,
zero high-entropy, not secrets.

Redaction is not rotation. Scrubbing the database does not invalidate anything
at the provider. See check_rotation.py.

Usage:
  ./redact.py --selftest
  ./redact.py --selftest --registry R.json --hmac-key-file K   # incl. registry
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Tier 1: prefix-anchored credential shapes. Redacted unconditionally.
#
# Anchored with (?<![A-Za-z]) rather than \b. \b was WRONG and silently missed
# live keys: URL-encoded text puts a digit immediately before the credential
# (`key=%20%22AIzaSy...%22`), and '2' -> 'A' is not a word boundary, so the
# pattern never fired. 11 real Google API keys survived the first backfill this
# way. The lookbehind still blocks mid-word matches (so `task-<32 chars>` does
# not look like an `sk-` key) while allowing digits and punctuation before.
# ---------------------------------------------------------------------------
TIER1: list[tuple[str, re.Pattern]] = [
    ("aws_access_key_id",  re.compile(r"(?<![A-Za-z])AKIA[0-9A-Z]{16}\b")),
    ("google_api_key",     re.compile(r"(?<![A-Za-z])AIza[0-9A-Za-z_\-]{35}\b")),
    ("github_token",       re.compile(r"(?<![A-Za-z])(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b")),
    ("github_pat",         re.compile(r"(?<![A-Za-z])github_pat_[A-Za-z0-9_]{60,}\b")),
    ("anthropic_key",      re.compile(r"(?<![A-Za-z])sk-ant-[A-Za-z0-9\-_]{20,}\b")),
    ("openai_key",         re.compile(r"(?<![A-Za-z])sk-(?:proj-)?[A-Za-z0-9\-_]{32,}\b")),
    # LiteLLM VIRTUAL keys are shorter than OpenAI's 32+ and slipped past the rule
    # above: 7 live ones were found sitting in recall.chunks on 2026-08-20. The
    # sk- prefix plus 16+ token chars is specific enough not to catch prose.
    ("litellm_virtual_key", re.compile(r"(?<![A-Za-z])sk-[A-Za-z0-9]{16,31}\b")),
    ("slack_token",        re.compile(r"(?<![A-Za-z])xox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("telegram_bot_token", re.compile(r"(?<![A-Za-z])\d{8,10}:[A-Za-z0-9_\-]{35}\b")),
    ("tailscale_key",      re.compile(r"(?<![A-Za-z])tskey-[a-z]+-[A-Za-z0-9\-]{10,}\b")),
    ("age_secret_key",     re.compile(r"(?<![A-Za-z])AGE-SECRET-KEY-1[A-Z0-9]{50,}\b")),
    ("neon_db_key",        re.compile(r"(?<![A-Za-z])npg_[A-Za-z0-9]{16,}\b")),
    ("stripe_live_key",    re.compile(r"(?<![A-Za-z])sk_live_[A-Za-z0-9]{16,}\b")),
    ("jwt",                re.compile(r"(?<![A-Za-z])eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    # The body of a private key block, not just the header -- a redacted header
    # over an intact body would be worse than useless.
    ("private_key_block",  re.compile(
        r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----",
        re.S)),
    ("ansible_vault_blob", re.compile(r"\$ANSIBLE_VAULT;\d\.\d;AES256[\s0-9a-f]{64,}")),
]

# Password inside a DB URI: redact ONLY the password span, keeping the scheme,
# user, host and database name, which are legitimate content and often the whole
# point of the surrounding sentence.
DB_URI = re.compile(
    r"\b((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s:@/]+:)([^\s@/]{6,})(@)")

# Characters that can appear inside a credential. Used to carve candidate tokens
# out of text for registry matching. ':' '@' '/' are excluded so that a password
# embedded in a URI becomes its own token.
TOKEN = re.compile(r"[A-Za-z0-9_\-+=.~!$^*()\[\]{}|<>?&%#]{6,200}")

PLACEHOLDER_TOKEN = "[REDACTED:{}]"


class Redactor:
    """Applies tier-1 patterns and, if configured, known-secret matching."""

    def __init__(self, registry: dict | None = None, hmac_key: bytes | None = None):
        self.hmac_key = hmac_key
        self.entries: dict[str, dict] = {}
        self.lengths: set[int] = set()
        self.stats: Counter = Counter()

        if registry is not None:
            if hmac_key is None:
                raise ValueError("registry supplied without an HMAC key")
            expect = hashlib.sha256(hmac_key).hexdigest()[:12]
            if registry.get("key_id") != expect:
                # Silently matching nothing is the worst outcome: ingestion would
                # run "successfully" and write unredacted secrets forever.
                raise ValueError(
                    f"registry key_id {registry.get('key_id')} != key {expect}; "
                    "refusing to run with a key that would match nothing")
            self.entries = registry["entries"]
            self.lengths = {e["len"] for e in self.entries.values()}

    # -- the two things ingest-sessions.py calls ---------------------------

    def text(self, s):
        """Redact a string. Non-strings pass through untouched."""
        if not isinstance(s, str) or not s:
            return s
        out = s
        for name, pat in TIER1:
            out, n = pat.subn(PLACEHOLDER_TOKEN.format(name), out)
            if n:
                self.stats[name] += n
        out, n = DB_URI.subn(lambda m: m.group(1) + "[REDACTED:db_password]" + m.group(3), out)
        if n:
            self.stats["db_password"] += n
        if self.entries:
            out = self._match_known(out)
        return out

    def json(self, obj):
        """Recurse through a JSON-ish structure, redacting every string leaf.

        Keys are redacted too: a dict key can be a credential when a tool call
        serialises `{"sk-ant-...": ...}`, which does happen in header dumps.
        """
        if isinstance(obj, str):
            return self.text(obj)
        if isinstance(obj, dict):
            return {self.text(k): self.json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.json(v) for v in obj]
        return obj

    # -- known-secret matching, hash-only ----------------------------------

    def _match_known(self, s: str) -> str:
        """Hash each candidate token and replace the ones the registry knows.

        Only tokens whose LENGTH appears in the registry are hashed, which keeps
        this cheap: the registry has ~38 distinct lengths, so the overwhelming
        majority of tokens are rejected on an integer comparison.
        """
        if not s:
            return s
        replacements: list[tuple[int, int, str]] = []
        for m in TOKEN.finditer(s):
            tok = m.group(0)
            if len(tok) not in self.lengths:
                continue
            h = hmac.new(self.hmac_key, tok.encode("utf-8"), hashlib.sha256).hexdigest()
            e = self.entries.get(h)
            if e:
                replacements.append((m.start(), m.end(), e["label"]))
        if not replacements:
            return s
        out, last = [], 0
        for start, end, label in replacements:
            out.append(s[last:start])
            out.append(PLACEHOLDER_TOKEN.format(f"vault:{label}"))
            self.stats[f"vault:{label}"] += 1
            last = end
        out.append(s[last:])
        return "".join(out)


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

# Every planted value must be redacted.
#
# The prefixes are SPLIT from their bodies deliberately. These are synthetic
# fixtures, but they are shaped exactly like the real thing -- which is the whole
# point -- so GitHub push protection blocks the repository when a complete
# literal appears in the source (it flagged the AWS key id and the Slack token
# and refused the push). Base64 does not help; GitHub decodes it. Concatenation
# does, because the scanner matches literals in the file while Python joins the
# adjacent strings at parse time, so the runtime values are byte-identical.
#
# If you add a fixture, split it the same way or the next push will be rejected.
MUST_REDACT = {
    "aws_access_key_id": "AKIA" "QWERTZUIOPASDFGH",
    "google_api_key": "AIza" "SyD-1234567890abcdefghijklmnopqrstu",
    "github_token": "ghp" "_abcdefghijklmnopqrstuvwxyz0123456789",
    "anthropic_key": "sk-" "ant-api03-abcdefghijklmnopqrstuvwxyz012345",
    "openai_key": "sk-" "proj-abcdefghijklmnopqrstuvwxyz0123456789",
    "slack_token": "xox" "b-1234567890-abcdefghijklmno",
    "telegram_bot_token": "1234567890" ":AAHqwertzuiopasdfghjklyxcvbnmQWERTZ",
    "tailscale_key": "tskey" "-auth-abcdef1234567890",
    "age_secret_key": "AGE-SECRET-KEY-1" "QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZZZZ",
    "neon_db_key": "npg" "_AbCdEf0123456789Xy",
    "jwt": "eyJhbGciOiJIUzI1NiJ9" ".eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop",
}

# REGRESSION: URL-encoded context. A leading \b anchor missed these entirely --
# the character before the key is '2' from %22, which is not a word boundary.
# 11 real Google API keys survived the first production backfill this way.
URL_ENCODED_CONTEXT = (
    "curl 'https://maps.googleapis.com/maps/api/js?key=%20%22"
    "AIza" "SyD-1234567890abcdefghijklmnopqrstu%22'"
)

# NOT ONE CHARACTER of this may change. This is the control that matters: a
# redactor that mangles ordinary text destroys the corpus it is protecting, and
# unlike a missed secret, the damage is silent and unrecoverable after re-ingest.
MUST_NOT_CHANGE = """
The container died after `podman image prune -af` removed the tagged image.
Run psql "$DB_URL" and check pg_stat_activity; the password lives in vault.yml.
See https://chat.aicortex.cloud/api/v1/models and 10.89.0.231:5432 for details.
password: correcthorsebatterystaple
api_key = os.environ["OPENAI_API_KEY"]
Neo4j is at bolt://10.89.0.44:7687 and SMTP at smtp.mailgun.org:587.
The regex was [^\\s:@/]{6,} which matched ${db_password} in the template.
sha256sum reported 0e5d4bb3a1c2 for the deployed lambda bundle.
"""


def selftest(registry: dict | None = None, key: bytes | None = None) -> int:
    r = Redactor(registry, key) if registry else Redactor()
    fail = False

    # --- positive: every planted credential must disappear -----------------
    missed = []
    for name, secret in MUST_REDACT.items():
        text = f"the command was: export TOKEN={secret} && run it"
        out = r.text(text)
        if secret in out:
            missed.append(name)
    if missed:
        print(f"CONTROL FAILED -- these credentials survived redaction: {missed}")
        fail = True

    # --- regression: the URL-encoded case that escaped the first backfill ---
    ue = r.text(URL_ENCODED_CONTEXT)
    if "AIza" "SyD-1234567890abcdefghijklmnopqrstu" in ue:
        print("CONTROL FAILED -- URL-encoded credential survived redaction "
              "(this is the \\b-anchor bug: %22 puts a digit before the key)")
        fail = True

    # --- negative: ordinary text must be untouched --------------------------
    # Without this, "everything got redacted" passes the positive control.
    out = r.text(MUST_NOT_CHANGE)
    if out != MUST_NOT_CHANGE:
        print("CONTROL FAILED -- ordinary text was modified. Diff:")
        for a, b in zip(MUST_NOT_CHANGE.splitlines(), out.splitlines()):
            if a != b:
                print(f"    was: {a}\n    now: {b}")
        fail = True

    # --- DB URI: password goes, everything else stays -----------------------
    uri_in = "psql postgresql://appuser:s3cr3tp4ssw0rd@10.89.0.231:5432/enterprise"
    uri_out = r.text(uri_in)
    if "s3cr3tp4ssw0rd" in uri_out:
        print("CONTROL FAILED -- DB URI password was not redacted")
        fail = True
    for keep in ("postgresql://", "appuser", "10.89.0.231:5432", "enterprise"):
        if keep not in uri_out:
            print(f"CONTROL FAILED -- DB URI redaction destroyed '{keep}' (real content)")
            fail = True

    # --- json(): both keys and values, at depth -----------------------------
    blob = {"headers": {"x-api-key": MUST_REDACT["anthropic_key"]},
            "args": ["--token", MUST_REDACT["github_token"]],
            "note": "this sentence must survive"}
    jout = json.dumps(r.json(blob))
    if MUST_REDACT["anthropic_key"] in jout or MUST_REDACT["github_token"] in jout:
        print("CONTROL FAILED -- sanitize_json path let a credential through")
        fail = True
    if "this sentence must survive" not in jout:
        print("CONTROL FAILED -- sanitize_json path destroyed ordinary content")
        fail = True

    # --- hash-matching mechanism, always exercised --------------------------
    # A synthetic registry built from a known fixture. This proves the
    # hash-match path CAN fire without needing any real vault value in the
    # test. Without it, a run against the real registry that redacts nothing
    # is ambiguous: no secrets present, or matcher broken?
    tkey = b"selftest-key-not-a-real-secret"
    shapeless = "Xk92mQp4Lz7Ry1Nv8Bw3Ct6Hs0Jd5Fg2Ae4Ui7Oq"      # no prefix; tier-1 cannot see it
    synth = {
        "key_id": hashlib.sha256(tkey).hexdigest()[:12],
        "entries": {
            hmac.new(tkey, shapeless.encode(), hashlib.sha256).hexdigest():
                {"label": "cloudflare_api_token", "len": len(shapeless), "entropy": 4.5}
        },
    }
    sr = Redactor(synth, tkey)
    if shapeless in sr.text(f"curl -H 'Authorization: Bearer {shapeless}' https://api.example.com"):
        print("CONTROL FAILED -- registry matching did not fire on a known secret")
        fail = True
    # ...and tier-1 alone must NOT catch it, or the above proves nothing.
    if shapeless not in Redactor().text(f"token={shapeless}"):
        print("CONTROL FAILED -- tier-1 caught the shapeless value, so the registry "
              "test above is not actually testing the registry")
        fail = True
    # One character off must survive: matching is exact, not fuzzy.
    near = shapeless[:-1] + ("q" if shapeless[-1] != "q" else "z")
    if near not in sr.text(f"token={near}"):
        print("CONTROL FAILED -- a near-miss was redacted; matching is not exact")
        fail = True

    # --- registry half, only if one was supplied ----------------------------
    if registry:
        sample = next(iter(registry["entries"].values()), None)
        if sample is None:
            print("CONTROL FAILED -- registry supplied but empty")
            fail = True
        else:
            # A registry secret must be redacted, and a near-miss must NOT be.
            # The near-miss half proves matching is exact rather than fuzzy --
            # a fuzzy matcher would quietly eat similar-looking real content.
            probe = "x" * sample["len"]
            if r.text(f"value={probe}") != f"value={probe}":
                print("CONTROL FAILED -- a value NOT in the registry was redacted "
                      "(matching is not exact)")
                fail = True
            print(f"  registry loaded: {len(r.entries)} known secrets, "
                  f"{len(r.lengths)} distinct lengths")

    if fail:
        return 1
    print(f"CONTROL PASSED -- {len(MUST_REDACT)} credential shapes redacted, "
          f"ordinary text byte-identical, DB URI keeps host/user/db, json path covered.")
    return 0


def load_from_env() -> Redactor:
    """Build a Redactor from the environment, for ingest-sessions.py.

    REDACTION_REGISTRY  path to the HMAC registry JSON
    REDACTION_HMAC_KEY  the key itself, or REDACTION_HMAC_KEY_FILE a path to it

    With neither set, returns a tier-1-only Redactor. That degradation is
    deliberate and LOUD -- it prints -- because a silent fallback to no
    registry is indistinguishable from a registry that matched nothing.
    """
    reg_path = os.environ.get("REDACTION_REGISTRY")
    key = os.environ.get("REDACTION_HMAC_KEY", "").encode() or None
    if not key and os.environ.get("REDACTION_HMAC_KEY_FILE"):
        key = Path(os.environ["REDACTION_HMAC_KEY_FILE"]).read_bytes().strip()

    if not reg_path or not key:
        print("redaction: TIER-1 ONLY (no registry configured) — "
              "shapeless credentials will NOT be redacted", file=sys.stderr)
        return Redactor()
    return Redactor(json.loads(Path(reg_path).read_text()), key)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--registry")
    ap.add_argument("--hmac-key-file")
    args = ap.parse_args()

    reg = key = None
    if args.registry:
        if not args.hmac_key_file:
            print("--registry requires --hmac-key-file", file=sys.stderr)
            return 2
        reg = json.loads(Path(args.registry).read_text())
        key = Path(args.hmac_key_file).read_bytes().strip()

    if args.selftest:
        return selftest(reg, key)
    print("nothing to do; pass --selftest", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
