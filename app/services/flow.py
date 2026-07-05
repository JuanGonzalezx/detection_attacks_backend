"""Maquina de estados de la conversacion: flujo imagen-por-imagen (frontal -> trasera)."""
from __future__ import annotations

import logging

from app.services import sessions
from app.services.fraud_api import call_fraud_api
from app.services.whatsapp import download_media, send_text_message
from app.services.gemini import generate_humanized_message


logger = logging.getLogger(__name__)

GREETING = (
    "Hola \U0001F44B. Soy el asistente de verificacion de documentos.\n\n"
    "Envia una *foto de la PARTE FRONTAL* de tu cedula."
)
ASK_BACK = "Frontal recibida ✅.\n\nAhora envia una *foto de la PARTE TRASERA*."
ASK_FRONT_AGAIN = "Aun no he recibido la frontal. Envia la *foto de la PARTE FRONTAL* de tu cedula."
ASK_BACK_AGAIN = "Ya recibi la frontal. Ahora envia la *foto de la PARTE TRASERA*."
FRONT_FAILED = (
    "No pude analizar la frontal (el servicio de analisis no respondio bien). "
    "Por favor *reenvia la foto de la PARTE FRONTAL*."
)
BACK_FAILED = (
    "No pude analizar la trasera (el servicio de analisis no respondio bien). "
    "Por favor *reenvia la foto de la PARTE TRASERA*."
)
ALREADY_DONE = (
    "Ya procese ambas caras de tu documento. Si quieres analizar otro, escribe *reiniciar*."
)
RESET_DONE = "Listo, reinicie el proceso. Envia la *foto de la PARTE FRONTAL* de tu cedula."


def _summarize(side: str, result: dict) -> str:
    """Resumen corto y legible de lo que devolvio el Lambda/Rekognition.

    Es tolerante al formato actual (labels genericas) y al futuro (cedula/score/coordenadas).
    """
    if not result or "error" in result:
        detail = result.get("error") or result.get("detail") if result else "sin respuesta"
        return f"No pude analizar la {side}: {detail}"

    parts: list[str] = []
    # Campos que probablemente agregue el Lambda mas adelante.
    if result.get("documentNumber") or result.get("cedula"):
        parts.append(f"Documento: {result.get('documentNumber') or result.get('cedula')}")
    if result.get("name") or result.get("nombre"):
        parts.append(f"Nombre: {result.get('name') or result.get('nombre')}")
    score = result.get("fraudScore") or result.get("confidence") or result.get("score")
    if score is not None:
        parts.append(f"Score: {score}")

    # Formato actual: Rekognition suele devolver labels o texto detectado.
    labels = result.get("Labels") or result.get("labels")
    if labels:
        names = [l.get("Name", l) if isinstance(l, dict) else l for l in labels][:5]
        parts.append("Detectado: " + ", ".join(map(str, names)))
    texts = result.get("TextDetections") or result.get("text")
    if texts and not labels:
        parts.append("Texto detectado en el documento.")

    if not parts:
        parts.append("analisis recibido.")
    return f"{side.capitalize()}: " + " | ".join(parts)


async def _process_image(phone: str, media_id: str, side: str) -> dict:
    """Descarga la imagen de Meta y la manda al Lambda. Devuelve el JSON del Lambda."""
    image_bytes = await download_media(media_id)
    logger.info("Imagen (%s) descargada de %s: %d bytes", side, phone, len(image_bytes))
    result = await call_fraud_api(image_bytes)
    logger.info("Lambda respondio para %s (%s): %s", phone, side, result)
    return result


async def handle_text(phone: str, text: str) -> None:
    """Maneja un mensaje de texto entrante."""
    normalized = text.strip().lower()
    if normalized in {"reiniciar", "reset", "empezar", "nuevo"}:
        await sessions.start_session(phone)
        greeting_msg = await generate_humanized_message("GREETING", {})
        await send_text_message(phone, greeting_msg)
        return

    session = await sessions.get_session(phone)
    if session is None:
        await sessions.start_session(phone)
        greeting_msg = await generate_humanized_message("GREETING", {})
        await send_text_message(phone, greeting_msg)
        return

    state = session["state"]
    # Responder de manera inteligente/conversacional al texto libre del usuario
    response_msg = await generate_humanized_message(
        "UNSUPPORTED_TEXT",
        {"current_state": state, "user_text": text}
    )
    await send_text_message(phone, response_msg)



async def handle_image(phone: str, media_id: str) -> None:
    """Maneja una imagen entrante segun el estado de la sesion."""
    session = await sessions.get_session(phone)

    # Tolerante: si no hay sesion, tratamos la 1a imagen como frontal.
    state = session["state"] if session else sessions.AWAITING_FRONT

    if state == sessions.AWAITING_FRONT:
        result = await _process_image(phone, media_id, "frontal")
        if "error" in result:
            response_msg = await generate_humanized_message(
                "AWAITING_FRONT_RESULT",
                {"result": result}
            )
            await send_text_message(phone, response_msg)
            return
        await sessions.save_front(phone, result)
        response_msg = await generate_humanized_message(
            "AWAITING_FRONT_RESULT",
            {"result": result}
        )
        await send_text_message(phone, response_msg)

    elif state == sessions.AWAITING_BACK:
        result = await _process_image(phone, media_id, "trasera")
        if "error" in result:
            response_msg = await generate_humanized_message(
                "AWAITING_BACK_RESULT",
                {"back_result": result}
            )
            await send_text_message(phone, response_msg)
            return
        await sessions.save_back(phone, result)
        
        front_result = session["front_result"] if session else None
        if not front_result:
            # Re-leer para asegurar los datos de la frontal
            updated_session = await sessions.get_session(phone)
            front_result = updated_session["front_result"] if updated_session else {}

        response_msg = await generate_humanized_message(
            "AWAITING_BACK_RESULT",
            {"front_result": front_result, "back_result": result}
        )
        await send_text_message(phone, response_msg)

    else:  # DONE
        response_msg = await generate_humanized_message(
            "UNSUPPORTED_TEXT",
            {"current_state": sessions.DONE, "user_text": "[imagen]"}
        )
        await send_text_message(phone, response_msg)

