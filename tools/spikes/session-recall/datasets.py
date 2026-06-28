DATASETS = {
    "useronly": "m.type = 'user'",
    "userasst": "m.type IN ('user','assistant')",
}

_KEEP = {"useronly": {"user"}, "userasst": {"user", "assistant"}}


def build_transcript(messages, dataset):
    keep = _KEEP[dataset]
    parts = []
    for typ, txt in messages:
        if typ in keep and txt and txt.strip():
            parts.append(f"{typ}: {txt.strip()}")
    return "\n".join(parts)


def iter_gemma_docs(conn, dataset, limit=None):
    where = DATASETS[dataset]
    sql = f"""
        SELECT m.id, s.session_uuid,
               COALESCE(p.display_name, p.project_path) AS project,
               m.timestamp, m.content_text
        FROM sessions.messages m
        JOIN sessions.sessions s ON s.id = m.session_id
        JOIN sessions.projects p ON p.id = s.project_id
        WHERE {where}
          AND m.content_text IS NOT NULL
          AND length(trim(m.content_text)) > 0
        ORDER BY m.id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    cur = conn.cursor(name="gemma_stream")
    cur.itersize = 1000
    cur.execute(sql)
    for r in cur:
        yield {"message_id": r[0], "session_uuid": r[1], "project": r[2],
               "ts": r[3], "content_text": r[4]}
    cur.close()


def iter_nomic_docs(conn, dataset, limit=None, max_chars=3500):
    sql = """
        SELECT s.session_uuid,
               COALESCE(p.display_name, p.project_path) AS project,
               s.started_at, s.title,
               array_agg(m.type ORDER BY m.sequence_num) AS types,
               array_agg(m.content_text ORDER BY m.sequence_num) AS texts
        FROM sessions.sessions s
        JOIN sessions.projects p ON p.id = s.project_id
        JOIN sessions.messages m ON m.session_id = s.id
        WHERE m.content_text IS NOT NULL AND length(trim(m.content_text)) > 0
        GROUP BY s.session_uuid, project, s.started_at, s.title
        ORDER BY s.started_at
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    cur = conn.cursor(name="nomic_stream")
    cur.itersize = 200
    cur.execute(sql)
    for r in cur:
        transcript = build_transcript(list(zip(r[4], r[5])), dataset)
        if not transcript:
            continue
        yield {"session_uuid": r[0], "project": r[1], "started_at": r[2],
               "title": r[3], "transcript": transcript[:max_chars]}
    cur.close()
