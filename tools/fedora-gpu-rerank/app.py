"""GPU cross-encoder reranker for Open WebUI RAG hybrid search.

Serves POST /rerank (and /v1/rerank) in the Cohere/Jina schema that Open WebUI's
ExternalReranker expects:
  request : {"model", "query", "documents": [...], "top_n"}
  response: {"model", "results": [{"index", "relevance_score"}, ...]}   # score per doc

Runs cross-encoder/ms-marco-MiniLM-L-12-v2 on the Fedora workstation GPU so no
reranking load hits the RAM-constrained VPS. Reached over the tailnet.
"""
import os
from typing import List, Optional

import torch
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import CrossEncoder

MODEL_ID = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-12-v2")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MAX_LEN = int(os.getenv("RERANK_MAX_LENGTH", "512"))

model = CrossEncoder(MODEL_ID, device=DEVICE, max_length=MAX_LEN)

app = FastAPI(title="fedora-gpu-rerank")


class RerankRequest(BaseModel):
    query: str
    documents: List[str]
    model: Optional[str] = None
    top_n: Optional[int] = None


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_ID, "device": DEVICE,
            "cuda": torch.cuda.is_available()}


@app.post("/rerank")
@app.post("/v1/rerank")
def rerank(req: RerankRequest):
    if not req.documents:
        return {"model": req.model or MODEL_ID, "results": []}
    pairs = [(req.query, d) for d in req.documents]
    scores = model.predict(pairs, convert_to_numpy=True)
    # Return a score for EVERY document keyed by its original index — Open WebUI
    # re-sorts by index and maps scores back to its candidate list, so all
    # indices must be present (do not truncate to top_n here).
    results = [{"index": i, "relevance_score": float(s)} for i, s in enumerate(scores)]
    return {"model": req.model or MODEL_ID, "results": results}
