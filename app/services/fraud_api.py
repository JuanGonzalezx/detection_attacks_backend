"""Cliente del Lambda de deteccion de fraude (Rekognition).

Contrato verificado empiricamente del endpoint:
    POST  application/json  body = {"image": "<base64 de la imagen>"}
Responde JSON con lo que Rekognition haya detectado.
"""
from __future__ import annotations

import base64
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def call_fraud_api(image_bytes: bytes) -> dict:
    """Envia la imagen (en base64) al Lambda y devuelve el JSON de respuesta.

    Siempre retorna un dict. Si algo falla, incluye la clave "error".
    """
    b64 = base64.b64encode(image_bytes).decode("ascii")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(settings.fraud_api_url, json={"image": b64})
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}
        if resp.status_code != 200:
            logger.error("Lambda respondio %s: %s", resp.status_code, resp.text)
            data.setdefault("error", f"HTTP {resp.status_code}")
        return data
    except httpx.TimeoutException:
        logger.error("Timeout llamando al Lambda de fraude")
        return {"error": "timeout llamando al servicio de analisis"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Excepcion llamando al Lambda de fraude")
        return {"error": str(exc)}
