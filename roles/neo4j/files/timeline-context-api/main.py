from __future__ import annotations

import os
import re
from fastapi import FastAPI, Header, HTTPException
from neo4j import AsyncGraphDatabase

app = FastAPI()

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASS = os.environ["NEO4J_PASSWORD"]
API_KEY = os.environ["TIMELINE_API_KEY"]

driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

SKIP_PREFIXES = ("<", "Review this change", "[Context:", "Caveat:")

# Lines matching any of these are dropped before they can reach the public
# chat widget's LLM. This blob spans ALL projects (incl. private repos), so
# this is the last guard against a secret/host in a commit subject or session
# title surfacing in a public answer. High-signal patterns; extend as needed.
_DENY = [
    re.compile(r"AKIA[0-9A-Z]{16}"),                       # AWS access key id
    re.compile(r"ASIA[0-9A-Z]{16}"),                       # AWS temp key id
    re.compile(r"(?i)\b[\w-]*(password|passwd|pwd|secret|token|api[_-]?key|apikey|"
               r"access[_-]?key|bearer|credential|client[_-]?secret|private[_-]?key)\b\s*[:=]"),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"(?i)\b[\w./-]+\.pem\b"),                  # key/cert filenames
    re.compile(r"\b(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),         # private/loopback IPv4
    re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
    re.compile(r"(?i)xox[baprs]-[0-9A-Za-z-]{8,}"),        # slack tokens
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),             # github tokens
    # --- value-shape patterns (added 2026-08-11) -------------------------------
    # The keyword rules above only fire on `NAME=value` / `NAME: value` forms, so a
    # BARE pasted credential sailed straight through. An audit of the corpus's 41
    # unrotated credentials found ~31 of them were shapes nothing here matched.
    re.compile(r"sk-ant-[0-9A-Za-z_-]{20,}"),              # anthropic
    re.compile(r"sk-proj-[0-9A-Za-z_-]{20,}"),             # openai project keys
    re.compile(r"\bsk-[0-9A-Za-z]{20,}"),                  # openai / litellm
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),               # google api keys
    re.compile(r"\b\d{8,10}:AA[0-9A-Za-z_-]{30,}"),        # telegram bot tokens
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@]+:[^\s/@]+@"),  # creds in a URI
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),  # JWTs
]


# TOPIC-level deny, separate from the value-shape rules above. _DENY catches
# credential *values* and `NAME=value` assignments; this catches lines that merely
# DISCUSS security posture. Added 2026-08-11 after a scan of the live payload found
# two commit subjects on the public endpoint — one about a "salt key for credential
# encryption", one naming GRAFANA_URL/USER/PASSWORD env vars. No credential leaked,
# but describing where secrets live is free reconnaissance. Applied to commit
# subjects and, belt-and-braces, to summaries at serve time.
_TOPIC_DENY = re.compile(
    r"(?i)\b(password|passwd|secret|credential|vault|salt[ _-]?key|api[ _-]?key|token|"
    r"rotate|rotation|revoke|leaked?|exposed|breach|xss|csrf|vulnerab|exploit|"
    r"private[ _-]?key|ssh[ _-]?key)\b"
)


def _is_sensitive(text: str) -> bool:
    return any(p.search(text) for p in _DENY)


def _is_sensitive_topic(text: str) -> bool:
    """True if the text merely TALKS about secrets/security, even with no value in it."""
    return _is_sensitive(text) or bool(_TOPIC_DENY.search(text))


# NOTE: the title is used only as a "this session was substantive" FILTER — it is
# deliberately NOT returned. Session titles are first_user_msg[:200] from
# ingest-sessions.py, i.e. RAW USER PROMPTS. This blob is appended to a public chat
# widget's system prompt and sent to a third-party LLM on EVERY request, so emitting
# titles published verbatim prompts (and, since ~21 credential hits in the corpus came
# from user pastes, would eventually publish a pasted secret). Project name + date
# carries the "what am I working on lately" signal with none of that risk.
# Do not add s.title back to the RETURN.
SESSIONS_QUERY = """
MATCH (p:Project)-[:HAS_SESSION]->(s:Session)
WHERE s.title IS NOT NULL AND size(s.title) > 20
RETURN p.display_name AS project, s.started_at AS date
ORDER BY s.started_at DESC
LIMIT 60
"""

# Authored, per-session summaries — the good substrate. `visibility` defaults to
# 'private' in sessions.session_summaries and a row only becomes 'public' when BOTH
# the summarising model and a local deny-list agreed it was safe. This query must
# ALWAYS filter on summary_visibility = 'public'; dropping that filter would publish
# summaries of security work. If no public summaries exist yet the endpoint falls
# back to the project+date block, which is safe but thin.
SUMMARIES_QUERY = """
MATCH (p:Project)-[:HAS_SESSION]->(s:Session)
WHERE s.summary_visibility = 'public' AND s.summary IS NOT NULL AND s.summary <> ''
RETURN p.display_name AS project, s.summary AS summary, s.started_at AS date
ORDER BY s.started_at DESC
LIMIT 25
"""

COMMITS_QUERY = """
MATCH (p:Project)-[:HAS_SESSION]->(sess:Session)-[:PRODUCED_COMMIT]->(c:Commit)
RETURN p.display_name AS project, c.message AS message, c.committed_at AS date
ORDER BY c.committed_at DESC
LIMIT 20
"""


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/context")
async def get_context(x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with driver.session() as db_session:
        summaries_result = await db_session.run(SUMMARIES_QUERY)
        raw_summaries = await summaries_result.data()

        sessions_result = await db_session.run(SESSIONS_QUERY)
        raw_sessions = await sessions_result.data()

        commits_result = await db_session.run(COMMITS_QUERY)
        raw_commits = await commits_result.data()

    lines: list[str] = ["=== RECENT ACTIVITY (live from timeline graph) ===\n"]

    # Prefer authored summaries. They describe what was ACHIEVED rather than what was
    # asked, and unlike the old title field they cannot contain a pasted credential,
    # because they are written rather than excerpted.
    emitted_summaries = 0
    if raw_summaries:
        lines.append("## What I've been working on (recent sessions):")
        seen: set[str] = set()
        for s in raw_summaries:
            summary = (s.get("summary") or "").strip()
            project = (s.get("project") or "misc").strip()
            if not summary or summary in seen:
                continue
            # belt and braces: the deny-list runs again at serve time, so a summary
            # that slipped through generation still cannot reach the public endpoint.
            if _is_sensitive_topic(summary) or _is_sensitive(project):
                continue
            seen.add(summary)
            date = str(s.get("date", ""))[:10]
            lines.append(f"- [{date}] ({project[:60]}): {summary[:220]}")
            emitted_summaries += 1
            if emitted_summaries >= 15:
                break
        lines.append("")

    # Fallback / supplement: project + date only. Never emits session titles, which
    # are raw user prompts. Kept unconditionally so the blob is never empty.
    lines.append("## Recent project activity (by project):")
    seen_days: set[tuple[str, str]] = set()
    count = 0
    for s in raw_sessions:
        date = str(s.get("date", ""))[:10]
        project = (s.get("project") or "misc").strip()
        # project names are directory names, but filter them anyway — cheap, and this
        # blob reaches a public endpoint.
        if not project or _is_sensitive(project):
            continue
        key = (date, project)
        if key in seen_days:
            continue
        seen_days.add(key)
        lines.append(f"- [{date}] {project[:60]}")
        count += 1
        if count >= 20:
            break

    lines.append("\n## What I've shipped recently (git commits):")
    for c in raw_commits:
        first_line = (c.get("message") or "").split("\n")[0][:120].strip()
        if not first_line:
            continue
        if any(first_line.startswith(p) for p in SKIP_PREFIXES):
            continue
        if _is_sensitive_topic(first_line):
            continue
        date = str(c.get("date", ""))[:10]
        project = c.get("project") or "misc"
        lines.append(f"- [{date}] ({project}): {first_line}")

    return {"context": "\n".join(lines)}
