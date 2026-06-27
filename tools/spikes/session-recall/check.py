from db import connect


def main():
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM sessions.sessions")
    n_sessions = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM sessions.messages")
    n_messages = cur.fetchone()[0]
    cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    has_vector = cur.fetchone() is not None
    print(f"sessions.sessions : {n_sessions}")
    print(f"sessions.messages : {n_messages}")
    print(f"pgvector present  : {has_vector}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
