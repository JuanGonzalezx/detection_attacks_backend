"""CRUD del estado de conversacion por numero de telefono (tabla whatsapp_sessions)."""
from __future__ import annotations

import json
from typing import Any

from app.db import get_pool

# Estados de la maquina
AWAITING_FRONT = "AWAITING_FRONT"
AWAITING_BACK = "AWAITING_BACK"
DONE = "DONE"


async def get_session(phone: str) -> dict[str, Any] | None:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT phone, state, front_result, back_result FROM whatsapp_sessions WHERE phone = $1",
        phone,
    )
    if row is None:
        return None
    return {
        "phone": row["phone"],
        "state": row["state"],
        # asyncpg devuelve jsonb como str; lo deserializamos si vino.
        "front_result": json.loads(row["front_result"]) if row["front_result"] else None,
        "back_result": json.loads(row["back_result"]) if row["back_result"] else None,
    }


async def start_session(phone: str) -> None:
    """Crea o reinicia la sesion en AWAITING_FRONT, limpiando resultados previos."""
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO whatsapp_sessions (phone, state, front_result, back_result, updated_at)
        VALUES ($1, $2, NULL, NULL, now())
        ON CONFLICT (phone) DO UPDATE
        SET state = $2, front_result = NULL, back_result = NULL, updated_at = now()
        """,
        phone,
        AWAITING_FRONT,
    )


async def save_front(phone: str, result: dict) -> None:
    """Guarda el resultado de la frontal y avanza a AWAITING_BACK."""
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO whatsapp_sessions (phone, state, front_result, updated_at)
        VALUES ($1, $2, $3::jsonb, now())
        ON CONFLICT (phone) DO UPDATE
        SET state = $2, front_result = $3::jsonb, updated_at = now()
        """,
        phone,
        AWAITING_BACK,
        json.dumps(result),
    )


async def save_back(phone: str, result: dict) -> None:
    """Guarda el resultado de la trasera y marca DONE."""
    pool = get_pool()
    await pool.execute(
        """
        UPDATE whatsapp_sessions
        SET state = $2, back_result = $3::jsonb, updated_at = now()
        WHERE phone = $1
        """,
        phone,
        DONE,
        json.dumps(result),
    )


async def reset_session(phone: str) -> None:
    pool = get_pool()
    await pool.execute("DELETE FROM whatsapp_sessions WHERE phone = $1", phone)


async def log_validation_event(
    phone: str,
    node: str,
    whatsapp_message_id: str | None,
    lambda_score: float | None,
    lambda_confidence: float | None,
    lambda_response: dict | None,
    latency_aws_ms: int | None,
    latency_gemini_ms: int | None,
    status: str,
    is_photocopy: bool,
) -> None:
    """Inserta un registro de logs en la tabla validation_logs para auditoría y métricas."""
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO validation_logs (
            phone, node, whatsapp_message_id, 
            lambda_score, lambda_confidence, lambda_response, 
            latency_aws_ms, latency_gemini_ms, status, is_photocopy, timestamp
        )
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, now())
        """,
        phone,
        node,
        whatsapp_message_id,
        lambda_score,
        lambda_confidence,
        json.dumps(lambda_response) if lambda_response else None,
        latency_aws_ms,
        latency_gemini_ms,
        status,
        is_photocopy,
    )

