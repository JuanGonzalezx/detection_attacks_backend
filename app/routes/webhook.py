"""Webhook de WhatsApp Cloud API: verificacion (GET) y mensajes entrantes (POST)."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections import OrderedDict

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.config import settings
from app.services.flow import handle_image, handle_text

logger = logging.getLogger(__name__)

router = APIRouter()

# Dedup en memoria: Meta reintenta webhooks y puede entregar duplicados.
_seen_ids: "OrderedDict[str, float]" = OrderedDict()
_DEDUP_MAX = 1000
_MAX_AGE_SECONDS = 300  # descartamos mensajes mas viejos que esto (reintentos de Meta)


def _already_seen(msg_id: str) -> bool:
    now = time.time()
    if msg_id in _seen_ids:
        return True
    _seen_ids[msg_id] = now
    while len(_seen_ids) > _DEDUP_MAX:
        _seen_ids.popitem(last=False)
    return False


def _valid_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Valida X-Hub-Signature-256 si hay APP_SECRET configurado."""
    if not settings.whatsapp_app_secret:
        return True  # validacion desactivada
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


@router.get("/webhook")
async def verify(request: Request) -> Response:
    """Handshake de verificacion de Meta."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        logger.info("Webhook verificado por Meta.")
        return Response(content=challenge, media_type="text/plain", status_code=200)
    logger.warning("Verificacion de webhook fallida (token no coincide).")
    return Response(status_code=403)


@router.post("/webhook")
async def incoming(request: Request, background: BackgroundTasks) -> Response:
    """Recibe mensajes. SIEMPRE responde 200 para que Meta no reintente."""
    raw = await request.body()
    if not _valid_signature(raw, request.headers.get("X-Hub-Signature-256")):
        logger.warning("Firma X-Hub-Signature-256 invalida; ignorando.")
        return Response(status_code=200)

    try:
        body = await request.json()
        value = body["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, ValueError):
        return Response(status_code=200)

    # Notificaciones de estado (sent/delivered/read) -> ignorar.
    if "statuses" in value:
        return Response(status_code=200)

    messages = value.get("messages")
    if not messages:
        return Response(status_code=200)

    message = messages[0]
    msg_id = message.get("id")
    from_number = message.get("from")
    if not msg_id or not from_number:
        return Response(status_code=200)

    # Descartar mensajes viejos (reintentos de Meta).
    try:
        ts = int(message.get("timestamp", "0"))
        if ts and (time.time() - ts) > _MAX_AGE_SECONDS:
            return Response(status_code=200)
    except (TypeError, ValueError):
        pass

    if _already_seen(msg_id):
        return Response(status_code=200)

    msg_type = message.get("type")
    if msg_type == "image":
        media_id = message.get("image", {}).get("id")
        if media_id:
            background.add_task(_safe_handle_image, from_number, media_id)
    elif msg_type == "text":
        text_body = message.get("text", {}).get("body", "")
        background.add_task(_safe_handle_text, from_number, text_body)
    else:
        # Tipos no soportados (audio, documento, etc.): guiamos al usuario.
        background.add_task(_safe_handle_text, from_number, "__unsupported__")

    return Response(status_code=200)


async def _safe_handle_image(phone: str, media_id: str) -> None:
    try:
        await handle_image(phone, media_id)
    except Exception:  # noqa: BLE001
        logger.exception("Error procesando imagen de %s", phone)


async def _safe_handle_text(phone: str, text: str) -> None:
    try:
        await handle_text(phone, text)
    except Exception:  # noqa: BLE001
        logger.exception("Error procesando texto de %s", phone)
