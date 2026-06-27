import requests
from config import NOMIC_BASE
from text_prep import nomic_doc, nomic_query


def _embed(inputs):
    # llama.cpp server: OpenAI-compatible /v1/embeddings, no auth, model name ignored.
    resp = requests.post(
        f"{NOMIC_BASE}/embeddings",
        json={"model": "nomic", "input": inputs},
        timeout=300,
    )
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def embed_docs(texts):
    return _embed([nomic_doc(t) for t in texts])


def embed_query(query):
    return _embed([nomic_query(query)])[0]
