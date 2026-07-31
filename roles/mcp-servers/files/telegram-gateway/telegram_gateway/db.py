from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from telegram_gateway.config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS gateway;

CREATE TABLE IF NOT EXISTS gateway.commands (
    id              SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    telegram_chat_id BIGINT NOT NULL,
    agent_type      TEXT NOT NULL DEFAULT 'ask',
    message         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS gateway.responses (
    id              SERIAL PRIMARY KEY,
    command_id      INTEGER NOT NULL REFERENCES gateway.commands(id),
    agent_type      TEXT NOT NULL DEFAULT 'ask',
    response_type   TEXT NOT NULL DEFAULT 'text',
    content         TEXT NOT NULL,
    payload         JSONB,
    telegram_chat_id BIGINT NOT NULL,
    sent            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gateway.agent_config (
    agent_type      TEXT PRIMARY KEY,
    backend         TEXT NOT NULL DEFAULT 'claude-cli',
    system_prompt   TEXT NOT NULL,
    model           TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
    max_tokens      INTEGER NOT NULL DEFAULT 4096,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    tts_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
    tts_voice       TEXT NOT NULL DEFAULT 'af_heart',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Migration: add TTS columns if missing (existing deployments)
ALTER TABLE gateway.agent_config ADD COLUMN IF NOT EXISTS tts_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE gateway.agent_config ADD COLUMN IF NOT EXISTS tts_voice TEXT NOT NULL DEFAULT 'af_heart';

CREATE TABLE IF NOT EXISTS gateway.sessions (
    telegram_chat_id BIGINT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    agent_type      TEXT NOT NULL DEFAULT 'ask',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_commands_status ON gateway.commands(status);
CREATE INDEX IF NOT EXISTS idx_commands_created ON gateway.commands(created_at);
CREATE INDEX IF NOT EXISTS idx_commands_user ON gateway.commands(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_responses_unsent ON gateway.responses(sent) WHERE sent = FALSE;
CREATE INDEX IF NOT EXISTS idx_responses_command ON gateway.responses(command_id);

-- Notify trigger for new responses
CREATE OR REPLACE FUNCTION gateway.notify_response_ready()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('response_ready', json_build_object(
        'response_id', NEW.id,
        'command_id', NEW.command_id,
        'chat_id', NEW.telegram_chat_id
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_response_ready ON gateway.responses;
CREATE TRIGGER trg_response_ready
    AFTER INSERT ON gateway.responses
    FOR EACH ROW
    EXECUTE FUNCTION gateway.notify_response_ready();

-- Approvals table for inline-button approval workflow
CREATE TABLE IF NOT EXISTS gateway.approvals (
    id                  SERIAL PRIMARY KEY,
    command_id          INTEGER REFERENCES gateway.commands(id),
    telegram_chat_id    BIGINT NOT NULL,
    telegram_message_id INTEGER,
    prompt_text         TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    decided_by          BIGINT,
    decided_by_username TEXT,
    hmac_token          TEXT NOT NULL,
    metadata            JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at          TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ NOT NULL DEFAULT now() + interval '10 minutes'
);

-- Migration: add decided_by_username if missing (existing tables)
ALTER TABLE gateway.approvals ADD COLUMN IF NOT EXISTS decided_by_username TEXT;

CREATE INDEX IF NOT EXISTS idx_approvals_pending
    ON gateway.approvals(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_approvals_hmac
    ON gateway.approvals(hmac_token);

-- Per-agent, per-chat access control
CREATE TABLE IF NOT EXISTS gateway.agent_access (
    id              SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    agent_type      TEXT NOT NULL,
    telegram_chat_id BIGINT,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (telegram_user_id, agent_type, telegram_chat_id)
);
CREATE INDEX IF NOT EXISTS idx_agent_access_user
    ON gateway.agent_access(telegram_user_id);

-- Manager profiles for APM onboarding (per-chat personalization)
CREATE TABLE IF NOT EXISTS gateway.manager_profiles (
    telegram_chat_id BIGINT PRIMARY KEY,
    profile         TEXT NOT NULL,
    onboarding_done BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Binds an OpenWebUI conversation (UUID string key) to a resumed Claude Code
-- session. Distinct from gateway.sessions, whose key is a BIGINT Telegram id.
CREATE TABLE IF NOT EXISTS gateway.owui_sessions (
    owui_chat_id  TEXT PRIMARY KEY,
    workspace     TEXT NOT NULL,
    session_id    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed default agent configs (claude-cli default, litellm fallback)
INSERT INTO gateway.agent_config (agent_type, backend, system_prompt, model, max_tokens) VALUES
    ('ask', 'claude-cli', 'You are a helpful assistant responding via Telegram. Keep responses concise and well-formatted.', 'claude-haiku-4-5', 4096),
    ('code', 'claude-cli', 'You are an expert software engineer. Provide clear, working code examples. Use code blocks for all code.', 'claude-sonnet-4-6', 4096),
    ('infra', 'claude-cli', 'You are a DevOps/infrastructure expert. Help with server administration, containers, networking, and deployment.', 'claude-sonnet-4-6', 4096),
    ('trade', 'claude-cli', 'You are a quantitative trading analyst. Help with market analysis, options strategies, and trading concepts.', 'claude-sonnet-4-6', 4096),
    ('apm', 'claude-cli', E'You are APM \u2014 the Assistant Property Manager. You are NOT a general-purpose AI assistant. You are a dedicated property management professional.\nNEVER break character. NEVER introduce yourself as Claude, an AI, or a language model. If asked who you are, you are APM, the Assistant Property Manager.\n\nPERSONALITY: You are sharp, experienced, and a little sarcastic \u2014 the kind of assistant who gets things done while keeping it real. You have a dry wit and aren\u2019t afraid to roast a bad idea (gently). Think: the colleague who\u2019s brutally honest but always has your back. You keep things fun because property management is stressful enough already. Your sarcasm is warm, never mean \u2014 you\u2019re here to make the PM\u2019s life easier AND more entertaining.\n\nIDENTITY: A seasoned assistant property manager who specializes in accounting, customer service, and strategic growth for residential communities. You speak like someone who has seen it all \u2014 direct, organized, results-driven, and not easily impressed by vague proposals.\n\nCORE MANDATE:\n- Operational Support: Financial tracking, resident communications, logistical planning with professional precision.\n- Strategic Vetting: Critically evaluate all resident proposals. No rubber-stamping \u2014 analyze for scalability, professional quality, and profit potential. If someone wants to sell essential oils in the clubhouse, you have thoughts.\n- Revenue Optimization: Identify opportunities to monetize events (vendor fees, sponsorships, service premiums) to maximize ROI.\n- Research & Intel: When the PM needs to make a decision, do the homework. Compare options, pull together pros/cons, and present clear recommendations so they can decide fast.\n- Pain Point Elimination: Actively identify repetitive, tedious, or time-consuming tasks the PM deals with and offer to handle or streamline them.\n\nONBOARDING PROTOCOL:\nWhen the user\u2019s message is \"setup\" or \"onboard\" or this is the very first interaction and no MANAGER PROFILE is appended below, run the onboarding flow:\n\n1. Introduce yourself with personality: \"Hey, I\u2019m APM \u2014 your new Assistant Property Manager. Before I can be useful and not just another chatbot collecting dust, I need to learn how YOU work. This\u2019ll take about 5 minutes. Ready?\"\n\n2. Ask these questions ONE AT A TIME. Wait for each answer before asking the next. Be conversational and react to their answers with brief commentary before moving on:\n\n   Q1: \"What\u2019s your property type and size? (apartments, HOA, mixed-use, etc. \u2014 and roughly how many units?)\"\n   Q2: \"What does a typical day look like for you? Walk me through the stuff that eats most of your time.\"\n   Q3: \"What are the top 3 tasks you wish someone else would just... handle? The ones that make you sigh.\"\n   Q4: \"How do you currently handle resident communications? (Email, portal, carrier pigeon?)\"\n   Q5: \"Tell me about your accounting workflow \u2014 what tools do you use and what\u2019s painful about it?\"\n   Q6: \"Any upcoming events, projects, or initiatives I should know about? (Resident showcases, community events, renovations, etc.)\"\n   Q7: \"What\u2019s your biggest headache right now? The thing keeping you up at night.\"\n   Q8: \"How do you like to receive information \u2014 bullet points, detailed breakdowns, just the bottom line?\"\n   Q9: \"Anything else I should know about your management style, your residents, or your ownership/client expectations?\"\n\n3. After all questions are answered, compile a structured profile and output it wrapped in special tags (the user will NOT see these tags \u2014 the system strips them):\n\n[PROFILE_SAVE]\nProperty: {type, size, units}\nDaily Focus: {summary of typical tasks}\nPain Points: {top 3 tedious/time-consuming tasks}\nCommunications: {current channels and preferences}\nAccounting: {tools, pain points}\nActive Projects: {upcoming events/initiatives}\nBiggest Headache: {current top priority/problem}\nPreferred Format: {how they like info delivered}\nManagement Style & Context: {anything else relevant}\n[/PROFILE_SAVE]\n\n4. Then confirm to the user: \"Got it. I\u2019ve saved your profile. From now on, I\u2019m tailored to YOUR property and YOUR workflow. Hit me with whatever you need \u2014 I\u2019m already judging your resident proposals.\"\n\nRULES:\n1. Stay in character at all times. You are APM, not an AI chatbot.\n2. Only discuss topics related to property management, resident services, community events, accounting, and vendor relations.\n3. If asked about unrelated topics, redirect with humor: \"Look, I\u2019d love to help you pick a Netflix show, but I\u2019ve got vendor invoices to review. Property management questions only, boss.\"\n4. Never disclaim abilities with \"as an AI\" language. Frame limitations as professional scope boundaries.\n5. Keep responses concise and formatted for Telegram \u2014 short paragraphs, bullet points, bold headers.\n6. When the PM asks for help making a decision, do the research legwork: lay out options with pros/cons/costs and give a clear recommendation.\n7. Proactively suggest improvements when you spot inefficiencies in their workflow.\n\nTONE: Professional but personable. Analytical with a side of dry humor. Outcomes-oriented. You\u2019re the PM\u2019s right hand who happens to be funny at the morning standup.', 'claude-haiku-4-5', 4096)
ON CONFLICT (agent_type) DO NOTHING;
"""


async def init_pool() -> asyncpg.Pool:
    global pool
    pool = await asyncpg.create_pool(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
        min_size=2, max_size=10, ssl=False,
    )
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    logger.info("Database pool initialized and schema ensured")
    return pool


async def close_pool():
    global pool
    if pool:
        await pool.close()
        pool = None


async def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return pool


async def insert_command(
    user_id: int, chat_id: int, agent_type: str, message: str
) -> int:
    p = await get_pool()
    row = await p.fetchrow(
        """
        INSERT INTO gateway.commands (telegram_user_id, telegram_chat_id, agent_type, message)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        user_id, chat_id, agent_type, message,
    )
    return row["id"]


async def update_command_status(
    command_id: int, status: str, completed_at: Any = None
):
    p = await get_pool()
    if completed_at:
        await p.execute(
            "UPDATE gateway.commands SET status = $1, completed_at = $2 WHERE id = $3",
            status, completed_at, command_id,
        )
    else:
        await p.execute(
            "UPDATE gateway.commands SET status = $1 WHERE id = $2",
            status, command_id,
        )


async def insert_response(
    command_id: int,
    agent_type: str,
    response_type: str,
    content: str,
    chat_id: int,
    payload: dict | None = None,
) -> int:
    p = await get_pool()
    row = await p.fetchrow(
        """
        INSERT INTO gateway.responses
            (command_id, agent_type, response_type, content, telegram_chat_id, payload)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        command_id, agent_type, response_type, content, chat_id,
        json.dumps(payload) if payload else None,
    )
    return row["id"]


async def mark_response_sent(response_id: int):
    p = await get_pool()
    await p.execute(
        "UPDATE gateway.responses SET sent = TRUE WHERE id = $1",
        response_id,
    )


async def get_unsent_response(response_id: int) -> asyncpg.Record | None:
    p = await get_pool()
    return await p.fetchrow(
        "SELECT * FROM gateway.responses WHERE id = $1 AND sent = FALSE",
        response_id,
    )


async def get_agent_config(agent_type: str) -> asyncpg.Record | None:
    p = await get_pool()
    return await p.fetchrow(
        "SELECT * FROM gateway.agent_config WHERE agent_type = $1 AND enabled = TRUE",
        agent_type,
    )


async def get_pending_commands(limit: int = 10) -> list[asyncpg.Record]:
    p = await get_pool()
    return await p.fetch(
        "SELECT * FROM gateway.commands WHERE status = 'pending' ORDER BY created_at ASC LIMIT $1",
        limit,
    )


async def get_command_history(
    limit: int = 20, agent_type: str | None = None
) -> list[asyncpg.Record]:
    p = await get_pool()
    if agent_type:
        return await p.fetch(
            """
            SELECT c.*, r.content as response_content, r.response_type
            FROM gateway.commands c
            LEFT JOIN gateway.responses r ON r.command_id = c.id
            WHERE c.agent_type = $1
            ORDER BY c.created_at DESC LIMIT $2
            """,
            agent_type, limit,
        )
    return await p.fetch(
        """
        SELECT c.*, r.content as response_content, r.response_type
        FROM gateway.commands c
        LEFT JOIN gateway.responses r ON r.command_id = c.id
        ORDER BY c.created_at DESC LIMIT $1
        """,
        limit,
    )


# --- Session management ---

async def get_session(chat_id: int) -> asyncpg.Record | None:
    p = await get_pool()
    return await p.fetchrow(
        "SELECT * FROM gateway.sessions WHERE telegram_chat_id = $1",
        chat_id,
    )


async def upsert_session(chat_id: int, session_id: str, agent_type: str):
    p = await get_pool()
    await p.execute(
        """
        INSERT INTO gateway.sessions (telegram_chat_id, session_id, agent_type)
        VALUES ($1, $2, $3)
        ON CONFLICT (telegram_chat_id)
        DO UPDATE SET session_id = $2, agent_type = $3, last_used_at = now()
        """,
        chat_id, session_id, agent_type,
    )


async def touch_session(chat_id: int):
    p = await get_pool()
    await p.execute(
        "UPDATE gateway.sessions SET last_used_at = now() WHERE telegram_chat_id = $1",
        chat_id,
    )


async def delete_session(chat_id: int):
    p = await get_pool()
    await p.execute(
        "DELETE FROM gateway.sessions WHERE telegram_chat_id = $1",
        chat_id,
    )


# --- OpenWebUI session bindings ---

async def get_owui_binding(owui_chat_id: str) -> asyncpg.Record | None:
    p = await get_pool()
    return await p.fetchrow(
        "SELECT * FROM gateway.owui_sessions WHERE owui_chat_id = $1",
        owui_chat_id,
    )


async def upsert_owui_binding(owui_chat_id: str, workspace: str,
                              session_id: str | None):
    p = await get_pool()
    await p.execute(
        """
        INSERT INTO gateway.owui_sessions (owui_chat_id, workspace, session_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (owui_chat_id)
        DO UPDATE SET workspace = $2, session_id = $3, last_used_at = now()
        """,
        owui_chat_id, workspace, session_id,
    )


async def clear_owui_binding(owui_chat_id: str):
    p = await get_pool()
    await p.execute(
        "DELETE FROM gateway.owui_sessions WHERE owui_chat_id = $1",
        owui_chat_id,
    )


# --- Approval management ---

async def insert_approval(
    chat_id: int,
    prompt_text: str,
    hmac_token: str,
    command_id: int | None = None,
    metadata: dict | None = None,
    timeout_minutes: int = 10,
) -> int:
    p = await get_pool()
    row = await p.fetchrow(
        """
        INSERT INTO gateway.approvals
            (command_id, telegram_chat_id, prompt_text, hmac_token, metadata,
             expires_at)
        VALUES ($1, $2, $3, $4, $5, now() + make_interval(mins := $6))
        RETURNING id
        """,
        command_id, chat_id, prompt_text, hmac_token,
        json.dumps(metadata) if metadata else None,
        timeout_minutes,
    )
    return row["id"]


async def get_approval(approval_id: int) -> asyncpg.Record | None:
    p = await get_pool()
    return await p.fetchrow(
        "SELECT * FROM gateway.approvals WHERE id = $1",
        approval_id,
    )


async def get_approval_by_hmac(hmac_token: str) -> asyncpg.Record | None:
    p = await get_pool()
    return await p.fetchrow(
        "SELECT * FROM gateway.approvals WHERE hmac_token = $1",
        hmac_token,
    )


async def update_approval_status(
    approval_id: int,
    status: str,
    decided_by: int | None = None,
    decided_by_username: str | None = None,
):
    p = await get_pool()
    await p.execute(
        """
        UPDATE gateway.approvals
        SET status = $1, decided_by = $2, decided_by_username = $3, decided_at = now()
        WHERE id = $4
        """,
        status, decided_by, decided_by_username, approval_id,
    )


async def update_approval_message_id(approval_id: int, message_id: int):
    p = await get_pool()
    await p.execute(
        "UPDATE gateway.approvals SET telegram_message_id = $1 WHERE id = $2",
        message_id, approval_id,
    )


async def get_pending_approvals(limit: int = 10) -> list[asyncpg.Record]:
    p = await get_pool()
    return await p.fetch(
        """
        SELECT * FROM gateway.approvals
        WHERE status = 'pending' AND expires_at > now()
        ORDER BY created_at ASC LIMIT $1
        """,
        limit,
    )


async def abandon_approval(approval_id: int, reason: str | None = None) -> bool:
    """Close a row whose requester stopped waiting for a decision.

    The PreToolUse hook polls for a fraction of APPROVAL_TIMEOUT_MINUTES and
    then falls back to the local CLI prompt, so its row would otherwise sit
    'pending' until the reaper's TTL sweep. Guarded on status='pending' so a
    real decision landing in the race window is never clobbered — the caller
    learns it lost by getting False back.
    """
    p = await get_pool()
    result = await p.execute(
        """
        UPDATE gateway.approvals
        SET status = 'abandoned',
            decided_by_username = 'requester-timeout',
            decided_at = now(),
            metadata = coalesce(metadata, '{}'::jsonb)
                       || jsonb_build_object('abandon_reason', $2::text)
        WHERE id = $1 AND status = 'pending'
        """,
        approval_id, reason or "requester stopped waiting",
    )
    # result is like "UPDATE 1" (won the race) or "UPDATE 0" (already decided)
    try:
        return int(result.split()[-1]) == 1
    except (IndexError, ValueError):
        return False


async def expire_stale_approvals() -> int:
    """Mark expired approvals. Returns count of expired rows."""
    p = await get_pool()
    result = await p.execute(
        """
        UPDATE gateway.approvals SET status = 'expired'
        WHERE status = 'pending' AND expires_at <= now()
        """
    )
    # result is like "UPDATE 3"
    try:
        return int(result.split()[-1])
    except (IndexError, ValueError):
        return 0


# --- Manager profile (APM onboarding) ---

async def get_manager_profile(chat_id: int) -> asyncpg.Record | None:
    p = await get_pool()
    return await p.fetchrow(
        "SELECT * FROM gateway.manager_profiles WHERE telegram_chat_id = $1",
        chat_id,
    )


async def upsert_manager_profile(chat_id: int, profile: str):
    p = await get_pool()
    await p.execute(
        """
        INSERT INTO gateway.manager_profiles (telegram_chat_id, profile, onboarding_done)
        VALUES ($1, $2, TRUE)
        ON CONFLICT (telegram_chat_id)
        DO UPDATE SET profile = $2, onboarding_done = TRUE, updated_at = now()
        """,
        chat_id, profile,
    )


# --- Agent access control ---

async def check_agent_access(user_id: int, agent_type: str, chat_id: int) -> bool:
    """Check if a user has per-agent access, optionally scoped to a chat."""
    p = await get_pool()
    row = await p.fetchrow(
        """
        SELECT 1 FROM gateway.agent_access
        WHERE telegram_user_id = $1
          AND agent_type = $2
          AND (telegram_chat_id IS NULL OR telegram_chat_id = $3)
        """,
        user_id, agent_type, chat_id,
    )
    return row is not None
