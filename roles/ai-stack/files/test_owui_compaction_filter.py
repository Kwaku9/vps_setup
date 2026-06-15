import importlib.util, pathlib, pytest

spec = importlib.util.spec_from_file_location(
    "ocf", pathlib.Path(__file__).parent / "owui-compaction-filter.py")
ocf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ocf)

V = dict(output_reserve_pct=0.25, min_output_reserve=4096,
         history_target_pct=0.10, history_trigger_pct=0.15,
         history_abs_cap=65536)


def test_est_tokens_heuristic():
    assert ocf.est_tokens("a" * 400) == 115  # 400/4*1.15


def test_compute_budget_scales_with_window():
    b = ocf.compute_budget(200_000, overhead=0, v=V)
    assert b["target"] == 20_000 and b["trigger"] == 30_000


def test_compute_budget_abs_cap_on_huge_window():
    b = ocf.compute_budget(1_000_000, overhead=0, v=V)
    assert b["target"] == 65_536 and b["trigger"] == 65_536


def test_compute_budget_usable_clamps_trigger():
    b = ocf.compute_budget(8_000, overhead=1_000, v=V)
    # reserve=max(4096, 2000)=4096; usable=8000-4096-1000=2904; 15% of 8000=1200
    assert b["trigger"] == min(1_200, 65_536, 2_904) == 1_200


def test_compact_bookends_and_recap():
    convo = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
             for i in range(20)]
    out = ocf.compact(convo, "RECAP", first_n=3, last_n=9, target=10_000)
    assert len(out) == 13
    assert out[:3] == convo[:3]
    assert out[3] == {"role": "system", "content": "Summary of earlier conversation:\nRECAP"}
    assert out[4:] == convo[-9:]


def test_compact_noop_when_no_middle():
    convo = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    assert ocf.compact(convo, "RECAP", first_n=3, last_n=9, target=10_000) == convo


def test_parse_window_reads_max_input_tokens():
    info = {"data": [{"model_name": "claude-opus-4-6",
                      "model_info": {"max_input_tokens": 200000}}]}
    assert ocf.parse_window(info, "claude-opus-4-6", fallback=131072) == 200000
    assert ocf.parse_window(info, "unknown", fallback=131072) == 131072
