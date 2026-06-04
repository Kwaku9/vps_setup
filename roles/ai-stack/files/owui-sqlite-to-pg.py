#!/usr/bin/env python3
"""Data-only copy: OWUI SQLite -> Postgres `openwebui` schema.

Both sides are OWUI 0.9.6 (Postgres schema built by OWUI's own Alembic at boot).
SQLite is read via the raw DBAPI (no SQLAlchemy type coercion — OWUI stores epoch
ints in some DATETIME-declared legacy columns, which breaks SQLAlchemy's reader).
Values are adapted to the Postgres column types on insert (JSON, bool, datetime),
then sequences are reset.

Env:
  SQLITE_PATH   path to webui.db
  PG_URL        postgresql://...@shared-db-pod:5432/enterprise?options=-csearch_path%3Dopenwebui,public
"""
import datetime
import json
import os
import sqlite3

from sqlalchemy import Boolean, DateTime, MetaData, create_engine, insert, text
from sqlalchemy.dialects.postgresql import JSON, JSONB

SKIP = {"alembic_version", "migratehistory"}
# Insert one row at a time: some single chats embed ~80MB of base64 image data,
# so even small multi-row batches can spike the backend past its memory cap.
CHUNK = 1

raw = sqlite3.connect(os.environ["SQLITE_PATH"])
dst = create_engine(os.environ["PG_URL"])

dst_md = MetaData(schema="openwebui")
dst_md.reflect(bind=dst, schema="openwebui")
ordered = [t for t in dst_md.sorted_tables if t.name not in SKIP]

sqlite_tables = {
    r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")
}


def adapt(table, row):
    out = {}
    for col in table.columns:
        if col.name not in row:
            continue
        v = row[col.name]
        if v is not None:
            if isinstance(col.type, (JSON, JSONB)) and isinstance(v, str):
                try:
                    v = json.loads(v) if v != "" else None
                except (ValueError, TypeError):
                    v = None
            elif isinstance(col.type, Boolean) and isinstance(v, int):
                v = bool(v)
            elif isinstance(col.type, DateTime):
                if isinstance(v, (int, float)):
                    v = datetime.datetime.fromtimestamp(v, tz=datetime.timezone.utc)
                elif isinstance(v, str):
                    try:
                        v = datetime.datetime.fromisoformat(v)
                    except ValueError:
                        pass
        out[col.name] = v
    return out


total = 0
with dst.begin() as dconn:
    dconn.execute(text("SET session_replication_role = replica"))
    for table in reversed(ordered):
        dconn.execute(text('TRUNCATE openwebui."%s" CASCADE' % table.name))
    for table in ordered:
        if table.name not in sqlite_tables:
            print("skip(absent): %s" % table.name)
            continue
        cur = raw.execute('SELECT * FROM "%s"' % table.name)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for i in range(0, len(rows), CHUNK):
            batch = rows[i:i + CHUNK]
            dconn.execute(insert(table), [adapt(table, r) for r in batch])
        print("%s: %d" % (table.name, len(rows)))
        total += len(rows)
    dconn.execute(text("SET session_replication_role = DEFAULT"))

# Reset sequences so future inserts don't collide with copied integer PKs.
with dst.begin() as dconn:
    for table in ordered:
        for col in table.columns:
            seq = dconn.execute(
                text("SELECT pg_get_serial_sequence(:t, :c)").bindparams(
                    t='openwebui."%s"' % table.name, c=col.name
                )
            ).scalar()
            if seq:
                dconn.execute(
                    text(
                        'SELECT setval(:s, COALESCE((SELECT MAX("%s") FROM openwebui."%s"), 1))'
                        % (col.name, table.name)
                    ).bindparams(s=seq)
                )

print("TOTAL ROWS COPIED: %d" % total)
