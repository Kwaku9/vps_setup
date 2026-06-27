import argparse
import requests

from db import connect
from config import LITELLM_BASE, LITELLM_KEY, GEN_MODEL
from sampling import stratified_sample

SYS_PROMPT = (
    "You write ONE short, natural search query (max 12 words) that a developer would "
    "type later to find this past coding session. Output only the query — no quotes, "
    "no preamble."
)


def candidate_sessions(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT s.session_uuid, COALESCE(p.display_name, p.project_path) AS project,
               s.started_at, s.title
        FROM sessions.sessions s
        JOIN sessions.projects p ON p.id = s.project_id
    """)
    return [{"session_uuid": r[0], "project": r[1], "started_at": r[2], "title": r[3]}
            for r in cur.fetchall()]


def already_labeled(conn):
    cur = conn.cursor()
    cur.execute("SELECT gold_session_uuid FROM spike.eval_queries")
    return {r[0] for r in cur.fetchall()}


def snippet_for(conn, session_uuid):
    # Send only a small snippet to the (cloud-proxied) gen model: title + first user turns.
    cur = conn.cursor()
    cur.execute("""
        SELECT m.content_text
        FROM sessions.messages m
        JOIN sessions.sessions s ON s.id = m.session_id
        WHERE s.session_uuid = %s AND m.type = 'user'
          AND m.content_text IS NOT NULL
        ORDER BY m.sequence_num
        LIMIT 3
    """, (session_uuid,))
    parts = [r[0][:600] for r in cur.fetchall()]
    return "\n".join(parts)[:1200]


def gen_query(snippet, title):
    user = f"Session title: {title}\nWhat the user worked on:\n{snippet}"
    resp = requests.post(
        f"{LITELLM_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {LITELLM_KEY}"},
        json={
            "model": GEN_MODEL,
            "messages": [{"role": "system", "content": SYS_PROMPT},
                         {"role": "user", "content": user}],
            "temperature": 0.3,
            "max_tokens": 40,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=25)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    conn = connect()
    labeled = already_labeled(conn)
    pool = [s for s in candidate_sessions(conn) if s["session_uuid"] not in labeled]
    batch = stratified_sample(pool, args.batch_size, seed=args.seed)
    ins = conn.cursor()
    saved = 0

    for s in batch:
        snip = snippet_for(conn, s["session_uuid"])
        if not snip:
            continue
        q = gen_query(snip, s["title"] or "")
        started = s["started_at"].strftime("%Y-%m-%d") if s["started_at"] else "?"
        print(f"\n--- {s['project']} | {s['title']} | {started}")
        print(f"draft: {q}")
        ans = input("[a]ccept / [e]dit / [r]eject / [q]uit > ").strip().lower()
        if ans == "q":
            break
        if ans == "r":
            continue
        if ans == "e":
            q = input("new query: ").strip()
            if not q:
                continue
        ins.execute(
            "INSERT INTO spike.eval_queries (query, gold_session_uuid, source) "
            "VALUES (%s, %s, 'synthetic-approved')",
            (q, s["session_uuid"]),
        )
        conn.commit()
        saved += 1
        print("saved.")

    print(f"\nApproved {saved} queries into spike.eval_queries.")


if __name__ == "__main__":
    main()
