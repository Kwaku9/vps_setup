# Trajectory Learning — Speaker Notes

Evidence date: 2026-10-02. Implementation commit: 74e0d75.

## 01 — Your sessions become a curriculum.

A closed-loop learning pipeline for the workstation and VPS.

The purpose is to turn operational experience into repeatable model behavior. Real sessions show how work was attempted, which tools were available, what the environment returned, and whether the task succeeded. The pipeline preserves that evidence, curates training examples, and prepares separate local and cloud candidates. The software has been implemented and tested, but no student model has yet been trained or deployed. This deck describes the implementation committed as 74e0d75, validated on October 2, 2026.

Source: `README.md · VALIDATION.md`

## 02 — Operational knowledge should survive the session.

Today’s troubleshooting can become tomorrow’s reliable procedure.

The project connects two complementary mechanisms. Retrieval provides relevant facts and prior evidence at inference time. Fine-tuning changes the student model’s habits: selecting tools, respecting schemas, interpreting results, and completing operational tasks. A transcript is not automatically a good lesson. The curation pipeline must separate useful behavior from failed actions, sensitive material, and unsupported claims. The goal is continuity across sessions without manually re-teaching every workflow.

Source: `README.md: purpose and architecture`

## 03 — The goal is a more capable systems operator.

These are intended benefits; improvement has not yet been measured.

A useful student model should know when to inspect before acting, select the right tool schema, connect results to the original request, and recognize uncertainty or failed execution. These benefits remain goals until a trained checkpoint is compared against a baseline on representative tasks. This pipeline does not itself grant administrative permissions or define the inference-layer authorization policy. Those remain responsibilities of the surrounding runtime.

Source: `README.md · INFERENCE-HANDOFF.md`

## 04 — Memory, learned behavior, and tools have different jobs.

Teach stable procedures. Retrieve changing facts. Observe the live system.

It is unrealistic to expect a fine-tuned checkpoint to know everything about systems that keep changing. Credentials, current ports, installed versions, and service state belong in current context and authorized tools, not in model weights. Existing session-recall and neo4j-sessions MCP servers continue to expose institutional knowledge. The pipeline adds evidence-linked learning records and supports recall; production connectivity to the existing memory environment has not been exercised.

Source: `integrations.py · README.md`

## 05 — Two student models share evidence, not release decisions.

The local and cloud targets have independent job histories and gates.

Both configured targets consume curated trajectories, but each reserves its own training hashes, trains its own adapter, and must pass its own evaluation gate. Model revisions are pinned in config.toml, making the exact base reproducible. Gemma is the requested small local target; Qwen is the larger cloud target. Ollama is the selected local engine. The inference layer being developed in the separate nucybersec mailkit session is an integration boundary, not something this project replaces.

Source: `config.toml · jobs.py · INFERENCE-HANDOFF.md`

## 06 — The loop closes only after a candidate proves itself.

Every deployed improvement must produce new observable evidence.

The full intended loop is capture, curation, training, evaluation, controlled release, and renewed capture. Failed or incomplete records are retained outside the training set. A model candidate does not become active just because training succeeded. It must be served as a candidate and evaluated first. At present the code paths exist, but production connections, training, and auto-promotion are disabled. This is a built pipeline awaiting live integration and model validation.

Source: `README.md · config.toml`

## 07 — Three input paths become one trace format.

New runtime capture can preserve evidence that old logs never recorded.

The importer supports Claude, Codex, and canonical runtime traces. It waits for settled files before ingestion and fingerprints source content to avoid repeatedly processing unchanged data. Historical logs often lack tool schemas or complete terminal outcomes. The normalizer flags these deficiencies rather than inventing missing evidence. Internal analysis and private thinking records are excluded from training. If synthesized tools change, start a new trace segment linked to the same session group.

Source: `capture.py · normalize.py · store.py`

## 08 — A trajectory connects an action to its observed result.

Illustrative example: identify the process listening on port 8080.

This is a synthetic teaching example, not a copied private session. The canonical record links a tool call to its result with a call ID and preserves the tool schema, arguments, execution feedback, and final answer. A successful exit code is useful evidence but does not establish that the response answered the user’s request. Independent verification is still required. Source metadata and hashes let a future training example be traced back to its evidence.

Source: `capture.py · normalize.py`

## 09 — Preserve raw evidence before transforming it.

Capture failures too; curation decides what can teach the student.

Two storage paths preserve provenance. The runtime interceptor writes append-only events with locking and fsync. Historical ingestion stores immutable whole-file snapshots before parsing, including malformed or incomplete bytes. Raw session archives can contain sensitive information and remain private. They are not included in this presentation or automatically exported for training. The local SQLite queue uses WAL and immutable trace and decision records. Latest source snapshots are selected for dataset construction.

Source: `capture.py · store.py`

## 10 — A useful trace must pass more than a success flag.

Deterministic checks remove unreliable or unsafe training material.

The implementation is conservative: a failed tool call can quarantine a trace even if its overall error ratio is below the configured 0.25 threshold. Schema repairs are not silently accepted as good tool behavior. Credential redaction is not a license to train on altered commands; such records require review. Quarantine is an auditable disposition, not deletion. Source outcomes and model self-reports alone are insufficient to accept a training example.

Source: `curate.py · config.toml`

## 11 — Independent evidence decides whether the task was solved.

An exit code of zero does not prove task completion.

The judge can call an OpenAI-compatible endpoint when configured. Its output must meet all required quality conditions and the confidence threshold. The alternative verify command accepts trusted human-review or sandbox-test evidence tied to the exact trace and record hash, preventing a review for one record from approving a different record. The credibility of manually supplied evidence remains a trust boundary; the pipeline does not independently execute the referenced URI. The critic is disabled by default.

Source: `judge.py · cli.py`

## 12 — The first audit found zero training-ready sessions.

Ten real local logs: five Claude sessions and five Codex sessions.

These results are an audit of a ten-session sample, not a representative estimate of every session’s quality. They show why copying historical logs directly into SFT would be risky. The pipeline preserved the source evidence while withholding records that failed its requirements. The practical next step is richer runtime instrumentation and explicit outcome verification, not relaxing quality controls to reach the training threshold. Audit data remains in private ignored state.

Source: `VALIDATION.md: real local-session sample`

## 13 — Failures remain evidence, not automatic training pairs.

A clean continuation must still be supported by the same task context.

The initial project proposal included pruning dead ends and automatically creating DPO pairs. The implemented pipeline does not automatically rewrite, replay, or generate preference pairs. Removing failed steps can remove information that made a later action valid. Likewise, a failed and successful command from different system states is not necessarily a valid chosen/rejected pair. These are extension points that require stronger evidence and an authorized sandbox. Current training work is centered on verified SFT.

Source: `README.md: limitations · curate.py`

## 14 — Each store has a distinct responsibility.

The new learning records complement your existing institutional memory.

PostgreSQL and Neo4j are not interchangeable replicas of every byte. PostgreSQL provides transactional learning metadata and an outbox; Neo4j provides traversable relationships into existing session knowledge. The local SQLite queue allows capture and dataset work to progress separately from remote integration. Migrations add a learning schema rather than replacing existing recall data. These integrations passed disposable-database tests, but production VPS migration and connection remain untested.

Source: `schema.sql · integrations.py · store.py`

## 15 — An outbox bridges PostgreSQL and the graph.

A retryable handoff keeps graph delivery separate from capture.

The transactional outbox avoids trying to coordinate a single cross-database transaction. Learning data and the delivery request are committed in PostgreSQL together. A synchronizer writes the graph using stable identities and MERGE, then marks delivery successful. If the process stops after the graph write but before acknowledgement, retrying should not duplicate the graph entities. Repeat-safe writes, migration behavior, and provenance links were exercised against PostgreSQL 16 and Neo4j 5 in disposable containers.

Source: `integrations.py · tests/integration_databases.py`

## 16 — A lesson needs evidence, scope, and an expiry policy.

Retrieve current knowledge instead of freezing every fact into weights.

The lesson command records evidence-linked operational knowledge with scope, time, expiration, and supersession. Recall can combine existing recall.chunks embeddings, graph topics, and nonexpired verified lessons. The existing embeddinggemma path expects 768-dimensional vectors. Inference-time consumers must still retrieve and use this context. The model should learn the habit of checking current facts rather than treating a remembered service location or configuration as timeless truth. Live recall-vector retrieval has not yet been exercised against the VPS.

Source: `integrations.py · cli.py`

## 17 — Versioned datasets preserve diversity and lineage.

The split happens by session group, not by individual message.

The default validation fraction is 10 percent. Grouping helps prevent related trajectories from appearing in both training and validation. Optional semantic deduplication uses cosine similarity with a default threshold of 0.96; it is disabled until an endpoint is set. This is not a guarantee against every form of data leakage. The benchmark contamination guard checks exact prompt prefixes, so semantic leakage still requires dataset review and benchmark discipline.

Source: `dataset.py · config.toml`

## 18 — Only assistant output contributes to training loss.

Inspect the difference between the model’s inputs and its learning targets.

The model receives the conversation as context, but labels for system text, user text, tool results, and padding are set to -100. Assistant tool-call syntax, arguments, and final public responses contribute to loss. Private reasoning is excluded. The on-slide control highlights which role is supervised; it is an explanatory visualization, not a live tokenizer. The actual preprocessor uses the native model template and rejects unsupported or unsafe masking conditions. It does not silently truncate long samples.

Source: `masking.py · templates.py`

## 19 — Native templates prevent subtle tool-output leakage.

Gemma and Qwen do not share one generic ChatML formatter.

These token counts belong to controlled fixtures, not the training dataset. Both official tokenizers were tested at the pinned revisions with Transformers 5.18.0 and TRL 1.14.1. Native rendered bytes were preserved while annotating supervised regions. Additional checks covered Unicode, parallel tool outputs, and multi-turn continuations. Gemma’s template can render tool output inside an assistant branch, so masking entire assistant-formatted blocks would incorrectly supervise environment text. No model weights were downloaded for these checks.

Source: `VALIDATION.md · tests/native_tokenizers.py`

## 20 — QLoRA adapts the model with a small trainable layer.

The recipe is configured; GPU training has not yet run.

QLoRA keeps quantized base weights while learning low-rank adapter parameters. This makes adaptation more practical than updating every parameter, but actual VRAM needs depend on architecture, optimizer state, sequence length, and hardware. The training implementation uses the multimodal model class for the selected bases while training text/tool trajectories and targeting language projections. No training time, memory requirement, or quality improvement is claimed: the available environment did not expose a working NVIDIA device.

Source: `train.py · config.toml`

## 21 — Training starts from enough new, verified work.

Each model gets its own queue and data reservation.

The worker creates work only when prerequisites are satisfied for that target. Running and successful jobs reserve training hashes to avoid repeatedly consuming the same examples as new work. Separate targets can learn from the same curriculum independently. Process locks prevent competing workers from duplicating active work. A process crash can leave a job marked running; operator recovery is currently required. Supplied user-systemd units poll capture every minute and the worker every five minutes, but are not installed.

Source: `jobs.py · config.toml · deploy/`

## 22 — Release gates compare the candidate with its baseline.

Training success alone never proves operational improvement.

The same benchmark runs against baseline and candidate endpoints. Reports are bound to the job, artifact, suite, and case identities. Required categories are tool use, operations, instruction following, and safety. Every category needs at least five cases, and the entire suite needs at least fifty. Category scores must meet 90 percent, regressions cannot exceed two percentage points, and safety failures must be zero. The bundled eight-case example is intentionally insufficient and blocks the default gate. These settings are release criteria, not observed model scores.

Source: `evaluate.py · config.toml`

## 23 — Ollama receives a candidate before the active model changes.

The local release path carries artifact identity and rollback state.

The export helper uses a configured llama.cpp installation for conversion and quantization. Real architecture support, conversion, and memory requirements still need validation. The Ollama client uploads the artifact, records the resulting engine digest, and uses dedicated candidate, active, and previous tags. Promotion is followed by identity and generation health checks, with rollback on failure. The lifecycle was tested against a simulated API, not a live daemon. The Qwen cloud release transport remains an integration task.

Source: `export_gguf.py · ollama.py · INFERENCE-HANDOFF.md`

## 24 — One verified fix can improve both memory and training.

Illustrative future run: a service is not listening on its expected port.

This is a hypothetical completed loop, not a live incident the pipeline has handled. The runtime should first obtain current system context, inspect the state, carry out only authorized actions, and verify the outcome. The learning pipeline then captures and curates that session. A scoped lesson can become retrievable earlier than a new model release; training waits for the batch threshold. This separates immediate institutional memory from slower model adaptation while using the same underlying evidence.

Source: `README.md · integrations.py · jobs.py`

## 25 — The foundation has passed meaningful implementation checks.

Evidence as recorded on October 2, 2026.

The behavioral tests also used real subprocess fixtures for training-stage orchestration, not a real GPU training run. Database tests covered repeated migrations, repeat-safe writes, immutable evidence, lessons, and the graph outbox. Tokenizer checks established masking behavior without downloading model weights. Ollama tag lifecycle tests used a simulated API. This evidence supports the implementation’s mechanics, but does not establish a better model, a working production deployment, or the reliability of remote integration.

Source: `VALIDATION.md`

## 26 — Live operation needs integration and model validation.

The remaining work is concrete and intentionally gated.

Training, external critic use, database integration, and auto-promotion are disabled in checked-in configuration. Additional operational work includes archive retention planning, crash recovery for stale running jobs, and installing capture/worker timers when ready. LM Studio can be added by the inference-layer project if useful, but it has not been integrated or tested here. The next milestone should be a controlled end-to-end run with a small approved dataset and a candidate endpoint, followed by evaluation rather than immediate promotion.

Source: `VALIDATION.md · config.toml · INFERENCE-HANDOFF.md`

## 27 — Measure better work, not just a lower training loss.

Proposed scorecard for the first trained candidates.

These are proposed metrics, not measurements already produced by a trained system. Compare the same tasks and context against the selected baseline. Track local and cloud targets separately because latency, cost, and capacity differ. Model-quality gains should be accompanied by operational checks: does the model retrieve current facts, avoid unsupported claims, and stop or recover appropriately when tools fail? Lower loss can coexist with worse operational behavior, which is why the release benchmark and live feedback loop are necessary.

Source: `Proposed measurement plan · evaluate.py`

## 28 — The product is a repeatable learning process.

Verified experience becomes durable operational capability.

The lasting value is the process, not one adapter. Capture creates evidence; institutional memory keeps knowledge accessible; curation selects trustworthy examples; fine-tuning adapts behavior; and evaluation controls release. The two student models can evolve independently while sharing the same evidence discipline. The code is committed locally as 74e0d75. No GPU-trained checkpoint or production promotion has occurred. The following appendix slides map the components, operating commands, default gates, and inference-layer contract.

Source: `README.md · VALIDATION.md`

## 29 — The code follows the lifecycle of the evidence.

Use these entry points to inspect or extend the implementation.

All source paths are relative to tools/trajectory-pipeline/trajectory_pipeline unless otherwise specified. capture.py provides the runtime interception API. store.py provides durable local tracking and raw snapshots. integrations.py connects sanitized learning records to external memory. Configuration lives in config.toml, operator documentation in README.md, and current verification evidence in VALIDATION.md. The provided deployment units live under deploy and are not installed.

Source: `trajectory_pipeline/ · deploy/`

## 30 — The CLI exposes each stage for inspection and control.

Command groups make the automated loop observable.

These are subcommand names, not a blind execution script. Read the README for the configured CLI invocation and required arguments. ingest records sources, curate evaluates them, verify attaches independent evidence, and export writes a versioned dataset. cycle and watch support recurring capture/curation; worker advances eligible training jobs. migrate and sync manage the additive learning integrations. recall reads institutional context; lesson records scoped evidence-backed knowledge. Configure endpoints and credentials through the documented environment-variable contract.

Source: `cli.py · README.md`

## 31 — Defaults favor evidence before automation.

Thresholds are configurable; these are the committed starting values.

Defaults should be reviewed against the actual workload and benchmark. The error-ratio threshold does not mean every trace below 25 percent errors is accepted: failed calls are conservatively quarantined. Semantic embeddings require an endpoint before they are active. A queue threshold is based on new unique accepted work for each model, not raw log count. The intentionally undersized example suite prevents an accidental default release before representative evaluations exist.

Source: `config.toml · curate.py · jobs.py`

## 32 — The inference layer consumes tested artifacts and current context.

A clean boundary with the parallel nucybersec mailkit work.

The local adapter contract uses dedicated tags under trajectory-gemma-admin: candidate-JOBPREFIX, active, and previous-JOBPREFIX. The normal local endpoint is the configured Ollama service; no deployment target is assumed for the Qwen cloud model. LM Studio could participate as an optional consumer or comparison endpoint after its actual model and tool-call behavior are validated. The pipeline does not replace inference routing, current-context assembly, or tool authorization. Those remain part of the parallel inference stack.

Source: `INFERENCE-HANDOFF.md`
