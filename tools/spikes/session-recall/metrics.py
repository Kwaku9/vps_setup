def recall_at_k(ranked, gold, k):
    return 1.0 if gold in ranked[:k] else 0.0


def precision_at_k(ranked, gold, k):
    return (1.0 / k) if gold in ranked[:k] else 0.0


def reciprocal_rank(ranked, gold):
    for i, item in enumerate(ranked, start=1):
        if item == gold:
            return 1.0 / i
    return 0.0
