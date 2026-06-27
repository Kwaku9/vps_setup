from db import connect


def find_sessions(conn, project, after, title, limit=25):
    clauses, params = [], []
    if project:
        clauses.append("COALESCE(p.display_name, p.project_path) ILIKE %s")
        params.append(f"%{project}%")
    if after:
        clauses.append("s.started_at >= %s")
        params.append(after)
    if title:
        clauses.append("s.title ILIKE %s")
        params.append(f"%{title}%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        "SELECT s.session_uuid, s.started_at, "
        "COALESCE(p.display_name, p.project_path) AS project, "
        "COALESCE(s.title, '(untitled)') AS title "
        "FROM sessions.sessions s JOIN sessions.projects p ON p.id = s.project_id"
        + where + " ORDER BY s.started_at DESC LIMIT %s"
    )
    params.append(limit)
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchall()  # (uuid, started_at, project, title)


def session_title(conn, uuid):
    cur = conn.cursor()
    cur.execute("SELECT title FROM sessions.sessions WHERE session_uuid = %s", (uuid,))
    row = cur.fetchone()
    return row[0] if row else None


def add_one(conn):
    query = input("\nYour query (blank to quit) > ").strip()
    if not query:
        return False
    project = input("  filter project contains > ").strip()
    after = input("  on/after date (YYYY-MM-DD, blank=any) > ").strip() or None
    title = input("  title contains > ").strip()

    rows = find_sessions(conn, project, after, title)
    if not rows:
        print("  no sessions matched; loosen the filters and retry.")
        return True
    print(f"\n  {'#':>2}  {'started':10}  {'session_id':36}  title")
    for i, (uuid, started, proj, ttl) in enumerate(rows, 1):
        d = started.strftime("%Y-%m-%d") if started else "?"
        print(f"  {i:>2}  {d:10}  {uuid:36}  [{proj}] {ttl[:50]}")

    pick = input("\n  correct answer? (row number, or paste a session_id, 'n'=skip) > ").strip()
    if pick.lower() in ("n", ""):
        print("  skipped.")
        return True
    if pick.isdigit() and 1 <= int(pick) <= len(rows):
        gold = rows[int(pick) - 1][0]
    else:
        gold = pick  # treat as a pasted session_id
    title_found = session_title(conn, gold)
    if not title_found:
        print(f"  session_id {gold} not found in sessions.sessions; not saved.")
        return True

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO spike.eval_queries (query, gold_session_uuid, source) "
        "VALUES (%s, %s, 'manual')", (query, gold))
    conn.commit()
    print(f"  saved (source=manual): {gold}")
    print(f"  title : {title_found}")
    print(f"  resume: claude --resume {gold}")
    return True


def main():
    conn = connect()
    print("Add your own scored queries (source=manual). Blank query to quit.")
    while add_one(conn):
        pass


if __name__ == "__main__":
    main()
