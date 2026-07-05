"""Orquestación del flujo conversacional usando LangGraph con telemetría de métricas."""
from __future__ import annotations

import logging
import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.services import sessions
from app.services.fraud_api import call_fraud_api
from app.services.gemini import generate_humanized_message
from app.services.whatsapp import download_media, send_text_message

logger = logging.getLogger(__name__)


# 1. Definición del Estado de la Conversación (con campos de telemetría/métricas)
class AgentState(TypedDict):
    phone: str
    input_text: str | None
    media_id: str | None
    current_state: str
    front_result: dict | None
    back_result: dict | None
    response: str
    
    # Telemetría para métricas
    latency_aws_ms: int | None
    latency_gemini_ms: int | None
    node_executed: str | None
    status: str
    is_photocopy: bool
    lambda_score: float | None
    lambda_confidence: float | None
    lambda_response: dict | None


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
    
    start_gemini = time.perf_counter()
    response_msg = await generate_humanized_message("GREETING", {})
    latency_gemini = int((time.perf_counter() - start_gemini) * 1000)

    return {
        "current_state": "AWAITING_FRONT",
        "front_result": None,
        "back_result": None,
        "response": response_msg,
        "latency_aws_ms": None,
        "latency_gemini_ms": latency_gemini,
        "node_executed": "reset_flow",
        "status": "success",
        "is_photocopy": False,
        "lambda_score": None,
        "lambda_confidence": None,
        "lambda_response": None,
    }


async def process_front_node(state: AgentState) -> dict[str, Any]:
    """Procesa la imagen frontal de la cédula."""
    logger.info("Nodo [process_front_node] ejecutado para %s", state["phone"])
    media_id = state["media_id"]
    if not media_id:
        return {
            "response": "Error interno: no se proporcionó ID de imagen.",
            "node_executed": "process_front",
            "status": "error",
            "is_photocopy": False,
            "latency_aws_ms": None,
            "latency_gemini_ms": None,
            "lambda_score": None,
            "lambda_confidence": None,
            "lambda_response": None,
        }

    start_aws = time.perf_counter()
    result = await _process_image(state["phone"], media_id, "frontal")
    latency_aws = int((time.perf_counter() - start_aws) * 1000)

    start_gemini = time.perf_counter()
    response_msg = await generate_humanized_message("AWAITING_FRONT_RESULT", {"result": result})
    latency_gemini = int((time.perf_counter() - start_gemini) * 1000)

    if "error" in result:
        # Si falló, mantenemos el estado actual
        return {
            "response": response_msg,
            "latency_aws_ms": latency_aws,
            "latency_gemini_ms": latency_gemini,
            "node_executed": "process_front",
            "status": "error",
            "is_photocopy": False,
            "lambda_score": None,
            "lambda_confidence": None,
            "lambda_response": result,
        }

    # Analizar score e indicar si es fotocopia (0 = Real, 1 = Fotocopia, umbral 0.5)
    score = result.get("score") or result.get("confidence") or result.get("fraudScore")
    confidence = result.get("detection", {}).get("confidence")
    
    is_photocopy = False
    status = "success"
    if score is not None and score >= 0.5:
        is_photocopy = True
        status = "fraud_detected"


    return {
        "current_state": "AWAITING_BACK",
        "front_result": result,
        "response": response_msg,
        "latency_aws_ms": latency_aws,
        "latency_gemini_ms": latency_gemini,
        "node_executed": "process_front",
        "status": status,
        "is_photocopy": is_photocopy,
        "lambda_score": score,
        "lambda_confidence": confidence,
        "lambda_response": result,
    }


async def process_back_node(state: AgentState) -> dict[str, Any]:
    """Procesa la imagen trasera de la cédula y consolida la verificación."""
    logger.info("Nodo [process_back_node] ejecutado para %s", state["phone"])
    media_id = state["media_id"]
    if not media_id:
        return {
            "response": "Error interno: no se proporcionó ID de imagen trasera.",
            "node_executed": "process_back",
            "status": "error",
            "is_photocopy": False,
            "latency_aws_ms": None,
            "latency_gemini_ms": None,
            "lambda_score": None,
            "lambda_confidence": None,
            "lambda_response": None,
        }

    start_aws = time.perf_counter()
    result = await _process_image(state["phone"], media_id, "trasera")
    latency_aws = int((time.perf_counter() - start_aws) * 1000)

    front_result = state["front_result"] or {}
    start_gemini = time.perf_counter()
    response_msg = await generate_humanized_message(
        "AWAITING_BACK_RESULT",
        {"front_result": front_result, "back_result": result},
    )
    latency_gemini = int((time.perf_counter() - start_gemini) * 1000)

    if "error" in result:
        # Si falló, mantenemos AWAITING_BACK
        return {
            "response": response_msg,
            "latency_aws_ms": latency_aws,
            "latency_gemini_ms": latency_gemini,
            "node_executed": "process_back",
            "status": "error",
            "is_photocopy": False,
            "lambda_score": None,
            "lambda_confidence": None,
            "lambda_response": result,
        }

    # Analizar consolidación (0 = Real, 1 = Fotocopia, umbral 0.5)
    score = result.get("score") or result.get("confidence") or result.get("fraudScore")
    confidence = result.get("detection", {}).get("confidence")
    
    is_photocopy = False
    status = "success"
    if score is not None and score >= 0.5:
        is_photocopy = True
        status = "fraud_detected"

    # Revisar también si la frontal fue fraude (umbral 0.5)
    front_score = front_result.get("score") or front_result.get("confidence") or front_result.get("fraudScore")
    if front_score is not None and front_score >= 0.5:
        is_photocopy = True
        status = "fraud_detected"


    return {
        "current_state": "DONE",
        "back_result": result,
        "response": response_msg,
        "latency_aws_ms": latency_aws,
        "latency_gemini_ms": latency_gemini,
        "node_executed": "process_back",
        "status": status,
        "is_photocopy": is_photocopy,
        "lambda_score": score,
        "lambda_confidence": confidence,
        "lambda_response": result,
    }


async def handle_unsupported_node(state: AgentState) -> dict[str, Any]:
    """Maneja mensajes de texto libre o archivos no soportados en el estado actual."""
    logger.info("Nodo [handle_unsupported_node] ejecutado para %s", state["phone"])
    text = state["input_text"] or "[imagen/archivo no soportado]"
    
    start_gemini = time.perf_counter()
    response_msg = await generate_humanized_message(
        "UNSUPPORTED_TEXT",
        {"current_state": state["current_state"], "user_text": text},
    )
    latency_gemini = int((time.perf_counter() - start_gemini) * 1000)

    return {
        "response": response_msg,
        "latency_aws_ms": None,
        "latency_gemini_ms": latency_gemini,
        "node_executed": "handle_unsupported",
        "status": "success",
        "is_photocopy": False,
        "lambda_score": None,
        "lambda_confidence": None,
        "lambda_response": None,
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

# Transiciones finales
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
        "latency_aws_ms": None,
        "latency_gemini_ms": None,
        "node_executed": None,
        "status": "success",
        "is_photocopy": False,
        "lambda_score": None,
        "lambda_confidence": None,
        "lambda_response": None,
    }

    # Ejecutar el grafo de estados
    logger.info("Ejecutando grafo para %s en estado %s", phone, current_state)
    final_state = await graph.ainvoke(initial_state)

    # Persistir el estado resultante de la sesión
    new_state = final_state["current_state"]
    new_front = final_state["front_result"]
    new_back = final_state["back_result"]

    if new_state == "AWAITING_FRONT" and new_front is None:
        await sessions.start_session(phone)
    elif new_state == "AWAITING_BACK" and new_front is not None and new_back is None:
        await sessions.save_front(phone, new_front)
    elif new_state == "DONE" and new_back is not None:
        await sessions.save_back(phone, new_back)

    # Enviar respuesta al usuario y capturar ID del mensaje
    msg_id = None
    if final_state["response"]:
        ok, msg_id = await send_text_message(phone, final_state["response"])

    # Registrar el evento en la base de datos para métricas (si se ejecutó un nodo válido)
    node_executed = final_state.get("node_executed")
    if node_executed:
        try:
            await sessions.log_validation_event(
                phone=phone,
                node=node_executed,
                whatsapp_message_id=msg_id,
                lambda_score=final_state.get("lambda_score"),
                lambda_confidence=final_state.get("lambda_confidence"),
                lambda_response=final_state.get("lambda_response"),
                latency_aws_ms=final_state.get("latency_aws_ms"),
                latency_gemini_ms=final_state.get("latency_gemini_ms"),
                status=final_state.get("status", "success"),
                is_photocopy=final_state.get("is_photocopy", False),
            )
            logger.info("Métrica registrada en base de datos para el nodo %s", node_executed)
        except Exception:
            logger.exception("Error al registrar evento de métricas para %s", phone)


async def handle_text(phone: str, text: str) -> None:
    """Procesa un mensaje de texto entrante."""
    await _run_graph_and_persist(phone, input_text=text, media_id=None)


async def handle_image(phone: str, media_id: str) -> None:
    """Procesa una imagen entrante."""
    await _run_graph_and_persist(phone, input_text=None, media_id=media_id)
