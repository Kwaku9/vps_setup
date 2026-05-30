from ops_dashboard.sessions.live_state import derive_live_state


def test_notification_sets_needs_input():
    st = derive_live_state("Notification", prev_needs_input=False)
    assert st.live_status == "waiting_input"
    assert st.needs_input is True


def test_pretooluse_is_running_with_stage():
    st = derive_live_state("PreToolUse", tool_name="Bash", prev_needs_input=False)
    assert st.live_status == "running"
    assert st.needs_input is False
    assert "Bash" in st.current_stage


def test_stop_preserves_outstanding_needs_input():
    st = derive_live_state("Stop", prev_needs_input=True)
    assert st.live_status == "waiting_input"
    assert st.needs_input is True


def test_stop_after_normal_turn_clears():
    st = derive_live_state("Stop", prev_needs_input=False)
    assert st.live_status == "waiting_input"
    assert st.needs_input is False


def test_session_end_is_terminal():
    st = derive_live_state("SessionEnd", prev_needs_input=True)
    assert st.live_status == "ended"
    assert st.needs_input is False
