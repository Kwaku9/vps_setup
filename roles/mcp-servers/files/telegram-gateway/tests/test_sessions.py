import json
import os
import time

from telegram_gateway import sessions


def _write_session(root, enc_dir, sid, lines, age_days=0):
    d = os.path.join(root, enc_dir)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{sid}.jsonl")
    with open(path, "w") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")
    if age_days:
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
    return path


def test_list_sessions_extracts_cwd_and_summary(tmp_path):
    root = str(tmp_path)
    _write_session(root, "-workspace-vscode-projects-vps-setup", "abc", [
        {"type": "summary", "summary": "fix approval gate"},
        {"type": "user", "cwd": "/workspace/vscode-projects/vps_setup",
         "message": {"content": "hello"}},
    ])
    out = sessions.list_sessions(root=root, within_days=14)
    assert len(out) == 1
    s = out[0]
    assert s.session_id == "abc"
    assert s.workspace == "/workspace/vscode-projects/vps_setup"
    assert s.summary == "fix approval gate"
    assert s.mtime_iso  # ISO string present


def test_summary_falls_back_to_first_user_message(tmp_path):
    root = str(tmp_path)
    _write_session(root, "-w", "noSum", [
        {"type": "user", "cwd": "/w", "message": {"content": "do the thing"}},
    ])
    out = sessions.list_sessions(root=root, within_days=14)
    assert out[0].summary == "do the thing"


def test_summary_from_block_list_content(tmp_path):
    root = str(tmp_path)
    _write_session(root, "-w", "blocks", [
        {"type": "user", "cwd": "/w", "message": {"content": [
            {"type": "text", "text": "resume the migration"}]}},
    ])
    out = sessions.list_sessions(root=root, within_days=14)
    assert out[0].summary == "resume the migration"


def test_old_sessions_excluded(tmp_path):
    root = str(tmp_path)
    _write_session(root, "-w", "old", [
        {"type": "user", "cwd": "/w", "message": {"content": "ancient"}},
    ], age_days=30)
    assert sessions.list_sessions(root=root, within_days=14) == []


def test_workspace_filter(tmp_path):
    root = str(tmp_path)
    _write_session(root, "-a", "s1", [{"type": "user", "cwd": "/a",
                                       "message": {"content": "x"}}])
    _write_session(root, "-b", "s2", [{"type": "user", "cwd": "/b",
                                       "message": {"content": "y"}}])
    out = sessions.list_sessions(root=root, within_days=14, workspace="/a")
    assert [s.session_id for s in out] == ["s1"]


def test_list_workspaces_groups_and_counts(tmp_path):
    root = str(tmp_path)
    _write_session(root, "-vps", "s1", [{"type": "user",
                   "cwd": "/workspace/vscode-projects/vps_setup",
                   "message": {"content": "a"}}])
    ws = sessions.list_workspaces(root=root, within_days=14)
    assert len(ws) == 1
    assert ws[0]["workspace"] == "/workspace/vscode-projects/vps_setup"
    assert ws[0]["label"] == "vps_setup"
    assert ws[0]["session_count"] == 1
    assert ws[0]["last_active"]


def test_file_without_cwd_is_skipped(tmp_path):
    root = str(tmp_path)
    _write_session(root, "-w", "nocwd", [{"type": "summary",
                                          "summary": "orphan"}])
    assert sessions.list_sessions(root=root, within_days=14) == []


def test_clean_user_title_passes_real_text():
    assert sessions._clean_user_title("Fix the login bug") == "Fix the login bug"


def test_clean_user_title_drops_injected_blobs():
    assert sessions._clean_user_title("[Context: You are APM ...]") == ""
    assert sessions._clean_user_title("### Task:\nSuggest follow-ups") == ""
    assert sessions._clean_user_title("<command-name>/compact</command-name>") == ""


def test_clean_user_title_handles_block_list():
    assert sessions._clean_user_title(
        [{"type": "text", "text": "resume migration"}]) == "resume migration"


def test_last_aititle_reads_last_value(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join([
        json.dumps({"type": "ai-title", "aiTitle": "First Draft", "sessionId": "s"}),
        json.dumps({"type": "mode", "mode": "x", "sessionId": "s"}),
        json.dumps({"type": "ai-title", "aiTitle": "Final Title", "sessionId": "s"}),
    ]) + "\n")
    assert sessions._last_aititle(str(p)) == "Final Title"


def test_last_aititle_absent_returns_empty(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
    assert sessions._last_aititle(str(p)) == ""


def test_last_aititle_found_in_tail_of_large_file(tmp_path):
    p = tmp_path / "s.jsonl"
    filler = json.dumps({"type": "mode", "mode": "x", "sessionId": "s"})
    lines = [filler] * 300 + [
        json.dumps({"type": "ai-title", "aiTitle": "Tail Title", "sessionId": "s"})]
    p.write_text("\n".join(lines) + "\n")
    assert sessions._last_aititle(str(p)) == "Tail Title"
