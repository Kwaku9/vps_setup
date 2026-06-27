from sampling import stratified_sample


def _rows():
    rows = []
    for p, count in [("alpha", 10), ("beta", 10), ("gamma", 2)]:
        for i in range(count):
            rows.append({"project": p, "id": f"{p}-{i}"})
    return rows


def test_returns_requested_count():
    assert len(stratified_sample(_rows(), 6)) == 6


def test_spreads_across_projects():
    sample = stratified_sample(_rows(), 6)
    projects = {r["project"] for r in sample}
    assert projects == {"alpha", "beta", "gamma"}  # all three represented early


def test_caps_at_available():
    assert len(stratified_sample(_rows(), 1000)) == 22


def test_deterministic_with_seed():
    a = [r["id"] for r in stratified_sample(_rows(), 8, seed=42)]
    b = [r["id"] for r in stratified_sample(_rows(), 8, seed=42)]
    assert a == b
