import hashlib, pytest
from grafana_reports.store import Store
from grafana_reports.config import Settings

def _s():
    return Settings(grafana_url="", grafana_sa_token="", auth_token="", s3_bucket=None,
                    s3_prefix="reports", s3_region="us-east-1", presign_ttl=3600,
                    litellm_url=None, litellm_model="m", litellm_key=None, catalog_path="",
                    refresh_interval=900, default_width=1000, default_height=500,
                    render_timeout=15, fuzzy_threshold=70)

def test_save_returns_sha256_and_get_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    st = Store(_s())
    png = b"\x89PNG fake bytes"
    rid = st.save(png, {"dashboard_uid": "u", "panel_id": 1})
    assert rid == hashlib.sha256(png).hexdigest()
    assert st.get(rid) == png
    assert st.exists(rid)

def test_identical_png_dedupes_to_same_id(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    st = Store(_s())
    a = st.save(b"same", {"k": 1})
    b = st.save(b"same", {"k": 2})
    assert a == b

def test_get_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    with pytest.raises(KeyError):
        Store(_s()).get("deadbeef")

def test_presign_none_without_s3(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    st = Store(_s())
    rid = st.save(b"x", {})
    assert st.presign(rid) is None

def test_get_rejects_path_traversal_id(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    st = Store(_s())
    with pytest.raises(KeyError):
        st.get("../../etc/passwd")

def test_exists_false_for_invalid_id(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DIR", str(tmp_path))
    st = Store(_s())
    assert st.exists("../../etc/passwd") is False
    assert st.exists("not-a-hex") is False
