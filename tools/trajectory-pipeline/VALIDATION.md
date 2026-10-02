# Validation — 2026-10-02

## Passed

- **36 unit/behavior tests**, run with Python 3.11.15. Includes real subprocess
  training-stage fixtures, two-target queue idempotency, dataset lineage, redaction,
  tool schema validation, native mask invariants, regression rejection, release
  rollback, and Ollama model-tag lifecycle using a simulated API.
- **Real PostgreSQL 16 + Neo4j 5 integration**, in disposable loopback-only Podman
  containers. Repeated migrations, repeat-safe writes, transactional graph outbox,
  graph provenance, immutable evidence triggers, and lesson inserts passed.
  The test containers and their anonymous volumes were removed afterward.
- **Official native tokenizers**, Transformers 5.18.0 / TRL 1.14.1:

| Model | Revision | Fixture tokens | Assistant loss tokens |
| --- | --- | ---: | ---: |
| Gemma 4 E4B IT | `ee0ef6023621cff504d758262d4e04895a5af4a2` | 103 | 25 |
| Qwen 3.8 27B | `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` | 340 | 50 |

  Mask annotations preserved native rendered bytes. Tool results, system prompts,
  and user prompts were excluded from loss. Parallel tool outputs, Unicode, and
  multi-turn continuations also passed. Model weights were not downloaded.
- **Real local-session sample:** five Claude logs and five Codex logs captured into
  private, ignored `state/`. Nine were quarantined; one awaited independent
  verification. Findings included missing schemas, incomplete conversations,
  failed calls, repeated actions, and credential-like content. No sample was
  accepted or used to train. Raw archive and audit outputs remain private.
- Python compilation, configuration parsing, installed CLI status/idle-worker
  smoke tests, and whitespace checks passed.

## Not yet exercised

- QLoRA on a GPU, model-quality improvements, memory requirements, or training time.
  The current environment did not expose a working NVIDIA device.
- Adapter merge, actual Gemma GGUF conversion/quantization, live Ollama import and
  reload, or LM Studio execution. Ollama is the selected local engine; no daemon
  or CLI was available to this environment for a live engine test.
- Production VPS connection/migration, live recall-vector retrieval, or existing
  memory MCP network connectivity. Integration tests used disposable databases.
- External critic/embedding calls and cloud GPU transport/provider deployment.
- Installation of capture timers or connection to the runtime synthesis dispatcher.

Training and auto-promotion remain disabled in the checked-in configuration. The
regression suite must be expanded beyond its eight illustrative cases before the
default release gate will permit a job. See `INFERENCE-HANDOFF.md` for the contract
with the parallel inference-layer work.
