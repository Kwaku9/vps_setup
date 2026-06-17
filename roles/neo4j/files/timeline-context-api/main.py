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
]


def _is_sensitive(text: str) -> bool:
    return any(p.search(text) for p in _DENY)


def _clean_title(title: str) -> str | None:
    t = title.strip()
    if any(t.startswith(p) for p in SKIP_PREFIXES):
        return None
    if _is_sensitive(t):
        return None
    return t[:160]


SESSIONS_QUERY = """
MATCH (p:Project)-[:HAS_SESSION]->(s:Session)
WHERE s.title IS NOT NULL AND size(s.title) > 20
RETURN p.display_name AS project, s.title AS title, s.started_at AS date
ORDER BY s.started_at DESC
LIMIT 60
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
        sessions_result = await db_session.run(SESSIONS_QUERY)
        raw_sessions = await sessions_result.data()

        commits_result = await db_session.run(COMMITS_QUERY)
        raw_commits = await commits_result.data()

    lines: list[str] = ["=== RECENT ACTIVITY (live from timeline graph) ===\n"]

    lines.append("## What I've been working on (recent sessions):")
    seen_titles: set[str] = set()
    count = 0
    for s in raw_sessions:
        title = _clean_title(s.get("title") or "")
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        date = str(s.get("date", ""))[:10]
        project = s.get("project") or "misc"
        lines.append(f"- [{date}] ({project}): {title}")
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
        if _is_sensitive(first_line):
            continue
        date = str(c.get("date", ""))[:10]
        project = c.get("project") or "misc"
        lines.append(f"- [{date}] ({project}): {first_line}")

    return {"context": "\n".join(lines)}
