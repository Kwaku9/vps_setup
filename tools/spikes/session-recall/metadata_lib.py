import json, re

CATEGORIES = {"debug","feature","fix","research","maintenance",
              "deploy","config","refactor","review","security"}

def build_summary_input(types, texts, cap=40000, head=28000, tail=12000):
    parts = [f"{ty}: {tx.strip()}" for ty, tx in zip(types, texts) if tx and tx.strip()]
    s = "\n".join(parts)
    if len(s) <= cap:
        return s
    return s[:head] + "\n…[truncated]…\n" + s[-tail:]

def parse_metadata(raw):
    out = {"summary": "", "categories": [], "services": [], "topics": [], "decisions": []}
    if not raw:
        return out
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return out
    try:
        d = json.loads(m.group(0))
    except Exception:
        return out
    out["summary"] = str(d.get("summary", "")).strip()
    out["categories"] = d.get("categories", []) or []
    for k in ("services", "topics", "decisions"):
        out[k] = d.get(k, []) or []
    return out

def validate_categories(cats):
    seen, res = set(), []
    for c in cats:
        c = str(c).strip().lower()
        if c in CATEGORIES and c not in seen:
            seen.add(c); res.append(c)
        if len(res) == 3:
            break
    return res

def clean_entities(d):
    out = {}
    for k in ("services", "topics", "decisions"):
        seen, res = set(), []
        for v in d.get(k, []) or []:
            v = str(v).strip()
            if v and v.lower() not in seen:
                seen.add(v.lower()); res.append(v)
            if len(res) == 8:
                break
        out[k] = res
    return out
