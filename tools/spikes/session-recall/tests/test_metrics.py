from metrics import recall_at_k, precision_at_k, reciprocal_rank

RANKED = ["a", "b", "c", "d", "e"]


def test_recall_hit_in_top_k():
    assert recall_at_k(RANKED, "a", 1) == 1.0
    assert recall_at_k(RANKED, "c", 3) == 1.0
    assert recall_at_k(RANKED, "c", 1) == 0.0
    assert recall_at_k(RANKED, "z", 5) == 0.0


def test_precision_is_recall_over_k():
    assert precision_at_k(RANKED, "a", 1) == 1.0
    assert precision_at_k(RANKED, "c", 3) == 1.0 / 3
    assert precision_at_k(RANKED, "z", 3) == 0.0


def test_reciprocal_rank():
    assert reciprocal_rank(RANKED, "a") == 1.0
    assert reciprocal_rank(RANKED, "b") == 0.5
    assert reciprocal_rank(RANKED, "z") == 0.0
