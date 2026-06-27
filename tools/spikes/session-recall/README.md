# Session Semantic Recall — Evaluation Harness (spike)

Throwaway harness: embeds all-time Claude Code sessions six ways and scores recall
against a human-approved gold set. Spec:
`docs/superpowers/specs/2026-06-25-session-semantic-recall-spike-design.md`.

## One-time setup
1. `podman build --network=enterprise_network -t spike-tools .`
2. `cp spike.env.example spike.env` and fill `PGPASSWORD` (vault `pg_session_ingest_password`)
   + `LITELLM_API_KEY` (vault `litellm_master_key`).
3. `./run.sh check.py` — prints the all-time session count (anchors gold-set sizing).
4. `podman exec -i postgres psql -U postgres -d enterprise < schema.sql`
5. `bash nomic-up.sh` — downloads the nomic GGUF and starts the `nomic-embed` container.

## Build the corpus (all-time, resumable)
```bash
for ds in useronly userasst; do
  ./run.sh embed_sessions.py --model gemma --dataset $ds
  ./run.sh embed_sessions.py --model nomic --dataset $ds
done
./run.sh -c "from db import connect; import kwsearch; kwsearch.populate(connect())"
```

## Build the gold set (adaptive)
- Pilot synthetic: `./run.sh gen_queries.py --batch-size 25` (approve/edit/reject each).
- Add your own (optional, anytime): `./run.sh add_query.py` — type a query, find the right
  session by project/date/title (session IDs shown) or paste a session_id. Tagged `source=manual`.
- Score: `./run.sh run_eval.py` — prints a board per source (`manual` separate from
  `synthetic-approved`) + a combined board. Restrict with `--source manual`.
- If methods are bunched within the noise, expand: `./run.sh gen_queries.py --batch-size 25 --seed 1`
  and re-score. Hard cap ~150 total. Stop early if one method clearly dominates.
- Reinforcement: `./run.sh run_eval.py --feedback` records relevance into `spike.eval_relevance`.

## Reading the scoreboard
One board per `source`; six rows each (model/dataset), sorted by **R@3** (correct session
in the top 3). Your `manual` queries are the most realistic test — weight that board. Pick
the method with the best R@3/MRR; use the `ms` (query cost) column as the tiebreaker.
Keyword winning is a valid, cheap outcome. See the spec's "Success criteria / verdict".

## Teardown
`bash teardown.sh` — drops `spike` schema, removes the container + image.
