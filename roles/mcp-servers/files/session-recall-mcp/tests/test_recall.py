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
