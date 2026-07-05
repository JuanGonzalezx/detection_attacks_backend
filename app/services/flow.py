"""Orquestación del flujo conversacional usando LangGraph."""
from __future__ import annotations

import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.services import sessions
from app.services.fraud_api import call_fraud_api
from app.services.gemini import generate_humanized_message
from app.services.whatsapp import download_media, send_text_message

logger = logging.getLogger(__name__)


# 1. Definición del Estado de la Conversación
class AgentState(TypedDict):
    phone: str
    input_text: str | None
    media_id: str | None
    current_state: str
    front_result: dict | None
    back_result: dict | None
    response: str


# 2. Descarga y procesamiento de imágenes con el Lambda
async def _process_image(phone: str, media_id: str, side: str) -> dict:
    """Descarga la imagen de Meta y la manda al Lambda de Rekognition."""
    try:
        image_bytes = await download_media(media_id)
        logger.info("Imagen (%s) descargada de %s: %d bytes", side, phone, len(image_bytes))
        result = await call_fraud_api(image_bytes)
        logger.info("Lambda respondió para %s (%s): %s", phone, side, result)
        return result
    except Exception as exc:
        logger.exception("Error procesando imagen %s para %s", side, phone)
        return {"error": str(exc)}


# 3. Nodos del Grafo (Funciones de Acción)
async def reset_flow_node(state: AgentState) -> dict[str, Any]:
    """Reinicia la sesión limpiando resultados y saludando al usuario."""
    logger.info("Nodo [reset_flow_node] ejecutado para %s", state["phone"])
    response_msg = await generate_humanized_message("GREETING", {})
    return {
        "current_state": "AWAITING_FRONT",
        "front_result": None,
        "back_result": None,
        "response": response_msg,
    }


async def process_front_node(state: AgentState) -> dict[str, Any]:
    """Procesa la imagen frontal de la cédula."""
    logger.info("Nodo [process_front_node] ejecutado para %s", state["phone"])
    media_id = state["media_id"]
    if not media_id:
        return {"response": "Error interno: no se proporcionó ID de imagen."}

    result = await _process_image(state["phone"], media_id, "frontal")
    if "error" in result:
        # Si falló, mantenemos el estado actual pidiendo que reenvíe
        response_msg = await generate_humanized_message("AWAITING_FRONT_RESULT", {"result": result})
        return {
            "response": response_msg,
        }

    # Si fue exitoso, avanzamos a esperar la trasera
    response_msg = await generate_humanized_message("AWAITING_FRONT_RESULT", {"result": result})
    return {
        "current_state": "AWAITING_BACK",
        "front_result": result,
        "response": response_msg,
    }


async def process_back_node(state: AgentState) -> dict[str, Any]:
    """Procesa la imagen trasera de la cédula y consolida la verificación."""
    logger.info("Nodo [process_back_node] ejecutado para %s", state["phone"])
    media_id = state["media_id"]
    if not media_id:
        return {"response": "Error interno: no se proporcionó ID de imagen trasera."}

    result = await _process_image(state["phone"], media_id, "trasera")
    if "error" in result:
        # Si falló, mantenemos AWAITING_BACK y pedimos reenvío
        response_msg = await generate_humanized_message("AWAITING_BACK_RESULT", {"back_result": result})
        return {
            "response": response_msg,
        }

    # Si fue exitoso, avanzamos a DONE y consolidamos resultados
    front_result = state["front_result"] or {}
    response_msg = await generate_humanized_message(
        "AWAITING_BACK_RESULT",
        {"front_result": front_result, "back_result": result},
    )
    return {
        "current_state": "DONE",
        "back_result": result,
        "response": response_msg,
    }


async def handle_unsupported_node(state: AgentState) -> dict[str, Any]:
    """Maneja mensajes de texto libre o archivos no soportados en el estado actual."""
    logger.info("Nodo [handle_unsupported_node] ejecutado para %s", state["phone"])
    text = state["input_text"] or "[imagen/archivo no soportado]"
    response_msg = await generate_humanized_message(
        "UNSUPPORTED_TEXT",
        {"current_state": state["current_state"], "user_text": text},
    )
    return {
        "response": response_msg,
    }


# 4. Lógica de Enrutamiento (Arista Condicional)
def decide_next_node(state: AgentState) -> str:
    """Decide a qué nodo ir basado en el texto del usuario, el estado y las entradas."""
    text = (state["input_text"] or "").strip().lower()
    # Si el usuario quiere reiniciar, vamos a reset_flow inmediatamente
    if text in {"reiniciar", "reset", "empezar", "nuevo"}:
        return "reset"

    curr = state["current_state"]
    media_id = state["media_id"]

    if curr == "AWAITING_FRONT":
        return "front" if media_id else "unsupported"
    elif curr == "AWAITING_BACK":
        return "back" if media_id else "unsupported"
    else:  # DONE
        return "unsupported"


# 5. Construcción y Compilación del Grafo
workflow = StateGraph(AgentState)

# Registrar nodos
workflow.add_node("reset_flow", reset_flow_node)
workflow.add_node("process_front", process_front_node)
workflow.add_node("process_back", process_back_node)
workflow.add_node("handle_unsupported", handle_unsupported_node)

# Entrada condicional
workflow.set_conditional_entry_point(
    decide_next_node,
    {
        "reset": "reset_flow",
        "front": "process_front",
        "back": "process_back",
        "unsupported": "handle_unsupported",
    },
)

# Transiciones finales (todos los nodos terminan el turno y esperan la siguiente interacción)
workflow.add_edge("reset_flow", END)
workflow.add_edge("process_front", END)
workflow.add_edge("process_back", END)
workflow.add_edge("handle_unsupported", END)

# Compilar
graph = workflow.compile()


# 6. Funciones de Entrada (Orquestación del Webhook)
async def _run_graph_and_persist(
    phone: str,
    input_text: str | None,
    media_id: str | None,
) -> None:
    """Carga la sesión, ejecuta el grafo de estados, persiste y responde al usuario."""
    # Recuperar sesión persistente de Supabase
    session = await sessions.get_session(phone)
    if session is None:
        current_state = "AWAITING_FRONT"
        front_result = None
        back_result = None
    else:
        current_state = session["state"]
        front_result = session["front_result"]
        back_result = session["back_result"]

    # Inicializar estado para el grafo
    initial_state: AgentState = {
        "phone": phone,
        "input_text": input_text,
        "media_id": media_id,
        "current_state": current_state,
        "front_result": front_result,
        "back_result": back_result,
        "response": "",
    }

    # Ejecutar el grafo de estados
    logger.info("Ejecutando grafo para %s en estado %s", phone, current_state)
    final_state = await graph.ainvoke(initial_state)

    # Persistir el estado resultante
    new_state = final_state["current_state"]
    new_front = final_state["front_result"]
    new_back = final_state["back_result"]

    if new_state == "AWAITING_FRONT" and new_front is None:
        await sessions.start_session(phone)
    elif new_state == "AWAITING_BACK" and new_front is not None and new_back is None:
        await sessions.save_front(phone, new_front)
    elif new_state == "DONE" and new_back is not None:
        await sessions.save_back(phone, new_back)

    # Enviar respuesta al usuario
    if final_state["response"]:
        await send_text_message(phone, final_state["response"])


async def handle_text(phone: str, text: str) -> None:
    """Procesa un mensaje de texto entrante."""
    await _run_graph_and_persist(phone, input_text=text, media_id=None)


async def handle_image(phone: str, media_id: str) -> None:
    """Procesa una imagen entrante."""
    await _run_graph_and_persist(phone, input_text=None, media_id=media_id)
