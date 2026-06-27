from datasets import build_transcript

MSGS = [("user", "do X"), ("assistant", "okay"), ("progress", "..."), ("user", "now Y")]


def test_useronly_keeps_only_user():
    assert build_transcript(MSGS, "useronly") == "user: do X\nuser: now Y"


def test_userasst_keeps_user_and_assistant():
    assert build_transcript(MSGS, "userasst") == "user: do X\nassistant: okay\nuser: now Y"


def test_skips_blank():
    assert build_transcript([("user", "  "), ("user", "hi")], "useronly") == "user: hi"
