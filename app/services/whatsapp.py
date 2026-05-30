"""Cliente de WhatsApp Cloud API: enviar texto y descargar media (2 pasos)."""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _normalize_phone(phone: str) -> str:
    return phone.strip().replace("+", "").replace(" ", "").replace("-", "")


async def send_text_message(phone: str, text: str) -> tuple[bool, str]:
    """Envia un mensaje de texto. Retorna (ok, message_id | error)."""
    url = f"{settings.graph_base}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _normalize_phone(phone),
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            msg_id = resp.json().get("messages", [{}])[0].get("id", "")
            logger.info("Mensaje enviado a %s (id=%s)", phone, msg_id)
            return True, msg_id
        logger.error("Error enviando a %s: %s %s", phone, resp.status_code, resp.text)
        return False, f"{resp.status_code}: {resp.text}"
    except httpx.TimeoutException:
        logger.error("Timeout enviando mensaje a %s", phone)
        return False, "timeout"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Excepcion enviando mensaje a %s", phone)
        return False, str(exc)


async def download_media(media_id: str) -> bytes:
    """Descarga los bytes de una imagen de WhatsApp en los 2 pasos que exige Meta:
    1) GET /{media_id} -> JSON con la URL temporal de descarga.
    2) GET <url> con el Bearer token -> bytes binarios.
    """
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        meta_resp = await client.get(f"{settings.graph_base}/{media_id}", headers=headers)
        meta_resp.raise_for_status()
        media_url = meta_resp.json()["url"]

        # La URL de media exige el mismo Authorization header.
        bin_resp = await client.get(media_url, headers=headers)
        bin_resp.raise_for_status()
        return bin_resp.content
