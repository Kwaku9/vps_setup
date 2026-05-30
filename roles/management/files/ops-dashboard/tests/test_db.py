from ops_dashboard.sessions.db import build_dsn


def test_build_dsn_from_parts():
    dsn = build_dsn(host="pg", port=5432, db="enterprise", user="postgres", password="s3cr3t")
    assert dsn == "postgresql://postgres:s3cr3t@pg:5432/enterprise"


def test_build_dsn_url_encodes_password():
    dsn = build_dsn(host="pg", port=5432, db="enterprise", user="postgres", password="p@ss/word")
    assert "p%40ss%2Fword" in dsn
