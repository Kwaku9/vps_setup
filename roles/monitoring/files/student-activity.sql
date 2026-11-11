-- student-activity.sql (idempotent). Durable per-student history for the
-- mentoring view: what each account opened, per day, across the platform.
-- Written only by /usr/local/bin/student-activity (root, via podman exec psql).
-- Read only by the ops dashboard (admin-only Students page). Metadata only:
-- which page, dashboard, deck slide or app, and when. Never chat text or
-- search terms.
\set ON_ERROR_STOP on

CREATE SCHEMA IF NOT EXISTS mentoring;

-- One row per account, day, resource and item.
--   resource: grafana | threat | decks | portal | charts | timeline | tts | login | openwebui
--   item:     dashboard:<uid> | deck:<name> | page:<first path segment> | api:<endpoint>
--             | <app domain> | refused:<app domain> | chats_active | chats_started | model:<id>
CREATE TABLE IF NOT EXISTS mentoring.activity (
    day         date        NOT NULL,
    email       text        NOT NULL,
    resource    text        NOT NULL,
    item        text        NOT NULL,
    hits        integer     NOT NULL DEFAULT 0,
    first_seen  timestamptz NOT NULL,
    last_seen   timestamptz NOT NULL,
    PRIMARY KEY (day, email, resource, item)
);
CREATE INDEX IF NOT EXISTS activity_email_idx ON mentoring.activity (email, day DESC);

-- Furthest point reached in each reveal.js deck (from the slide beacon the
-- decks nginx injects). slide_index is 0-based over every slide in order.
CREATE TABLE IF NOT EXISTS mentoring.deck_progress (
    email        text        NOT NULL,
    deck         text        NOT NULL,
    slides_total integer     NOT NULL,
    max_slide    integer     NOT NULL,
    slides_seen  integer[]   NOT NULL DEFAULT '{}',
    first_seen   timestamptz NOT NULL,
    last_seen    timestamptz NOT NULL,
    PRIMARY KEY (email, deck)
);

-- Grafana dashboard uid -> title (both orgs), refreshed at deploy.
CREATE TABLE IF NOT EXISTS mentoring.dashboards (
    uid   text PRIMARY KEY,
    title text NOT NULL
);

GRANT USAGE ON SCHEMA mentoring TO ops_dashboard;
GRANT SELECT ON ALL TABLES IN SCHEMA mentoring TO ops_dashboard;
