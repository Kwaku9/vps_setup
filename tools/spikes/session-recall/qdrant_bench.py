"""Speed/scale benchmark: pgvector vs Qdrant on the same gemma vectors.
Quality ties (identical embeddings); this measures latency, index size, build time, recall-overlap."""
import time
import statistics as st
import requests

from db import connect
from embedders import gemma

QDRANT = "http://qdrant-spike:6333"
COLL = "gemma_userasst"
TABLE = "spike.emb_gemma_userasst"


def ensure_loaded(conn):
    requests.get(f"{QDRANT}/collections/{COLL}")  # touch
    cnt = 0
    r = requests.post(f"{QDRANT}/collections/{COLL}/points/count", json={"exact": True})
    if r.status_code == 200:
        cnt = r.json()["result"]["count"]
    if cnt > 0:
        print(f"Qdrant already has {cnt} points")
        return
    requests.put(f"{QDRANT}/collections/{COLL}",
                 json={"vectors": {"size": 768, "distance": "Cosine"}})
    cur = conn.cursor(name="qload")
    cur.itersize = 2000
    cur.execute(f"SELECT session_uuid, embedding::text FROM {TABLE}")
    batch, pid, n, t0 = [], 0, 0, time.time()
    for uuid, emb in cur:
        vec = [float(x) for x in emb.strip("[]").split(",")]
        pid += 1
        batch.append({"id": pid, "vector": vec, "payload": {"s": uuid}})
        if len(batch) >= 1000:
            requests.put(f"{QDRANT}/collections/{COLL}/points?wait=true", json={"points": batch})
            n += len(batch); batch = []
    if batch:
        requests.put(f"{QDRANT}/collections/{COLL}/points?wait=true", json={"points": batch}); n += len(batch)
    cur.close()
    print(f"loaded {n} vectors into Qdrant in {time.time()-t0:.1f}s")


def main():
    conn = connect()
    cur = conn.cursor()
    # pgvector HNSW index (build time)
    cur.execute(f"SELECT to_regclass('spike.idx_gua_hnsw')")
    if cur.fetchone()[0] is None:
        t0 = time.time()
        cur.execute(f"CREATE INDEX idx_gua_hnsw ON {TABLE} USING hnsw (embedding vector_cosine_ops)")
        conn.commit()
        print(f"pgvector HNSW build: {time.time()-t0:.1f}s")
    ensure_loaded(conn)

    cur.execute("SELECT query FROM spike.eval_queries WHERE source='manual'")
    queries = [r[0] for r in cur.fetchall()]
    pg, qd, overlap = [], [], []
    for q in queries:
        qv = gemma.embed_query(q)
        lit = "[" + ",".join(f"{x:.6f}" for x in qv) + "]"
        t = time.time()
        cur.execute(f"SELECT session_uuid FROM {TABLE} ORDER BY embedding <=> %s::vector LIMIT 10", (lit,))
        a = [r[0] for r in cur.fetchall()]; pg.append((time.time()-t)*1000)
        t = time.time()
        r = requests.post(f"{QDRANT}/collections/{COLL}/points/search",
                          json={"vector": qv, "limit": 10, "with_payload": True})
        b = [p["payload"]["s"] for p in r.json()["result"]]; qd.append((time.time()-t)*1000)
        overlap.append(len(set(a) & set(b)) / max(1, len(set(a))))

    # sizes
    cur.execute(f"SELECT pg_size_pretty(pg_relation_size('spike.idx_gua_hnsw'))")
    pg_idx = cur.fetchone()[0]
    info = requests.get(f"{QDRANT}/collections/{COLL}").json()["result"]
    print("\n=== speed/scale: pgvector vs Qdrant (gemma_userasst, 46k vectors) ===")
    print(f"pgvector(HNSW)  query  p50={st.median(pg):.1f}ms  mean={st.mean(pg):.1f}ms  idx_size={pg_idx}")
    print(f"qdrant(HNSW)    query  p50={st.median(qd):.1f}ms  mean={st.mean(qd):.1f}ms  points={info.get('points_count')}")
    print(f"top-10 session overlap (pgvector vs qdrant): {st.mean(overlap):.2f}")


if __name__ == "__main__":
    main()
