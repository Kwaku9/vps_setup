import metadata_lib as M

def test_build_summary_input_joins_turns():
    out = M.build_summary_input(["user","assistant"], ["hi","hello"])
    assert out == "user: hi\nassistant: hello"

def test_build_summary_input_head_tail_truncation():
    big = "x" * 60000
    out = M.build_summary_input(["user"], [big], cap=40000, head=28000, tail=12000)
    assert len(out) <= 40000 + 40  # head + marker + tail
    assert "[truncated]" in out
    assert out.startswith("user: " + "x"*100)
    assert out.endswith("x"*100)

def test_parse_metadata_plain_json():
    raw = '{"summary":"did x","categories":["fix"],"services":["litellm"],"topics":["t"],"decisions":["d"]}'
    m = M.parse_metadata(raw)
    assert m["summary"] == "did x"
    assert m["categories"] == ["fix"]
    assert m["services"] == ["litellm"]

def test_parse_metadata_json_embedded_in_prose():
    raw = 'Here you go:\n{"summary":"s","categories":["debug","fix"]}\nThanks!'
    m = M.parse_metadata(raw)
    assert m["summary"] == "s"
    assert m["categories"] == ["debug","fix"]
    assert m["services"] == []  # missing keys default to []

def test_validate_categories_filters_and_caps():
    assert M.validate_categories(["FIX","review","bogus","fix","deploy","config"]) == ["fix","review","deploy"]

def test_clean_entities_dedupes_and_drops_empty():
    d = {"services":["a","a"," ","b"],"topics":[],"decisions":["x"]}
    out = M.clean_entities(d)
    assert out["services"] == ["a","b"]
    assert out["topics"] == []
    assert out["decisions"] == ["x"]
