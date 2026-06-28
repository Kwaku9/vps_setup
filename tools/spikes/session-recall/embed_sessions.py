import argparse
import time

from db import connect, vec_literal
import datasets
from text_prep import chunk_text
from embedders import gemma, nomic

GEMMA_TABLES = {"useronly": "spike.emb_gemma_useronly", "userasst": "spike.emb_gemma_userasst"}
NOMIC_TABLES = {"useronly": "spike.emb_nomic_useronly", "userasst": "spike.emb_nomic_userasst"}


def embed_gemma(conn_read, conn_write, dataset, limit, batch_size=32, chunk_chars=3500, table=None):
    # NOTE: a server-side (named) read cursor is invalidated by COMMIT, so reads and
    # writes use SEPARATE connections. conn_read streams; conn_write inserts + commits.
    table = table or GEMMA_TABLES[dataset]
    w = conn_write.cursor()
    w.execute(f"SELECT DISTINCT message_id FROM {table}")
    done = {r[0] for r in w.fetchall()}

    pending = []  # (message_id, chunk_idx, session_uuid, project, ts, snippet, raw_chunk)
    n = 0
    t0 = time.time()

    def flush():
        nonlocal pending
        if not pending:
            return
        vecs = gemma.embed_docs([p[6] for p in pending])
        for p, v in zip(pending, vecs):
            w.execute(
                f"INSERT INTO {table}"
                f"(message_id, chunk_idx, session_uuid, project, ts, snippet, embedding) "
                f"VALUES (%s,%s,%s,%s,%s,%s,%s::vector) ON CONFLICT DO NOTHING",
                (p[0], p[1], p[2], p[3], p[4], p[5], vec_literal(v)),
            )
        conn_write.commit()
        pending = []

    for d in datasets.iter_gemma_docs(conn_read, dataset, limit):
        if d["message_id"] in done:
            continue
        for ci, chunk in enumerate(chunk_text(d["content_text"], chunk_chars)):
            pending.append((d["message_id"], ci, d["session_uuid"], d["project"],
                            d["ts"], chunk[:500], chunk))
            if len(pending) >= batch_size:
                flush()
        n += 1
        if n % 200 == 0:
            print(f"  gemma/{dataset}: {n} messages, {time.time()-t0:.0f}s")
    flush()
    print(f"  gemma/{dataset}: done {n} new messages in {time.time()-t0:.0f}s")


def embed_nomic(conn_read, conn_write, dataset, limit, batch_size=8):
    table = NOMIC_TABLES[dataset]
    w = conn_write.cursor()
    w.execute(f"SELECT session_uuid FROM {table}")
    done = {r[0] for r in w.fetchall()}

    pending = []
    n = 0
    t0 = time.time()

    def flush():
        nonlocal pending
        if not pending:
            return
        vecs = nomic.embed_docs([p["transcript"] for p in pending])
        for p, v in zip(pending, vecs):
            w.execute(
                f"INSERT INTO {table}"
                f"(session_uuid, project, started_at, title, embedding) "
                f"VALUES (%s,%s,%s,%s,%s::vector) ON CONFLICT DO NOTHING",
                (p["session_uuid"], p["project"], p["started_at"], p["title"], vec_literal(v)),
            )
        conn_write.commit()
        pending = []

    for d in datasets.iter_nomic_docs(conn_read, dataset, limit):
        if d["session_uuid"] in done:
            continue
        pending.append(d)
        if len(pending) >= batch_size:
            flush()
        n += 1
        if n % 50 == 0:
            print(f"  nomic/{dataset}: {n} sessions, {time.time()-t0:.0f}s")
    flush()
    print(f"  nomic/{dataset}: done {n} new sessions in {time.time()-t0:.0f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["gemma", "nomic"], required=True)
    ap.add_argument("--dataset", choices=["useronly", "userasst"], required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--chunk-chars", type=int, default=3500)
    ap.add_argument("--gemma-table", default=None,
                    help="override the gemma target table (for chunk-size variants)")
    args = ap.parse_args()

    conn_read = connect()
    conn_write = connect()
    if args.model == "gemma":
        embed_gemma(conn_read, conn_write, args.dataset, args.limit,
                    chunk_chars=args.chunk_chars, table=args.gemma_table)
    else:
        embed_nomic(conn_read, conn_write, args.dataset, args.limit)
    conn_read.close()
    conn_write.close()


if __name__ == "__main__":
    main()
