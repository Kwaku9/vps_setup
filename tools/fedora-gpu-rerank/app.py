"""GPU cross-encoder reranker for Open WebUI RAG hybrid search.

Serves POST /rerank (and /v1/rerank) in the Cohere/Jina schema that Open WebUI's
ExternalReranker expects:
  request : {"model", "query", "documents": [...], "top_n"}
  response: {"model", "results": [{"index", "relevance_score"}, ...]}   # score per doc

Runs the cross-encoder on the Fedora workstation GPU so no reranking load hits
the RAM-constrained VPS. Reached over the tailnet.

The GPU is a 6GB RTX 3050 shared with whisper-gpu (push-to-talk STT), which
loads on demand and OOMs if it cannot claim ~2GB. This process is resident, so
it must stay small: fp16 weights and a small predict batch keep bge-reranker-v2-m3
under ~1.5GB even at the 8192-token window. See RERANK_DTYPE / RERANK_BATCH_SIZE.
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
# fp16 halves resident weights (bge-reranker-v2-m3: 2166MiB -> 1083MiB) and the
# activations with them. BAAI ships this model for fp16 inference, so scores are
# unchanged in rank order. Set RERANK_DTYPE=float32 to opt back out.
DTYPE = os.getenv("RERANK_DTYPE", "float16" if DEVICE == "cuda" else "float32")
# Peak activation memory scales with batch_size * max_length. The library default
# of 32 at an 8192-token window is what actually spikes VRAM, not the weights.
BATCH_SIZE = int(os.getenv("RERANK_BATCH_SIZE", "4"))


def _load_model() -> CrossEncoder:
    if DEVICE != "cuda" or DTYPE == "float32":
        return CrossEncoder(MODEL_ID, device=DEVICE, max_length=MAX_LEN)
    dtype = getattr(torch, DTYPE)
    # transformers 5 renamed this kwarg from torch_dtype to dtype; the deps here
    # are unpinned, so accept whichever the installed version takes.
    for kwarg in ("dtype", "torch_dtype"):
        try:
            return CrossEncoder(MODEL_ID, device=DEVICE, max_length=MAX_LEN,
                                model_kwargs={kwarg: dtype})
        except TypeError:
            continue
    raise RuntimeError(f"cannot load {MODEL_ID} as {DTYPE}: no accepted dtype kwarg")


model = _load_model()

app = FastAPI(title="fedora-gpu-rerank")


class RerankRequest(BaseModel):
    query: str
    documents: List[str]
    model: Optional[str] = None
    top_n: Optional[int] = None


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_ID, "device": DEVICE,
            "cuda": torch.cuda.is_available(),
            "dtype": str(next(model.model.parameters()).dtype),
            "max_length": MAX_LEN, "batch_size": BATCH_SIZE,
            "vram_allocated_mib": round(torch.cuda.memory_allocated() / 2**20)
            if DEVICE == "cuda" else 0}


@app.post("/rerank")
@app.post("/v1/rerank")
def rerank(req: RerankRequest):
    if not req.documents:
        return {"model": req.model or MODEL_ID, "results": []}
    pairs = [(req.query, d) for d in req.documents]
    scores = model.predict(pairs, convert_to_numpy=True, batch_size=BATCH_SIZE)
    # Return a score for EVERY document keyed by its original index — Open WebUI
    # re-sorts by index and maps scores back to its candidate list, so all
    # indices must be present (do not truncate to top_n here).
    results = [{"index": i, "relevance_score": float(s)} for i, s in enumerate(scores)]
    return {"model": req.model or MODEL_ID, "results": results}
