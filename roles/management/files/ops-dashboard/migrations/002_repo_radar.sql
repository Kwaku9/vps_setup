-- 002_repo_radar.sql — idempotent. Safe to re-run.
-- One row per host holding the latest Repo Radar snapshot (git state of every
-- repository in that host's workspace). The laptop pushes its snapshot to
-- /api/repo-radar/ingest; the dashboard scans the VPS workspace itself.
\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS sessions.repo_radar_snapshots (
    host        text PRIMARY KEY,
    payload     jsonb NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON sessions.repo_radar_snapshots TO ops_dashboard;
