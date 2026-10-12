from ops_dashboard.api.routers.repo_radar import _sanitize


def test_non_github_pr_urls_are_dropped():
    snap = {"repos": [], "prs": {"vps_setup": [
        {"number": 1, "title": "ok", "url": "https://github.com/Kwaku9/vps_setup/pull/1"},
        {"number": 2, "title": "xss", "url": "javascript:alert(1)"},
        {"number": 3, "title": "http", "url": "http://github.com/x/y/pull/3"},
        {"number": 4, "title": "no url"},
    ]}}
    prs = _sanitize(snap, "vps")["prs"]["vps_setup"]
    assert [p["number"] for p in prs] == [1]


def test_malformed_prs_shapes_do_not_crash():
    assert _sanitize({"prs": None}, "vps")["prs"] == {}
    assert _sanitize({"prs": ["x"]}, "vps")["prs"] == {}
    assert _sanitize({"prs": {"r": "x"}}, "vps")["prs"] == {}
