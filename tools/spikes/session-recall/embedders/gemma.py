import requests
from config import LITELLM_BASE, LITELLM_KEY, GEMMA_MODEL
from text_prep import gemma_doc, gemma_query


def _embed(inputs):
    resp = requests.post(
        f"{LITELLM_BASE}/embeddings",
        headers={"Authorization": f"Bearer {LITELLM_KEY}"},
        json={"model": GEMMA_MODEL, "input": inputs},
        timeout=120,
    )
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def embed_docs(texts):
    return _embed([gemma_doc(t) for t in texts])


def embed_query(query):
    return _embed([gemma_query(query)])[0]
