import importlib.util
import pathlib

import pytest

# Load the hyphenated module by path. The module MUST NOT import neo4j at top
# level, or this exec fails where the driver isn't installed.
_MODPATH = pathlib.Path(__file__).resolve().parent.parent / "ingest-code-graph.py"
_spec = importlib.util.spec_from_file_location("ingest_code_graph", _MODPATH)
icg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(icg)

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "knowledge-graph.sample.json"


def test_load_graph_parses_fixture():
    g = icg.load_graph(str(FIXTURE))
    assert len(g["nodes"]) == 5
    assert len(g["edges"]) == 3
    assert g["project"]["name"] == "sample-proj"
    assert g["layers"][0]["id"] == "L1"
    assert len(g["tour"]) == 2


def test_load_graph_requires_nodes_and_edges(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"version": "1.0"}')
    with pytest.raises(ValueError):
        icg.load_graph(str(bad))


def test_pascal_label():
    assert icg.pascal_label("function") == "Function"
    assert icg.pascal_label("service") == "Service"


def test_node_to_params_basic():
    g = icg.load_graph(str(FIXTURE))
    fn = next(n for n in g["nodes"] if n["id"] == "fn1")
    p = icg.node_to_params(fn)
    assert p["id"] == "fn1"
    assert p["label"] == "Function"
    assert p["props"]["name"] == "handler"
    assert p["props"]["lineStart"] == 10
    assert p["props"]["lineEnd"] == 20
    # None-valued props are dropped
    assert "languageNotes" not in p["props"]


def test_node_to_params_flattens_meta():
    g = icg.load_graph(str(FIXTURE))
    svc = next(n for n in g["nodes"] if n["id"] == "svc1")
    p = icg.node_to_params(svc)
    assert p["label"] == "Service"
    assert p["props"]["domain_entryType"] == "http"
    assert p["props"]["domain_entities"] == ["Message"]
    tbl = next(n for n in g["nodes"] if n["id"] == "tbl1")
    pt = icg.node_to_params(tbl)
    assert pt["props"]["knowledge_category"] == "data"
    assert pt["props"]["knowledge_wikilinks"] == ["[[messages]]"]


def test_rel_type():
    assert icg.rel_type("imports") == "IMPORTS"
    assert icg.rel_type("depends_on") == "DEPENDS_ON"


def test_edge_to_params():
    g = icg.load_graph(str(FIXTURE))
    e = next(x for x in g["edges"] if x["source"] == "f1")
    p = icg.edge_to_params(e)
    assert p["source"] == "f1"
    assert p["target"] == "fn1"
    assert p["rel"] == "CONTAINS"
    assert p["props"]["weight"] == 1.0
    assert p["props"]["direction"] == "forward"
    assert p["props"]["description"] == "file has fn"


def test_edge_to_params_drops_missing_description():
    g = icg.load_graph(str(FIXTURE))
    e = next(x for x in g["edges"] if x["source"] == "fn1" and x["target"] == "svc1")
    p = icg.edge_to_params(e)
    assert "description" not in p["props"]


def test_normalize_name():
    assert icg.normalize_name("Telegram_Gateway") == "telegram-gateway"
    assert icg.normalize_name("  chat.aicortex.cloud ") == "chat-aicortex-cloud"


def test_find_link_candidates_exact():
    g = icg.load_graph(str(FIXTURE))
    sm = [
        {"label": "Container", "name": "telegram-gateway"},
        {"label": "Route", "name": "chat.aicortex.cloud"},
        {"label": "Database", "name": "enterprise"},
        {"label": "Pod", "name": "ai-stack-pod"},
    ]
    cands = icg.find_link_candidates(g["nodes"], sm)
    # svc1->Container and ep1->Route are exact; tbl1 'sessions' matches nothing.
    keys = {(c["code_id"], c["target_label"], c["basis"]) for c in cands}
    assert ("svc1", "Container", "exact") in keys
    assert ("ep1", "Route", "exact") in keys
    assert all(c["code_type"] in ("service", "endpoint", "table") for c in cands)
    assert all(c["approved"] is False for c in cands)
    # exact entries are ordered before substring entries
    bases = [c["basis"] for c in cands]
    assert bases == sorted(bases, key=lambda b: 0 if b == "exact" else 1)


def test_find_link_candidates_substring_and_whitelist():
    code = [
        {"id": "svc9", "type": "service", "name": "telegram-gateway-bot"},
        {"id": "fn9", "type": "function", "name": "telegram-gateway"},  # not whitelisted
    ]
    sm = [{"label": "Container", "name": "telegram-gateway"}]
    cands = icg.find_link_candidates(code, sm)
    assert len(cands) == 1
    assert cands[0]["code_id"] == "svc9"
    assert cands[0]["basis"] == "substring"
    assert cands[0]["confidence"] == "low"


def test_tour_step_id_uses_order_then_index():
    assert icg.tour_step_id({"order": 3}, 0) == "tour-step-3"
    assert icg.tour_step_id({}, 5) == "tour-step-5"
    assert icg.tour_step_id({"order": None}, 2) == "tour-step-2"
