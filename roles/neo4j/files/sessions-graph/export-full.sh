#!/bin/sh
# Export the FULL session graph from Postgres as CSVs into Neo4j's import dir.
# SQL JOINs resolve integer FKs into the natural keys the graph MERGEs on
# (session_uuid, message uuid, tool_use_id, agent_id, project path, commit_hash),
# so the load Cypher is a pure idempotent UPSERT. Free-text fields are sanitised
# with clean_text() (strip newline/CR/tab/double-quote) so they never break CSV
# parsing; double-quote is referenced as chr(34) to avoid shell-quoting issues.
set -eu
IMPORT_DIR="${1:-/opt/podman-data/neo4j/import}"

# clean_text(expr, maxlen): translate \n\r\t and " to spaces, then truncate.
# Used inline below.

q() {  # $1=outfile  $2=SQL
  podman exec postgres sh -c 'PGPASSWORD=$POSTGRES_PASSWORD psql -U postgres -d enterprise --csv -c "'"$2"'"' > "$IMPORT_DIR/$1"
}

q sg_projects.csv \
  "SELECT id, coalesce(project_path,'') AS path, translate(coalesce(display_name,''), E'\n\r\t' || chr(34), '    ') AS display_name, coalesce(source,'') AS source FROM sessions.projects WHERE project_path IS NOT NULL"

q sg_sessions.csv \
  "SELECT se.session_uuid, se.id AS pg_id, se.project_id, coalesce(pr.project_path,'') AS project_path, translate(left(coalesce(se.title,''),400), E'\n\r\t' || chr(34), '    ') AS title, coalesce(se.source,'') AS source, coalesce(se.model,'') AS model, coalesce(se.status,'') AS status, coalesce(se.session_category,'') AS category, coalesce(se.started_at::text,'') AS started_at, coalesce(se.ended_at::text,'') AS ended_at, coalesce(se.duration_seconds,0) AS duration_seconds, coalesce(se.total_messages,0) AS total_messages, coalesce(se.total_turns,0) AS total_turns, coalesce(se.total_tool_calls,0) AS total_tool_calls, coalesce(se.git_branch,'') AS git_branch, coalesce(se.cli_version,'') AS cli_version, translate(left(coalesce(ss.one_liner,''),300), E'\n\r\t' || chr(34), '    ') AS summary, coalesce(ss.visibility,'private') AS summary_visibility FROM sessions.sessions se LEFT JOIN sessions.projects pr ON pr.id = se.project_id LEFT JOIN sessions.session_summaries ss ON ss.session_uuid = se.session_uuid WHERE se.session_uuid IS NOT NULL"

q sg_messages.csv \
  "SELECT m.uuid, m.id AS pg_id, s.session_uuid, coalesce(m.parent_uuid::text,'') AS parent_uuid, coalesce(m.type,'') AS type, coalesce(m.role,'') AS role, coalesce(m.is_sidechain,false) AS is_sidechain, coalesce(m.timestamp::text,'') AS timestamp, coalesce(m.sequence_num,0) AS sequence_num, translate(left(coalesce(m.content_text,''),300), E'\n\r\t' || chr(34) || chr(92), '     ') AS content_preview FROM sessions.messages m JOIN sessions.sessions s ON m.session_id=s.id WHERE m.uuid IS NOT NULL"

q sg_toolcalls.csv \
  "SELECT tc.tool_use_id, tc.id AS pg_id, m.uuid AS message_uuid, coalesce(tc.tool_name,'') AS tool_name, coalesce(tc.status,'') AS status, coalesce(tc.denial_reason,'') AS denial_reason, coalesce(tc.timestamp::text,'') AS timestamp, coalesce(tc.sequence_num,0) AS sequence_num FROM sessions.tool_calls tc JOIN sessions.messages m ON tc.message_id=m.id WHERE tc.tool_use_id IS NOT NULL"

q sg_subagents.csv \
  "SELECT sa.agent_id, s.session_uuid, coalesce(sa.agent_type,'') AS agent_type, translate(left(coalesce(sa.description,''),300), E'\n\r\t' || chr(34), '    ') AS description, coalesce(sa.total_messages,0) AS total_messages FROM sessions.subagents sa JOIN sessions.sessions s ON sa.parent_session_id=s.id WHERE sa.agent_id IS NOT NULL"

q sg_artifacts.csv \
  "SELECT s.session_uuid, coalesce(tc.tool_use_id,'') AS tool_use_id, translate(coalesce(a.file_path,''), E'\n\r\t' || chr(34), '    ') AS file_path, coalesce(a.action,'') AS action, coalesce(a.language,'') AS language, coalesce(a.size_bytes,0) AS size_bytes, coalesce(a.timestamp::text,'') AS timestamp, translate(left(coalesce(a.content_preview,''),300), E'\n\r\t' || chr(34) || chr(92), '     ') AS preview, md5(s.session_uuid||'|'||coalesce(a.file_path,'')||'|'||coalesce(a.timestamp::text,'')||'|'||coalesce(a.action,'')) AS art_key FROM sessions.artifacts a JOIN sessions.sessions s ON a.session_id=s.id LEFT JOIN sessions.tool_calls tc ON a.tool_call_id=tc.id WHERE a.file_path IS NOT NULL"

q sg_repos.csv \
  "SELECT id, coalesce(repo_name,'') AS repo_name, coalesce(repo_path_vps,'') AS repo_path, coalesce(default_branch,'') AS default_branch, project_id FROM sessions.git_repos"

q sg_commits.csv \
  "SELECT c.commit_hash, c.repo_id, coalesce(s.session_uuid,'') AS session_uuid, coalesce(c.short_hash,'') AS short_hash, translate(coalesce(c.author_name,''), E'\n\r\t' || chr(34), '    ') AS author, translate(left(coalesce(c.commit_message,''),300), E'\n\r\t' || chr(34), '    ') AS message, coalesce(c.committed_at::text,'') AS committed_at, coalesce(c.branch,'') AS branch, coalesce(c.files_changed,0) AS files_changed FROM sessions.git_commits c LEFT JOIN sessions.sessions s ON c.session_id=s.id WHERE c.commit_hash IS NOT NULL"

echo "exported $(ls -1 "$IMPORT_DIR"/sg_*.csv 2>/dev/null | wc -l) CSV files to $IMPORT_DIR"
