"""Async Postgres pool for the sessions feature."""
from __future__ import annotations

import os
from urllib.parse import quote

import asyncpg


def build_dsn(host: str, port: int, db: str, user: str, password: str) -> str:
    return f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{db}"


def dsn_from_env() -> str:
    return build_dsn(
        host=os.environ.get("DB_HOST", "shared-db-pod"),
        port=int(os.environ.get("DB_PORT", "5432")),
        db=os.environ.get("DB_NAME", "enterprise"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


async def create_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=dsn_from_env(), min_size=1, max_size=5)
