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
