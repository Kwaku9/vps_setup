# embed_summaries.py — Stage 2: embed summary_text with nomic + gemma into pgvector tables
import argparse, requests
import db, config

def embed_nomic(text):
    r = requests.post(f"{config.NOMIC_BASE}/embeddings",
                      json={"input": text, "model": "nomic-embed"}, timeout=120)
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]

def embed_gemma(text):
    r = requests.post(f"{config.LITELLM_BASE}/embeddings",
                      headers={"Authorization": "Bearer " + config.LITELLM_KEY},
                      json={"input": text, "model": config.GEMMA_MODEL}, timeout=120)
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]

EMBEDDERS = {"nomic": (embed_nomic, "spike.session_summary_vec_nomic"),
             "gemma": (embed_gemma, "spike.session_summary_vec_gemma")}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    conn = db.connect(); cur = conn.cursor()
    for name, (fn, table) in EMBEDDERS.items():
        join = "TRUE" if a.force else "v.session_uuid IS NULL"
        sql = f"""SELECT ss.session_uuid, ss.summary_text FROM spike.session_summary ss
                  LEFT JOIN {table} v ON v.session_uuid=ss.session_uuid
                  WHERE ss.summary_text IS NOT NULL AND ss.model='claude-haiku-4-5' AND {join}"""
        if a.limit:
            sql += f" LIMIT {int(a.limit)}"
        cur.execute(sql); rows = cur.fetchall()
        print(f"{name}: {len(rows)} to embed")
        n = 0
        for uuid, text in rows:
            try:
                vec = fn(text)
            except Exception as e:
                print("  ERR embed", name, uuid, repr(e)[:100]); continue
            try:
                cur.execute(f"""INSERT INTO {table} (session_uuid, embedding, embedded_at)
                                VALUES (%s, %s, now())
                                ON CONFLICT (session_uuid) DO UPDATE
                                  SET embedding=EXCLUDED.embedding, embedded_at=now()""",
                            (uuid, db.vec_literal(vec)))
            except Exception as e:
                print("  ERR insert", name, uuid, repr(e)[:100]); conn.rollback(); continue
            n += 1
            if n % 100 == 0:
                conn.commit(); print(f"  {name} ...{n}")
        conn.commit(); print(f"{name}: embedded {n}")

if __name__ == "__main__":
    main()
