KW_TABLES = {"useronly": "spike.kw_useronly", "userasst": "spike.kw_userasst"}
KW_FILTER = {"useronly": "m.type = 'user'", "userasst": "m.type IN ('user','assistant')"}


def populate(conn):
    cur = conn.cursor()
    for ds, table in KW_TABLES.items():
        cur.execute(f"TRUNCATE {table};")
        cur.execute(f"""
            INSERT INTO {table} (session_uuid, doc)
            SELECT s.session_uuid,
                   to_tsvector('english',
                       string_agg(m.content_text, ' ' ORDER BY m.sequence_num))
            FROM sessions.sessions s
            JOIN sessions.messages m ON m.session_id = s.id
            WHERE {KW_FILTER[ds]} AND m.content_text IS NOT NULL
            GROUP BY s.session_uuid;
        """)
    conn.commit()
    cur.close()


def search(conn, query, dataset, k=10):
    table = KW_TABLES[dataset]
    cur = conn.cursor()
    cur.execute(f"""
        SELECT session_uuid, ts_rank(doc, websearch_to_tsquery('english', %s)) AS rank
        FROM {table}
        WHERE doc @@ websearch_to_tsquery('english', %s)
        ORDER BY rank DESC
        LIMIT %s;
    """, (query, query, k))
    rows = cur.fetchall()
    cur.close()
    return [r[0] for r in rows]
