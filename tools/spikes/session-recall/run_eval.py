import argparse
import time

from db import connect
from search import rank, METHODS, session_titles
from metrics import recall_at_k, precision_at_k, reciprocal_rank

KS = [1, 3, 5]
COLS = ["R@1", "R@3", "R@5", "P@1", "P@3", "P@5", "MRR", "ms"]


def load_gold(conn, source=None):
    cur = conn.cursor()
    if source:
        cur.execute("SELECT id, query, gold_session_uuid, COALESCE(source,'?') "
                    "FROM spike.eval_queries WHERE source = %s", (source,))
    else:
        cur.execute("SELECT id, query, gold_session_uuid, COALESCE(source,'?') "
                    "FROM spike.eval_queries")
    return cur.fetchall()


def score(conn, queries):
    agg = {m: {c: 0.0 for c in COLS} for m in METHODS}
    for _qid, query, gold_uuid, _src in queries:
        for m in METHODS:
            t0 = time.time()
            ranked = rank(conn, query, m[0], m[1], k=10)
            agg[m]["ms"] += (time.time() - t0) * 1000.0
            for k in KS:
                agg[m][f"R@{k}"] += recall_at_k(ranked, gold_uuid, k)
                agg[m][f"P@{k}"] += precision_at_k(ranked, gold_uuid, k)
            agg[m]["MRR"] += reciprocal_rank(ranked, gold_uuid)
    return agg


def print_board(title, agg, n):
    print(f"\n=== {title} — {n} queries ===")
    header = f"{'method':22} " + " ".join(f"{c:>6}" for c in COLS)
    print(header)
    print("-" * len(header))
    for m in sorted(METHODS, key=lambda mm: agg[mm]["R@3"], reverse=True):
        vals = [agg[m][c] / n for c in COLS]
        print(f"{m[0] + '/' + m[1]:22} " + " ".join(f"{v:6.2f}" for v in vals))


def capture_feedback(conn, queries):
    for qid, query, _gold, _src in queries:
        print(f"\n? feedback for: {query!r}")
        for model, dataset in METHODS:
            ranked = rank(conn, query, model, dataset, k=5)
            titles = session_titles(conn, ranked)
            print(f"  [{model}/{dataset}]")
            for i, u in enumerate(ranked, 1):
                print(f"    {i}. {titles.get(u, u)}  ({u[:8]})")
            raw = input("    relevant result #s (comma-sep, blank=none) > ").strip()
            good = {int(x) for x in raw.split(",") if x.strip().isdigit()}
            cur = conn.cursor()
            for i, u in enumerate(ranked, 1):
                cur.execute(
                    "INSERT INTO spike.eval_relevance (query_id, method, session_uuid, is_relevant) "
                    "VALUES (%s, %s, %s, %s)",
                    (qid, f"{model}/{dataset}", u, i in good))
            conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None,
                    help="restrict to one source, e.g. manual or synthetic-approved")
    ap.add_argument("--feedback", action="store_true")
    args = ap.parse_args()

    conn = connect()
    rows = load_gold(conn, args.source)
    if not rows:
        print("No gold queries — run gen_queries.py or add_query.py first.")
        return

    by_source = {}
    for r in rows:
        by_source.setdefault(r[3], []).append(r)

    # One scoreboard per source (manual scored separately from synthetic), plus combined.
    for src in sorted(by_source):
        group = by_source[src]
        print_board(f"source={src}", score(conn, group), len(group))
    if len(by_source) > 1:
        print_board("ALL sources", score(conn, rows), len(rows))

    if args.feedback:
        capture_feedback(conn, rows)


if __name__ == "__main__":
    main()
