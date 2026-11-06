import datetime as dt
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import recall  # noqa: E402


def test_gemma_query_prefix():
    assert recall.gemma_query("how did auth evolve") == \
        "task: search result | query: how did auth evolve"


def test_vec_literal():
    assert recall.vec_literal([0.5, -1.0]) == "[0.500000,-1.000000]"


def test_build_search_sql_no_filters_has_no_clauses():
    sql, params = recall.build_search_sql(None, None)
    assert params == {}
    assert "c.project = %(project)s" not in sql
    assert "c.ts >= %(since)s" not in sql
    assert "ORDER BY c.embedding <=> %(qv)s::vector" in sql


def test_build_search_sql_project_filter():
    sql, params = recall.build_search_sql("vps_setup", None)
    assert params == {"project": "vps_setup"}
    assert "c.project = %(project)s" in sql


def test_build_search_sql_both_filters():
    sql, params = recall.build_search_sql("vps_setup", "2026-01-01")
    assert params == {"project": "vps_setup", "since": "2026-01-01"}
    assert "c.ts >= %(since)s" in sql


def test_shape_hit():
    row = ("uuid-1", "vps_setup", "  some snippet  ",
           dt.datetime(2026, 6, 1, 12, 0), 0.25, "My Session")
    out = recall.shape_hit(row)
    assert out == {
        "session_uuid": "uuid-1",
        "title": "My Session",
        "project": "vps_setup",
        "date": "2026-06-01",
        "snippet": "some snippet",
        "score": 0.75,
    }


# --- HNSW scan settings (2026-11-06: ef_search 40 starved the 160-chunk prefetch to ~38) ---

class _Cur:
    def __init__(self, log, fail_on=None):
        self.log, self.fail_on = log, fail_on

    def execute(self, sql, params=None):
        self.log.append(sql.strip())
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("boom")

    def fetchall(self):
        return [("row",)]


class _Conn:
    autocommit = True  # what server._conn() hands us: SET LOCAL outside BEGIN is a silent no-op

    def __init__(self, fail_on=None):
        self.log, self.fail_on = [], fail_on

    def cursor(self):
        return _Cur(self.log, self.fail_on)


def test_ann_settings_defaults(monkeypatch):
    monkeypatch.delenv("RECALL_EF_SEARCH", raising=False)
    monkeypatch.delenv("RECALL_ITERATIVE_SCAN", raising=False)
    assert recall.ann_settings() == ["SET LOCAL hnsw.ef_search = 100",
                                     "SET LOCAL hnsw.iterative_scan = relaxed_order"]


def test_ann_settings_env_override(monkeypatch):
    monkeypatch.setenv("RECALL_EF_SEARCH", "40")
    monkeypatch.setenv("RECALL_ITERATIVE_SCAN", "off")
    assert recall.ann_settings() == ["SET LOCAL hnsw.ef_search = 40", "SET LOCAL hnsw.iterative_scan = off"]


def test_ann_settings_rejects_injection_and_range():
    import pytest
    for bad in ("100; DROP TABLE x", "0", "5000"):
        with pytest.raises(ValueError):
            recall.ann_settings(ef_search=bad, iterative_scan="off")
    with pytest.raises(ValueError):
        recall.ann_settings(ef_search=100, iterative_scan="relaxed_order; RESET ALL")


def test_run_ann_wraps_settings_and_search_in_one_transaction():
    conn = _Conn()
    rows = recall.run_ann(conn, "SELECT search", {}, settings=["SET LOCAL a", "SET LOCAL b"])
    assert rows == [("row",)]
    assert conn.log == ["BEGIN READ ONLY", "SET LOCAL a", "SET LOCAL b", "SELECT search", "ROLLBACK"]


def test_run_ann_ends_transaction_even_when_search_fails():
    import pytest
    conn = _Conn(fail_on="SELECT search")
    with pytest.raises(RuntimeError):
        recall.run_ann(conn, "SELECT search", {}, settings=["SET LOCAL a"])
    assert conn.log[-1] == "ROLLBACK"


def test_search_sql_materializes_candidates_and_orders_by_distance_explicitly():
    sql, _ = recall.build_search_sql(None, None)
    assert "WITH hits AS MATERIALIZED (" in sql
    assert "ORDER BY h.session_uuid, h.dist" in sql  # per-session best chunk, independent of scan order


def test_search_sessions_applies_ann_settings(monkeypatch):
    monkeypatch.setattr(recall, "embed_query", lambda q: [0.0, 1.0])
    conn = _Conn()
    conn.cursor = lambda: _RowsCur(conn.log)
    recall.search_sessions(conn, "q", k=2)
    assert conn.log[0] == "BEGIN READ ONLY"
    assert any(s.startswith("SET LOCAL hnsw.iterative_scan") for s in conn.log[1:3])
    assert conn.log[-1] == "ROLLBACK"


class _RowsCur(_Cur):
    def __init__(self, log):
        super().__init__(log)

    def fetchall(self):
        return [("u1", "p", "s", dt.datetime(2026, 1, 1), 0.2, "t")]
