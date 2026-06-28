import requests
from config import NOMIC_BASE
from text_prep import nomic_doc, nomic_query


def _post(inputs):
    # llama.cpp server: OpenAI-compatible /v1/embeddings, no auth, model name ignored.
    resp = requests.post(
        f"{NOMIC_BASE}/embeddings",
        json={"model": "nomic", "input": inputs},
        timeout=300,
    )
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def _embed(inputs):
    # llama.cpp 500s when an input exceeds the model's 2048-token context.
    # Split the batch to isolate the offender; truncate a lone overlong item and retry.
    try:
        return _post(inputs)
    except requests.HTTPError:
        if len(inputs) > 1:
            mid = len(inputs) // 2
            return _embed(inputs[:mid]) + _embed(inputs[mid:])
        s = inputs[0]
        if len(s) > 800:
            return _embed([s[: int(len(s) * 0.7)]])
        raise


def embed_docs(texts):
    return _embed([nomic_doc(t) for t in texts])


def embed_query(query):
    return _embed([nomic_query(query)])[0]
