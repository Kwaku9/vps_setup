import random


def stratified_sample(rows, n, seed=0):
    rng = random.Random(seed)
    by_project = {}
    for r in rows:
        by_project.setdefault(r["project"], []).append(r)
    for p in by_project:
        rng.shuffle(by_project[p])

    order = sorted(by_project.keys())
    idx = {p: 0 for p in order}
    result = []
    while len(result) < n and any(idx[p] < len(by_project[p]) for p in order):
        for p in order:
            if idx[p] < len(by_project[p]):
                result.append(by_project[p][idx[p]])
                idx[p] += 1
                if len(result) >= n:
                    break
    return result
