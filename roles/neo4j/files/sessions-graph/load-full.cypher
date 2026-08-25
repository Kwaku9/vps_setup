// =============================================================================
// Sessions subgraph — idempotent FULL loader (UPSERT). Safe to re-run forever.
// MERGE on the natural keys (which already have uniqueness constraints) so re-runs
// never duplicate. Large loads batched via apoc.periodic.iterate. Run AFTER export-full.sh.
//
// NOTE: the initial load created uniqueness constraints on pg_id (a load-counter) and
// plain indexes on ToolType.name / File.path. We therefore (a) do NOT write pg_id
// (would violate that constraint), and (b) do NOT redefine those indexed properties as
// constraints. We only add the two missing keys we rely on.
// =============================================================================

CREATE CONSTRAINT sess_proj_path IF NOT EXISTS FOR (p:Project)  REQUIRE p.path IS UNIQUE;
CREATE CONSTRAINT sess_sess_uuid IF NOT EXISTS FOR (s:Session)  REQUIRE s.uuid IS UNIQUE;
CREATE CONSTRAINT sess_msg_uuid  IF NOT EXISTS FOR (m:Message)  REQUIRE m.uuid IS UNIQUE;
CREATE CONSTRAINT sess_tool_id   IF NOT EXISTS FOR (t:ToolCall) REQUIRE t.tool_use_id IS UNIQUE;
CREATE CONSTRAINT sess_sub_id    IF NOT EXISTS FOR (s:Subagent) REQUIRE s.agent_id IS UNIQUE;
CREATE CONSTRAINT sg_artifact    IF NOT EXISTS FOR (a:Artifact) REQUIRE a.art_key IS UNIQUE;

// ---- Projects: AUTHORITATIVE full-refresh (MERGE on path) ----
// Project paths get merged/renamed upstream (e.g. the decode-bug backfill), so a
// purely additive MERGE would retain stale renamed project nodes (and poison the
// Codebase layer derived from them). Drop + reload so :Project mirrors Postgres.
MATCH (p:Project) DETACH DELETE p;
LOAD CSV WITH HEADERS FROM 'file:///sg_projects.csv' AS r
MERGE (p:Project {path: r.path}) SET p.display_name = r.display_name, p.source = r.source;

// ---- Sessions (+ Model/USED_MODEL/HAS_SESSION) ----
LOAD CSV WITH HEADERS FROM 'file:///sg_sessions.csv' AS r
MERGE (s:Session {uuid: r.session_uuid})
  SET s.title=r.title, s.source=r.source, s.model=r.model, s.status=r.status, s.category=r.category,
      s.started_at=r.started_at, s.ended_at=r.ended_at, s.duration_seconds=toInteger(r.duration_seconds),
      s.total_messages=toInteger(r.total_messages), s.total_turns=toInteger(r.total_turns),
      s.total_tool_calls=toInteger(r.total_tool_calls), s.git_branch=r.git_branch, s.cli_version=r.cli_version,
      // Authored summary + its visibility. The public chat widget reads ONLY
      // summary_visibility='public'; default is 'private' (see session_summaries).
      s.summary=r.summary, s.summary_visibility=r.summary_visibility;

LOAD CSV WITH HEADERS FROM 'file:///sg_sessions.csv' AS r WITH r WHERE r.project_path <> ''
MATCH (p:Project {path: r.project_path}), (s:Session {uuid: r.session_uuid})
MERGE (p)-[:HAS_SESSION]->(s);

LOAD CSV WITH HEADERS FROM 'file:///sg_sessions.csv' AS r WITH r WHERE r.model <> ''
MATCH (s:Session {uuid: r.session_uuid}) MERGE (mo:Model {name: r.model}) MERGE (s)-[:USED_MODEL]->(mo);

// ---- Messages (+ HAS_MESSAGE) — batched ----
CALL apoc.periodic.iterate(
  "LOAD CSV WITH HEADERS FROM 'file:///sg_messages.csv' AS r RETURN r",
  "MERGE (m:Message {uuid: r.uuid})
     SET m.type=r.type, m.role=r.role, m.is_sidechain=toBoolean(r.is_sidechain),
         m.timestamp=r.timestamp, m.sequence_num=toInteger(r.sequence_num), m.content_preview=r.content_preview
   WITH m, r MATCH (s:Session {uuid: r.session_uuid}) MERGE (s)-[:HAS_MESSAGE]->(m)",
  {batchSize:5000, parallel:false}) YIELD total, failedOperations RETURN 'messages' AS step, total, failedOperations;

// ---- PARENT_OF (threading) — batched ----
CALL apoc.periodic.iterate(
  "LOAD CSV WITH HEADERS FROM 'file:///sg_messages.csv' AS r WITH r WHERE r.parent_uuid <> '' RETURN r",
  "MATCH (c:Message {uuid: r.uuid}) MATCH (p:Message {uuid: r.parent_uuid}) MERGE (p)-[:PARENT_OF]->(c)",
  {batchSize:5000, parallel:false}) YIELD total, failedOperations RETURN 'parent_of' AS step, total, failedOperations;

// ---- ToolCalls (+ USED_TOOL/ToolType/IS_TYPE) — batched ----
CALL apoc.periodic.iterate(
  "LOAD CSV WITH HEADERS FROM 'file:///sg_toolcalls.csv' AS r RETURN r",
  "MERGE (t:ToolCall {tool_use_id: r.tool_use_id})
     SET t.tool_name=r.tool_name, t.status=r.status, t.denial_reason=r.denial_reason, t.timestamp=r.timestamp, t.sequence_num=toInteger(r.sequence_num)
   WITH t, r MATCH (m:Message {uuid: r.message_uuid}) MERGE (m)-[:USED_TOOL]->(t)
   WITH t, r WHERE r.tool_name <> '' MERGE (tt:ToolType {name: r.tool_name}) MERGE (t)-[:IS_TYPE]->(tt)",
  {batchSize:5000, parallel:false}) YIELD total, failedOperations RETURN 'toolcalls' AS step, total, failedOperations;

// ---- Subagents (+ SPAWNED) ----
LOAD CSV WITH HEADERS FROM 'file:///sg_subagents.csv' AS r
MERGE (sa:Subagent {agent_id: r.agent_id})
  SET sa.agent_type=r.agent_type, sa.description=r.description, sa.total_messages=toInteger(r.total_messages)
WITH sa, r MATCH (s:Session {uuid: r.session_uuid}) MERGE (s)-[:SPAWNED]->(sa);

// ---- Artifacts: AUTHORITATIVE full-refresh (no reliable pre-existing key) ----
MATCH (a:Artifact) DETACH DELETE a;
CALL apoc.periodic.iterate(
  "LOAD CSV WITH HEADERS FROM 'file:///sg_artifacts.csv' AS r RETURN r",
  "MERGE (a:Artifact {art_key: r.art_key})
     SET a.file_path=r.file_path, a.action=r.action, a.language=r.language,
         a.size_bytes=toInteger(r.size_bytes), a.timestamp=r.timestamp, a.preview=r.preview
   WITH a, r MATCH (s:Session {uuid: r.session_uuid}) MERGE (s)-[:HAS_ARTIFACT]->(a)
   WITH a, r MERGE (f:File {path: r.file_path}) MERGE (a)-[:TOUCHES_FILE]->(f)
   WITH a, r WHERE r.tool_use_id <> '' MATCH (t:ToolCall {tool_use_id: r.tool_use_id}) MERGE (t)-[:PRODUCED]->(a)",
  {batchSize:2000, parallel:false}) YIELD total, failedOperations RETURN 'artifacts' AS step, total, failedOperations;

// ---- Repos + Commits ----
// Repo MERGEs on its existing pg_id key. Commits are AUTHORITATIVE (the initial
// load keyed them on pg_id, not the hash, so a hash-keyed MERGE would create a
// parallel set) -> drop + recreate keyed on sha. Deterministic => idempotent.
LOAD CSV WITH HEADERS FROM 'file:///sg_repos.csv' AS r
MERGE (rp:Repo {pg_id: toInteger(r.id)}) SET rp.repo_name=r.repo_name, rp.repo_path=r.repo_path, rp.default_branch=r.default_branch;

MATCH (c:Commit) DETACH DELETE c;
LOAD CSV WITH HEADERS FROM 'file:///sg_commits.csv' AS r
MERGE (c:Commit {sha: r.commit_hash})
  SET c.short_hash=r.short_hash, c.author=r.author, c.message=r.message,
      c.committed_at=r.committed_at, c.branch=r.branch, c.files_changed=toInteger(r.files_changed)
WITH c, r MATCH (rp:Repo {pg_id: toInteger(r.repo_id)}) MERGE (rp)-[:HAS_COMMIT]->(c)
WITH c, r WHERE r.session_uuid <> '' MATCH (s:Session {uuid: r.session_uuid}) MERGE (s)-[:PRODUCED_COMMIT]->(c);

// ---- NEXT (conversation ordering within each session) — derived, idempotent ----
CALL apoc.periodic.iterate(
  "MATCH (s:Session) RETURN s",
  "MATCH (s)-[:HAS_MESSAGE]->(m:Message) WITH m ORDER BY m.sequence_num WITH collect(m) AS ms
   UNWIND range(0, size(ms)-2) AS i WITH ms[i] AS a, ms[i+1] AS b WHERE a.sequence_num < b.sequence_num
   MERGE (a)-[:NEXT]->(b)",
  {batchSize:50, parallel:false}) YIELD total, failedOperations RETURN 'next' AS step, total, failedOperations;

// ---- Prune empty-shell Session nodes (zero messages) ----
// Mirrors the Postgres shell-prune: a Session with no messages is a stale shell
// (real sessions always have messages). Additive Session MERGE would otherwise
// retain sessions deleted upstream, so sweep them here. Self-maintaining.
MATCH (s:Session) WHERE NOT (s)-[:HAS_MESSAGE]->() DETACH DELETE s;

// ---- Codebase: cross-machine canonical identity (C) — derived, idempotent ----
// One :Codebase per repo/leaf-dir name (machine-independent: the same repo on
// VPS /workspace/... , Fedora /home/... and Windows C:\... shares one leaf name,
// which also equals the UNIQUE sessions.git_repos.repo_name). Each per-machine
// :Project links INSTANCE_OF its Codebase, so machine provenance is preserved and
// "what am I working on" rolls up across machines. Depends on canonical Project
// paths (run migration 001 first); otherwise leaf names are garbage.
CREATE CONSTRAINT cb_key IF NOT EXISTS FOR (cb:Codebase) REQUIRE cb.key IS UNIQUE;

// Authoritative: drop stale Codebase nodes (their keys derive from Project leaf
// names, which change when projects are merged/renamed) before rebuilding.
MATCH (cb:Codebase) DETACH DELETE cb;

MATCH (p:Project) WHERE p.path IS NOT NULL
WITH p, [x IN split(replace(p.path, '\\', '/'), '/') WHERE x <> ''] AS parts
WITH p, parts[-1] AS key WHERE key IS NOT NULL AND key <> ''
MERGE (cb:Codebase {key: key})
MERGE (p)-[:INSTANCE_OF]->(cb);

// Enrich + link to the real git repo where the name matches.
MATCH (cb:Codebase)
OPTIONAL MATCH (r:Repo {repo_name: cb.key})
SET cb.is_git_repo = (r IS NOT NULL), cb.default_branch = r.default_branch;

MATCH (cb:Codebase), (r:Repo {repo_name: cb.key})
MERGE (cb)-[:HAS_REPO]->(r);
