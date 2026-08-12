#!/usr/bin/env python3
"""Load captured student searches from the nginx log into SQLite.

    python3 ingest_queries.py [--log PATH] [--db PATH]

Design: the LOG stays the source of truth, SQLite is a derived, queryable view.
That ordering matters. nginx writing a line is the only thing in the request
path while a student is typing — no app server, no database connection, nothing
that can fail mid-keystroke. If this script breaks, capture keeps working and
the next run catches up.

Idempotent: re-running over the whole log inserts nothing new, because each row
is keyed by a hash of (timestamp, term, question, program, course). Safe to run
on a timer, safe to run twice, safe to run after logrotate.

Privacy: the log has no IP by construction (see nginx.conf.j2 log_format), and
name/school never leave the browser at all. Programme/course are a cohort the
student opted into. Nothing here can re-identify anyone, and nothing should be
added that could.
"""
import argparse
import hashlib
import pathlib
import sqlite3
import sys
import urllib.parse

DDL = """
CREATE TABLE IF NOT EXISTS queries (
    id         TEXT PRIMARY KEY,      -- sha1 of the raw line; makes re-runs no-ops
    ts         TEXT NOT NULL,         -- ISO8601 from nginx
    kind       TEXT NOT NULL,         -- 'term'|'question'|'miss'|'miss_approx'
    text       TEXT NOT NULL,         -- what the student actually typed
    program    TEXT,                  -- cohort, opted in
    course     TEXT
);
CREATE INDEX IF NOT EXISTS ix_queries_ts      ON queries(ts);
CREATE INDEX IF NOT EXISTS ix_queries_kind    ON queries(kind);
CREATE INDEX IF NOT EXISTS ix_queries_program ON queries(program);
"""


def dec(v):
    v = (v or "").strip()
    if v in ("", "-"):
        return None
    return urllib.parse.unquote_plus(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="/opt/compose/dsm5-logs/queries.log")
    ap.add_argument("--db", default="/opt/compose/dsm5-logs/queries.sqlite")
    ap.add_argument("--retain-days", type=int, default=0,
                    help="drop rows older than N days; 0 keeps everything")
    a = ap.parse_args()

    log = pathlib.Path(a.log)
    if not log.exists():
        sys.exit(f"no log at {log}")

    db = sqlite3.connect(a.db)
    db.executescript(DDL)

    seen = added = skipped = 0
    rows = []
    for raw in log.read_text(errors="replace").splitlines():
        if not raw.strip():
            continue
        seen += 1
        parts = raw.split("\t")
        # Older lines have fewer columns (the format grew from 2 -> 5 -> 6 as
        # question capture, cohort, and the miss flag were added). Pad rather
        # than drop them: the early rows are still real student searches, and
        # the fields only ever get APPENDED so the positions stay stable.
        parts += [""] * (6 - len(parts))
        ts, term, question, program, course, miss = parts[:6]
        term, question = dec(term), dec(question)
        if question:
            kind, text = "question", question
        elif term:
            # A miss is still a term search — it is recorded as its own kind
            # because it is the only row type that describes something the app
            # could not do, which makes it the queue for the alias layer.
            # 1 = the index had nothing. 2 = only the word-level fallback
            # answered, so the student WAS served but their phrasing still
            # missed. Both are phrasing failures and both belong in the queue;
            # separating them says whether the fallback is earning its keep.
            m = (miss or "").strip()
            kind = {"1": "miss", "2": "miss_approx"}.get(m, "term")
            text = term
        else:
            skipped += 1
            continue
        rows.append((
            hashlib.sha1(raw.encode()).hexdigest(),
            ts.strip(), kind, text, dec(program), dec(course),
        ))

    cur = db.executemany(
        "INSERT OR IGNORE INTO queries (id, ts, kind, text, program, course) "
        "VALUES (?,?,?,?,?,?)", rows)
    db.commit()
    added = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    # Retention. Default 0 = keep everything, deliberately: these anonymous
    # queries are the evaluation corpus, so expiring them deletes the thing the
    # capture exists to produce. Set --retain-days only as a conscious choice.
    pruned = 0
    if a.retain_days and a.retain_days > 0:
        cur = db.execute(
            "DELETE FROM queries WHERE ts < datetime('now', ?)",
            (f"-{a.retain_days} days",))
        pruned = cur.rowcount or 0
        db.commit()
        if pruned:
            db.execute("VACUUM")

    total = db.execute("SELECT count(*) FROM queries").fetchone()[0]
    print(f"  log lines read : {seen} (skipped {skipped} empty)")
    print(f"  rows now in db : {total}  (+{added} this run"
          + (f", -{pruned} pruned)" if pruned else ")"))
    print(f"  db             : {a.db}")
    print()
    for kind, n in db.execute("SELECT kind, count(*) FROM queries GROUP BY kind"):
        print(f"    {kind:9} {n}")
    print()
    for label, k in (("top misses (nothing in the index at all)", "miss"),
                     ("rescued by word matching (phrasing still missed)", "miss_approx")):
        print(f"  {label}:")
        rows = db.execute(
            "SELECT text, count(*) n FROM queries WHERE kind=? "
            "GROUP BY lower(text) ORDER BY n DESC, text LIMIT 10", (k,)
        ).fetchall()
        if not rows:
            print("    (none yet)")
        for text, n in rows:
            print(f"    {text[:46]:46} {n}")
        print()
    print()
    print("  by cohort:")
    for prog, n in db.execute(
        "SELECT coalesce(program,'(not given)'), count(*) FROM queries "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 8"
    ):
        print(f"    {prog:28} {n}")
    db.close()


if __name__ == "__main__":
    main()
