#!/usr/bin/env python3
"""Redact credentials already written into Postgres.

Ingestion redacts everything from now on; this cleans what is already there.
Runs ON the VPS host (which has psycopg2, same as ingest-sessions.py) and
imports the deployed redact.py so the backfill and the live path can never
disagree about what a credential is.

COLUMNS (the same four ingest writes, plus the served snippet):
    sessions.messages.content_text / content_json
    sessions.tool_calls.input_json / result_text
    sessions.artifacts.content_full / content_preview
    recall.chunks.snippet          <- what semantic search actually RETURNS

recall.chunks NOTE: redacting a snippet does NOT recompute its embedding. The
vector still derives from the unredacted text. That is acceptable because a
vector does not expose the literal string, and the snippet is what gets shown;
re-embedding those chunks is optional cleanup, not a leak fix.

SAFETY - the asymmetric error here is OVER-redaction. A missed credential is
bad; corrupting prose across 500k rows is unrecoverable after the fact (the
JSONL archive can rebuild it, but only by a full re-ingest). So:

  * --dry-run is the default. Nothing is written without --apply.
  * If more than MAX_CHANGE_RATIO of rows in a table would change, ABORT. A
    registry value that collides with ordinary text would show up exactly this
    way, and refusing beats discovering it later.
  * Verification MEASURES THE TABLE afterwards, not the client's rowcount --
    psycopg2's cur.rowcount reflects only the last page of execute_values.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys

import psycopg2
from psycopg2.extras import Json

DEPLOY_DIR = "/opt/compose/session-ingestion"

# Same shapes redact.py handles, used only to COUNT before/after. Counting with
# an independent expression means the verification is not just asking the
# redactor whether it thinks it worked.
CRED_RE = (
    r"(AKIA[0-9A-Z]{16}|sk-ant-[A-Za-z0-9_-]{20}|AIza[0-9A-Za-z_-]{35}"
    r"|ghp_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]{10}|sk-[A-Za-z0-9]{32}"
    r"|npg_[A-Za-z0-9]{16}|AGE-SECRET-KEY-1[A-Z0-9]{50})"
)

MAX_CHANGE_RATIO = 0.10       # >10% of a table changing means something is wrong
BATCH = 500

# (table, primary-key columns, text columns, json columns)
# recall.chunks has a COMPOSITE key (message_id, chunk_idx), so the key is a list
# everywhere rather than a special case.
TARGETS = [
    ("sessions.messages",   ["id"], ["content_text"],                   []),
    ("sessions.messages",   ["id"], [],                                 ["content_json"]),
    ("sessions.tool_calls", ["id"], ["result_text"],                    []),
    ("sessions.tool_calls", ["id"], [],                                 ["input_json"]),
    ("sessions.artifacts",  ["id"], ["content_full", "content_preview"], []),
    ("recall.chunks", ["message_id", "chunk_idx"], ["snippet"],         []),
]


def load_redactor():
    spec = importlib.util.spec_from_file_location("redact", f"{DEPLOY_DIR}/redact.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    r = m.load_from_env()
    if not r.entries:
        print("WARNING: no registry loaded - tier-1 patterns only", file=sys.stderr)
    return r


def count_matching(cur, table, cols, jcols):
    exprs = [f"{c} ~ %s" for c in cols] + [f"{c}::text ~ %s" for c in jcols]
    if not exprs:
        return 0
    cur.execute(f"SELECT count(*) FROM {table} WHERE " + " OR ".join(exprs),
                [CRED_RE] * len(exprs))
    return cur.fetchone()[0]


def process(conn, red, table, pk, cols, jcols, apply_changes):
    cur = conn.cursor()
    total = count_matching(cur, table, cols, jcols)
    cur.execute(f"SELECT count(*) FROM {table}")
    tablerows = cur.fetchone()[0]
    label = f"{table}[{','.join(cols + jcols)}]"
    print(f"\n{label}")
    print(f"  rows in table                 : {tablerows:,}")
    print(f"  rows matching credential shape: {total:,}")
    if total == 0:
        cur.close()
        return 0

    if tablerows and total / tablerows > MAX_CHANGE_RATIO:
        print(f"  ABORT: {total/tablerows:.1%} of rows match - above the "
              f"{MAX_CHANGE_RATIO:.0%} ceiling. Refusing; investigate the pattern first.")
        cur.close()
        return -1

    sel = ", ".join(pk + cols + jcols)
    exprs = [f"{c} ~ %s" for c in cols] + [f"{c}::text ~ %s" for c in jcols]
    # A plain client-side cursor, deliberately. A server-side (named) cursor is
    # INVALIDATED by the conn.commit() inside flush() -- "named cursor isn't valid
    # anymore" -- and the matched sets here are small (tens to low hundreds of
    # rows), so streaming buys nothing and costs correctness.
    read = conn.cursor()
    read.execute(f"SELECT {sel} FROM {table} WHERE " + " OR ".join(exprs),
                 [CRED_RE] * len(exprs))
    rows = read.fetchall()
    read.close()

    changed = 0
    pending = []
    for row in rows:
        rid, vals = row[:len(pk)], row[len(pk):]
        newvals, dirty = [], False
        for i, c in enumerate(cols):
            v = vals[i]
            nv = red.text(v) if isinstance(v, str) else v
            dirty |= (nv != v)
            newvals.append(nv)
        for j, c in enumerate(jcols):
            v = vals[len(cols) + j]
            nv = red.json(v) if v is not None else v
            dirty |= (nv != v)
            newvals.append(nv)
        if dirty:
            pending.append((rid, newvals))
            changed += 1
        if apply_changes and len(pending) >= BATCH:
            flush(conn, table, pk, cols, jcols, pending)
            pending.clear()
    if apply_changes and pending:
        flush(conn, table, pk, cols, jcols, pending)

    print(f"  rows that WOULD change        : {changed:,}" if not apply_changes
          else f"  rows updated                  : {changed:,}")
    cur.close()
    return changed


def flush(conn, table, pk, cols, jcols, pending):
    cur = conn.cursor()
    sets = ", ".join([f"{c} = %s" for c in cols + jcols])
    where = " AND ".join([f"{k} = %s" for k in pk])
    for rid, vals in pending:
        params = []
        for i, _ in enumerate(cols):
            params.append(vals[i])
        for j, _ in enumerate(jcols):
            v = vals[len(cols) + j]
            params.append(Json(v) if v is not None else None)
        cur.execute(f"UPDATE {table} SET {sets} WHERE {where}", params + list(rid))
    conn.commit()
    cur.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default is dry-run)")
    args = ap.parse_args()

    red = load_redactor()
    print(f"redactor: {len(red.entries)} known secrets, "
          f"{len(red.lengths)} distinct lengths\n")

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"), port=5432, dbname="enterprise",
        user=os.environ.get("DB_USER", "postgres"), password=os.environ["DB_PASSWORD"])

    mode = "APPLY" if args.apply else "DRY RUN (no writes)"
    print(f"=== {mode} ===")

    before = {}
    cur = conn.cursor()
    for table, pk, cols, jcols in TARGETS:
        before[(table, tuple(cols + jcols))] = count_matching(cur, table, cols, jcols)
    cur.close()

    total_changed = 0
    for table, pk, cols, jcols in TARGETS:
        n = process(conn, red, table, pk, cols, jcols, args.apply)
        if n < 0:
            print("\nAborted - no further tables processed.")
            return 1
        total_changed += n

    if args.apply:
        # MEASURE THE TABLE, not the client. cur.rowcount lies across batches.
        print("\n=== verification: re-count credential shapes in the TABLE ===")
        cur = conn.cursor()
        remaining = 0
        for table, pk, cols, jcols in TARGETS:
            after = count_matching(cur, table, cols, jcols)
            b = before[(table, tuple(cols + jcols))]
            remaining += after
            print(f"  {table:22} {','.join(cols+jcols):28} {b:6,} -> {after:6,}")
        cur.close()
        print(f"\n  credential-shaped rows remaining: {remaining:,}")
        print("  (non-zero is not automatically wrong: placeholders and example keys"
              "\n   in prose match the shape but are not secrets)")
    else:
        print(f"\nTotal rows that would change: {total_changed:,}")
        print("Re-run with --apply to write.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
