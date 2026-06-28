"""RAG answer-quality board: for each (query, method): retrieve -> synthesize an answer from the
retrieved sessions -> LLM-judge the answer 1-5. Reports avg quality + retrieval latency per method.
This is the right metric for the user's cross-session synthesis questions (single-session hit-rate
doesn't fit). Synthesis + judging go through LiteLLM (cloud models)."""
import argparse
import time
import statistics as st
import requests

from db import connect
import search
from config import LITELLM_BASE, LITELLM_KEY, GEN_MODEL

SYNTH_MODEL = GEN_MODEL                # answer writer (cheap/fast)
JUDGE_MODEL = "claude-sonnet-4-6"      # grader (stronger)


def _chat(model, system, user, max_tokens=700, temperature=0.2):
    r = requests.post(
        f"{LITELLM_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {LITELLM_KEY}"},
        json={"model": model,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}],
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def context_for(conn, uuids, per_chars=1500, max_sessions=5):
    cur = conn.cursor()
    blocks = []
    for u in uuids[:max_sessions]:
        cur.execute(
            "SELECT COALESCE(s.title,''), to_char(s.started_at,'YYYY-MM-DD'), "
            "string_agg(m.content_text, ' ' ORDER BY m.sequence_num) "
            "FROM sessions.sessions s JOIN sessions.messages m ON m.session_id=s.id "
            "WHERE s.session_uuid=%s AND m.type IN ('user','assistant') AND m.content_text IS NOT NULL "
            "GROUP BY s.title, s.started_at", (u,))
        row = cur.fetchone()
        if not row:
            continue
        title, date, content = row
        blocks.append(f"[Session {date} — {title}]\n{(content or '')[:per_chars]}")
    return "\n\n".join(blocks)


def synthesize(conn, query, uuids):
    ctx = context_for(conn, uuids)
    if not ctx:
        return "(no context retrieved)"
    sys = ("You answer questions about the user's past coding sessions using ONLY the provided "
           "session excerpts. Be concise and specific. If the excerpts don't contain the answer, say so.")
    return _chat(SYNTH_MODEL, sys, f"Question: {query}\n\nRetrieved session excerpts:\n{ctx}\n\nAnswer:")


def judge(query, answer):
    sys = ("You grade an answer to a question about someone's past coding sessions. "
           "Score 1-5 (5=specific, useful, grounded; 1=empty/useless/wrong). Reply with ONLY the integer.")
    out = _chat(JUDGE_MODEL, sys, f"Question: {query}\n\nAnswer: {answer}\n\nScore (1-5):", max_tokens=4)
    for ch in out:
        if ch in "12345":
            return int(ch)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="userasst")
    ap.add_argument("--methods", default="gemma,gemma512,nomic,keyword,hybrid,graphrag")
    args = ap.parse_args()
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT query FROM spike.eval_queries WHERE source='manual' ORDER BY id")
    queries = [r[0] for r in cur.fetchall()]
    methods = [m.strip() for m in args.methods.split(",")]
    agg = {m: {"score": [], "ms": []} for m in methods}

    for qi, q in enumerate(queries, 1):
        for m in methods:
            t = time.time()
            uuids = search.rank(conn, q, m, args.dataset, 8)
            ms = (time.time() - t) * 1000
            ans = synthesize(conn, q, uuids)
            sc = judge(q, ans)
            agg[m]["score"].append(sc)
            agg[m]["ms"].append(ms)
        print(f"  scored query {qi}/{len(queries)}")

    print(f"\n=== RAG answer-quality board (dataset={args.dataset}, {len(queries)} queries) ===")
    print(f"{'method':12} {'avg_quality':>11} {'retr_ms':>8}")
    print("-" * 33)
    for m in sorted(methods, key=lambda mm: st.mean(agg[mm]['score']), reverse=True):
        print(f"{m:12} {st.mean(agg[m]['score']):11.2f} {st.mean(agg[m]['ms']):8.0f}")


if __name__ == "__main__":
    main()
