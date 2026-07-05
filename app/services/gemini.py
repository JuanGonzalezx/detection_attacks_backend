"""Servicio para interactuar con la API de Gemini usando google-genai."""
from __future__ import annotations

import logging
import json
from typing import Any

from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

# Configuración del prompt de sistema para que actúe como un asistente de WhatsApp
SYSTEM_INSTRUCTION = (
    "Eres un asistente virtual de validación de identidad para un proyecto de detección de fraude en cédulas colombianas. "
    "Te comunicarás con el usuario por WhatsApp en español. Tu tono debe ser profesional, amable, claro, empático y de apoyo.\n\n"
    "Reglas de formato y comportamiento:\n"
    "- Usa formato de WhatsApp para resaltar texto (*negrita* para enfatizar, _cursiva_ para términos o aclaraciones, ~tachado~ si es necesario).\n"
    "- Mantén los mensajes concisos y fáciles de leer en una pantalla de celular (usa saltos de línea dobles para separar párrafos y emojis de manera moderada y profesional).\n"
    "- NUNCA muestres JSON crudo o detalles técnicos que confundan al usuario (por ejemplo, coordenadas X/Y de cajas delimitadoras, bounding boxes, s3_keys, o hashes internos).\n"
    "- Explica los resultados (como el score de coincidencia o problemas con el ángulo de la foto) de forma comprensible para una persona común.\n"
    "- El bot solo procesa cédulas. Si el usuario pregunta cosas no relacionadas, sé cortés pero redirígelo al flujo del documento.\n"
)


def _get_client() -> genai.Client | None:
    """Obtiene una instancia del cliente de Gemini si la API key está configurada."""
    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY no está configurada.")
        return None
    try:
        return genai.Client(api_key=settings.gemini_api_key)
    except Exception:
        logger.exception("Error al inicializar el cliente de Gemini")
        return None


async def generate_humanized_message(
    flow_state: str,
    context: dict[str, Any],
) -> str:
    """Genera una respuesta humanizada y natural usando Gemini 2.5 Flash.

    Si falla la llamada a la API o no hay API key, se retorna un mensaje por defecto (fallback).
    """
    client = _get_client()
    if not client:
        return _get_fallback_message(flow_state, context)

    # Determinar el prompt de usuario según el estado
    user_prompt = ""
    if flow_state == "GREETING":
        user_prompt = (
            "El usuario acaba de iniciar el proceso o ha solicitado reiniciar. "
            "Salúdalo con entusiasmo y amabilidad, explícale brevemente que validarás su identidad de forma segura, "
            "y pídele que por favor envíe una foto nítida de la PARTE FRONTAL de su cédula colombiana."
        )
    elif flow_state == "AWAITING_FRONT_RESULT":
        result = context.get("result", {})
        user_prompt = (
            f"El usuario envió la foto frontal de su cédula. El modelo de Rekognition devolvió el siguiente análisis técnico:\n"
            f"{json.dumps(result, indent=2)}\n\n"
            "Analiza el resultado:\n"
            "- Si el análisis falló (por ejemplo, si contiene un campo 'error'), pídele amablemente que por favor vuelva a tomar la foto de la parte frontal, asegurando buena luz y enfoque.\n"
            "- Si fue exitoso: indícale que la foto frontal fue recibida correctamente. Si los valores técnicos parecen correctos (score/confianza aceptable), felicítalo e indícale que ahora envíe la foto de la PARTE TRASERA para finalizar.\n"
            "- Si el score de detección/confianza es alarmantemente bajo o hay advertencias de imagen no apta, sugiérele con tacto repetir la foto frontal dando consejos simples (sin reflejos, cédula plana, enfoque nítido)."
        )
    elif flow_state == "AWAITING_BACK_RESULT":
        front = context.get("front_result", {})
        back = context.get("back_result", {})
        user_prompt = (
            "El proceso ha terminado. El usuario ya envió ambas caras de su cédula. Estos son los análisis técnicos:\n"
            f"Frontal: {json.dumps(front, indent=2)}\n"
            f"Trasera: {json.dumps(back, indent=2)}\n\n"
            "Genera el mensaje final de validación:\n"
            "- Si ambos análisis son exitosos y con métricas que no apuntan a un fraude evidente (por ejemplo, confianza de detección de cédula o score aceptables): indícale que su documento ha sido validado correctamente. Felicítalo y explícale que el proceso fue exitoso. Despídete amablemente y recuérdale que si desea verificar otro documento, puede escribir *reiniciar*.\n"
            "- Si hay sospechas o scores bajos en alguna de las caras (fraude, foto de foto, pantalla, etc.): explícale de forma muy respetuosa y sutil que la verificación automática no fue exitosa. Aconséjale volver a intentarlo tomando fotos en un fondo plano con luz natural, y que puede escribir *reiniciar* para volver a empezar, o contactar a soporte."
        )
    elif flow_state == "UNSUPPORTED_TEXT":
        current_state = context.get("current_state", "AWAITING_FRONT")
        user_text = context.get("user_text", "")
        
        # Traducir estado a descripción comprensible
        state_desc = "la foto de la PARTE FRONTAL de su cédula" if current_state == "AWAITING_FRONT" else "la foto de la PARTE TRASERA de su cédula"
        if current_state == "DONE":
            state_desc = "escribir *reiniciar* si desea verificar otro documento"

        user_prompt = (
            f"El usuario está en el paso de proporcionar {state_desc}, pero en lugar de eso envió el siguiente texto: '{user_text}'.\n\n"
            "Responde a su mensaje de forma conversacional y agradable (saluda si es un saludo, responde brevemente si es una pregunta), "
            f"y recuérdale suavemente que para continuar con el proceso necesita enviar {state_desc}. "
            "Menciona que también puede escribir *reiniciar* en cualquier momento para empezar de nuevo."
        )
    else:
        # Fallback de seguridad
        return _get_fallback_message(flow_state, context)

    try:
        # Usamos client.aio para llamadas asíncronas no bloqueantes
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7,
                max_output_tokens=400,
            )
        )
        if response.text:
            return response.text.strip()
    except Exception:
        logger.exception("Error al llamar a la API de Gemini")
        
    return _get_fallback_message(flow_state, context)


def _get_fallback_message(flow_state: str, context: dict[str, Any]) -> str:
    """Mensajes de respaldo estáticos en caso de que Gemini no esté disponible."""
    if flow_state == "GREETING":
        return (
            "Hola 👋. Soy el asistente de verificación de documentos.\n\n"
            "Por favor, envía una *foto de la PARTE FRONTAL* de tu cédula."
        )
    elif flow_state == "AWAITING_FRONT_RESULT":
        result = context.get("result", {})
        if "error" in result:
            return (
                "No pude analizar la parte frontal de tu documento debido a un error técnico. "
                "Por favor, *reenvía la foto de la PARTE FRONTAL*."
            )
        # Resumen básico estructurado
        score = result.get("fraudScore") or result.get("confidence") or result.get("score")
        score_str = f"Score: {score:.2f}" if isinstance(score, (int, float)) else "procesada correctamente"
        return (
            f"Parte frontal recibida ✅ ({score_str}).\n\n"
            "Ahora, por favor envía la *foto de la PARTE TRASERA* de tu cédula."
        )
    elif flow_state == "AWAITING_BACK_RESULT":
        back = context.get("back_result", {})
        if "error" in back:
            return (
                "No pude analizar la parte trasera de tu documento debido a un error técnico. "
                "Por favor, *reenvía la foto de la PARTE TRASERA*."
            )
        return (
            "✅ *Análisis completado con éxito.*\n\n"
            "Hemos recibido y procesado ambas caras de tu documento correctamente.\n"
            "Si deseas analizar otro documento, escribe *reiniciar*."
        )
    elif flow_state == "UNSUPPORTED_TEXT":
        current_state = context.get("current_state", "AWAITING_FRONT")
        if current_state == "AWAITING_FRONT":
            return "Aún no he recibido la frontal. Por favor, envía la *foto de la PARTE FRONTAL* de tu cédula."
        elif current_state == "AWAITING_BACK":
            return "Ya recibí la frontal. Ahora, por favor envía la *foto de la PARTE TRASERA*."
        else:
            return "Ya procesé ambas caras de tu documento. Si quieres analizar otro, escribe *reiniciar*."
            
    return "Hola. Por favor, sigue las instrucciones del flujo o escribe *reiniciar* para empezar de nuevo."
