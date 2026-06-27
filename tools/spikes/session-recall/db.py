import psycopg2


def connect():
    # psycopg2 reads PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE from the environment.
    conn = psycopg2.connect()
    conn.autocommit = False
    return conn


def vec_literal(vec):
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
