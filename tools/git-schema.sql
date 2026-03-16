-- Git History Schema for Session Correlation
-- Extends the sessions schema with git commit tracking
-- Run: podman exec -i shared-db-pod-postgres psql -U postgres -d enterprise < git-schema.sql

CREATE SCHEMA IF NOT EXISTS sessions;

-- Tracked git repositories
CREATE TABLE IF NOT EXISTS sessions.git_repos (
    id              SERIAL PRIMARY KEY,
    repo_name       TEXT NOT NULL UNIQUE,
    repo_path_vps   TEXT,
    repo_path_local TEXT,
    default_branch  TEXT DEFAULT 'main',
    project_id      INTEGER REFERENCES sessions.projects(id),
    last_ingested_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Git commits with optional session correlation
CREATE TABLE IF NOT EXISTS sessions.git_commits (
    id              SERIAL PRIMARY KEY,
    repo_id         INTEGER NOT NULL REFERENCES sessions.git_repos(id),
    commit_hash     TEXT NOT NULL,
    short_hash      TEXT NOT NULL,
    author_name     TEXT,
    author_email    TEXT,
    commit_message  TEXT,
    committed_at    TIMESTAMPTZ NOT NULL,
    branch          TEXT,
    files_changed   INTEGER DEFAULT 0,
    insertions      INTEGER DEFAULT 0,
    deletions       INTEGER DEFAULT 0,
    net_lines       INTEGER GENERATED ALWAYS AS (insertions - deletions) STORED,
    session_id      INTEGER REFERENCES sessions.sessions(id),
    co_authored     BOOLEAN DEFAULT FALSE,
    imported_at     TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_git_commits_repo_hash UNIQUE (repo_id, commit_hash)
);

CREATE INDEX IF NOT EXISTS idx_git_commits_committed ON sessions.git_commits(committed_at DESC);
CREATE INDEX IF NOT EXISTS idx_git_commits_repo ON sessions.git_commits(repo_id);
CREATE INDEX IF NOT EXISTS idx_git_commits_session ON sessions.git_commits(session_id);
CREATE INDEX IF NOT EXISTS idx_git_commits_date ON sessions.git_commits((committed_at::date));
