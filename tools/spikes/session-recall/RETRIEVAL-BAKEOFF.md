# Retrieval Bake-off (v2) — dense vs keyword vs GraphRAG, quality + speed/scale

**Goal:** for the user's RAG-style questions (multi-session synthesis, not single-session
routing), compare retrieval approaches on **answer quality** AND **speed/scale**, on the
9 human-curated gold queries (`spike.eval_queries`, source='manual').

**Why v2:** the first board proved semantic >> keyword (keyword 0/9) but the single-session
hit-rate metric doesn't fit the user's real intent — they want *answers synthesized across
sessions*. So: switch the metric to LLM-judged answer quality, add GraphRAG (the relationship
structure is what ties scattered sessions together), and benchmark the engine axis (pgvector
vs Qdrant) on speed/scale.

## Methods on the final board

| # | Method | Store | Differentiator | Axis |
|---|---|---|---|---|
| 1 | dense · gemma-3500 | pgvector | per-message passages, 3500-char chunks | quality + speed |
| 2 | dense · gemma-512 | pgvector | finer ~512-token (~2000-char) passages | quality + speed |
| 3 | dense · nomic | pgvector | one vector / whole session | quality + speed |
| 4 | dense · gemma (perf) | **Qdrant** | same vectors, different engine | **speed/scale only** (quality ties) |
| 5 | keyword | Postgres FTS | literal term match | quality + speed |
| 6 | **GraphRAG** | Neo4j | vector seed → relationship expansion | quality + speed |
| 7 | hybrid | pgvector+FTS | RRF(dense, keyword) | quality + speed |

**Key truth (engine axis):** with identical embeddings + exact/high-recall search, all vector
engines return the same neighbors → they **tie on quality**. pgvector-vs-Qdrant is therefore a
**speed/scale** comparison only (latency p50/p95, recall@K vs exact, index build, RAM/disk, QPS).

## Metrics

- **Quality (primary):** for each (query, method): retrieve top-K context → an LLM **synthesizes
  an answer** → an LLM **judge** scores answers (1–5 or pairwise) on faithfulness + completeness.
  Plus retrieved-context relevance (does the gold session's content appear in the retrieved set).
- **Speed:** retrieval latency p50/p95 per method.
- **Scale/resource:** index size (RAM/disk), build time; QPS for the engine benchmark.

## Phases

- **Phase 1 — gemma-512 dense variant.** Add `spike.emb_gemma512_{useronly,userasst}`; re-embed
  gemma at ~2000-char chunks on the Fedora GPU; sync up. Reuses the proven pipeline.
- **Phase 2 — hybrid (RRF).** `search.rank` add a `hybrid` method fusing dense + keyword ranked
  lists via reciprocal-rank fusion. Small code add.
- **Phase 3 — Qdrant perf benchmark.** Deploy Qdrant (container, `enterprise_network`); load the
  gemma-3500 vectors; benchmark query latency / recall@K / RAM vs pgvector. Quality ties — perf only.
- **Phase 4 — GraphRAG (Neo4j).** What's missing today: embeddings on graph nodes + a vector
  index + a retrieval pipeline. Plan: create a Neo4j **vector index** over chunk embeddings
  (load the gemma chunk vectors onto `:Chunk`/`:Message` nodes), then GraphRAG retrieval =
  vector search for seed nodes → traverse relationships (`HAS_MESSAGE`, `TOUCHES_FILE`,
  `PRODUCED_COMMIT`, shared `:File`/`:ToolType`/`:Project`) to pull connected context → return
  the expanded passage set. The graph's job is **cross-session expansion** (find sessions
  connected to the seed by shared files/tools/projects), which is exactly what the user's
  "history across all sessions" questions need.
- **Phase 5 — answer-quality harness.** `rag_eval.py`: per (query, method) retrieve → synthesize
  (LiteLLM chat) → judge (LiteLLM chat, LLM-as-judge). Capture latency + resource alongside.
- **Phase 6 — unified board.** Quality + speed + resource for all 7 methods on the 9 queries.

## Reuse / constraints

- Fedora GPU pipeline (spike-pg mirror + gemma-cuda/nomic-cuda + spike-tools) is still up —
  reuse it for the gemma-512 re-embed, then `pg_dump` the new table up to the VPS.
- pgvector remains the dense store of record (consolidation: vectors + session metadata + the
  graph's source tables in one Postgres). Qdrant is a perf challenger, not a production proposal.
- Neo4j is `neo4j-db` (bolt :7687) on the VPS; the sessions graph is loaded from Postgres via
  `roles/neo4j/files/sessions-graph/` (Postgres is the source of truth — graph is downstream).
- All scratch lives under the `spike` schema / throwaway containers; teardown unchanged.

---

## Results (2026-06-28) — 9 human-curated queries, userasst

RAG answer-quality (LLM-judged 1-5, synth=claude-haiku-4-5, judge=claude-sonnet-4-6):

| method      | avg_quality | retr_ms |
|-------------|------------:|--------:|
| gemma-512   | 3.00        | 920     |
| gemma-3500  | 2.67        | 1079    |
| nomic       | 2.67        | 213     |
| hybrid      | 2.44        | 919     |
| graphrag    | 2.44        | 833     |
| keyword     | 2.22        | 39      |

Engine axis (gemma_userasst, 46k vectors, both HNSW): pgvector 110ms p50 / 173MB vs
Qdrant 22ms p50; top-10 overlap 0.86 (quality ties, as predicted).

**Verdict:** gemma-512 (finer chunks) best answers; nomic ~equal quality at 5x speed;
keyword weak-but-usable (2.22) and 25x faster; hybrid + GraphRAG did NOT beat pure dense
(top-5 dense context already good; fusion/expansion diluted it — GraphRAG helps *recall*,
not focused synthesis). pgvector sufficient at this scale. Caveat: 9 queries + single judge
= directional, not statistically tight.
