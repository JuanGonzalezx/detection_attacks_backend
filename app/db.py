"""Pool de conexiones asyncpg a Supabase/Postgres + creacion del esquema."""
from __future__ import annotations

import logging

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS whatsapp_sessions (
    phone        TEXT PRIMARY KEY,
    state        TEXT NOT NULL DEFAULT 'AWAITING_FRONT',
    front_result JSONB,
    back_result  JSONB,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS validation_logs (
    id SERIAL PRIMARY KEY,
    phone TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    node TEXT NOT NULL,
    whatsapp_message_id TEXT,
    lambda_score NUMERIC,
    lambda_confidence NUMERIC,
    lambda_response JSONB,
    latency_aws_ms INTEGER,
    latency_gemini_ms INTEGER,
    status TEXT NOT NULL,
    is_photocopy BOOLEAN NOT NULL DEFAULT FALSE
);
"""


async def init_db() -> None:
    """Crea el pool y asegura que la tabla exista. Idempotente."""
    global _pool
    if _pool is not None:
        return
    if not settings.database_url:
        # No crasheamos: dejamos levantar el servicio para que la verificacion del
        # webhook (GET) y el health check funcionen aun sin DB. Los handlers que
        # necesiten DB fallaran de forma controlada (ver get_pool).
        logger.warning("DATABASE_URL no configurada: arranco sin pool de DB.")
        return

    # statement_cache_size=0 es obligatorio con el pooler de Supabase (pgbouncer
    # en modo transaction no soporta prepared statements).
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=5,
        statement_cache_size=0,
    )
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)
    logger.info("DB lista: pool creado y tabla whatsapp_sessions verificada.")


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("El pool de DB no esta inicializado (llama init_db primero)")
    return _pool
