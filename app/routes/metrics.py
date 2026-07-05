"""Endpoints para consultar las métricas del dashboard."""
from __future__ import annotations

import logging
from typing import List
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/metrics", tags=["Métricas del Dashboard"])


# --- Pydantic Schemas para la documentación automática de Swagger ---

class KPISummary(BaseModel):
    total_validations: int = Field(..., description="Conteo total de eventos procesados en el webhook de WhatsApp")
    predicted_real: int = Field(..., description="Total de cédulas aprobadas como auténticas por el modelo")
    predicted_photocopy: int = Field(..., description="Total de ataques o copias fraudulentas detectadas")
    real_percentage: float = Field(..., description="Tasa porcentual de aprobación de documentos reales")
    photocopy_percentage: float = Field(..., description="Tasa porcentual de detección de ataques o copias")


class ScoreDistribution(BaseModel):
    front: List[int] = Field(
        ..., 
        description="Frecuencia de predicciones (cédula frontal) agrupadas en 10 rangos de score de 0.0 a 1.0 (de 0.1 en 0.1)"
    )
    back: List[int] = Field(
        ..., 
        description="Frecuencia de predicciones (cédula trasera) agrupadas en 10 rangos de score de 0.0 a 1.0 (de 0.1 en 0.1)"
    )


class DailyPrediction(BaseModel):
    date: str = Field(..., description="Fecha agrupada (YYYY-MM-DD)")
    front: int = Field(..., description="Cantidad de cédulas frontales procesadas")
    back: int = Field(..., description="Cantidad de cédulas traseras procesadas")
    unsupported: int = Field(..., description="Interacciones de texto libre o formatos no soportados por el bot")
    photocopy: int = Field(..., description="Cantidad de anomalías o fotocopias detectadas en el día")
    total: int = Field(..., description="Total de interacciones del día")


class LatencyItem(BaseModel):
    timestamp: str = Field(..., description="Fecha y hora de la transacción")
    aws: int | None = Field(..., description="Tiempo de ejecución de la Lambda de AWS en milisegundos")
    gemini: int | None = Field(..., description="Tiempo de ejecución del modelo Gemini en milisegundos")


class ExecutionTimes(BaseModel):
    avg_aws: int = Field(..., description="Tiempo promedio de procesamiento en AWS (Rekognition) en milisegundos")
    avg_gemini: int = Field(..., description="Tiempo promedio de procesamiento en Google Gemini en milisegundos")
    history: List[LatencyItem] = Field(..., description="Lista de latencias de las últimas 50 llamadas para gráficos")


class ValidationLogItem(BaseModel):
    timestamp: str = Field(..., description="Marca temporal de la transacción")
    phone: str = Field(..., description="Número telefónico del usuario")
    node: str = Field(..., description="Nombre del nodo ejecutado en el grafo de LangGraph")
    score: float | None = Field(..., description="Puntuación de veracidad del modelo (0.0 a 1.0)")
    is_photocopy: bool = Field(..., description="Verdadero si el modelo catalogó el documento como copia/fraude")
    message_id: str | None = Field(..., description="WhatsApp Message ID único retornado por Meta (wamid)")


class MetricsResponse(BaseModel):
    kpis: KPISummary = Field(..., description="Resumen de indicadores clave de rendimiento")
    score_distribution: ScoreDistribution = Field(..., description="Distribución de puntuaciones para los histogramas")
    daily_predictions: List[DailyPrediction] = Field(..., description="Historial agrupado diario de validaciones")
    execution_times: ExecutionTimes = Field(..., description="Tiempos de latencia y desempeño de los servicios")
    history: List[ValidationLogItem] = Field(..., description="Lista de historial detallado para la tabla de logs")


# --- Endpoint de la API ---

@router.get(
    "", 
    response_model=MetricsResponse,
    summary="Obtener todas las métricas agregadas del bot",
    description=(
        "Consulta la base de datos de Supabase y calcula las métricas consolidadas del sistema "
        "de validación de cédulas. Retorna KPIs, distribuciones de scores, volumen temporal, "
        "latencias de AWS y Gemini, e historial de logs para renderizar en el Dashboard."
    )
)
async def get_metrics() -> dict:
    """Calcula y devuelve todos los KPIs, histogramas y el historial de logs para el Dashboard."""
    try:
        pool = get_pool()

        # 1. KPIs Generales
        # Total de mensajes que entraron al webhook
        total_events = await pool.fetchval("SELECT COUNT(*) FROM validation_logs") or 0

        # Total de ejecuciones de imágenes (frontal o trasera)
        total_front_back = await pool.fetchval(
            "SELECT COUNT(*) FROM validation_logs WHERE node IN ('process_front', 'process_back')"
        ) or 0

        # Validaciones reales y anomalías detectadas
        predicted_real = await pool.fetchval(
            "SELECT COUNT(*) FROM validation_logs WHERE is_photocopy = FALSE AND node IN ('process_front', 'process_back')"
        ) or 0

        predicted_photocopy = await pool.fetchval(
            "SELECT COUNT(*) FROM validation_logs WHERE is_photocopy = TRUE AND node IN ('process_front', 'process_back')"
        ) or 0

        real_percentage = 0.0
        photocopy_percentage = 0.0
        if total_front_back > 0:
            real_percentage = round((predicted_real / total_front_back) * 100, 3)
            photocopy_percentage = round((predicted_photocopy / total_front_back) * 100, 3)


        # 2. Distribución de Scores (Histogramas Front y Back)
        front_scores_rows = await pool.fetch(
            "SELECT lambda_score::float FROM validation_logs WHERE node = 'process_front' AND lambda_score IS NOT NULL"
        )
        back_scores_rows = await pool.fetch(
            "SELECT lambda_score::float FROM validation_logs WHERE node = 'process_back' AND lambda_score IS NOT NULL"
        )

        front_scores = [r["lambda_score"] for r in front_scores_rows]
        back_scores = [r["lambda_score"] for r in back_scores_rows]

        def calculate_bins(scores: list[float]) -> list[int]:
            # Genera 10 bins: [0.0-0.1, 0.1-0.2, ..., 0.9-1.0]
            bins = [0] * 10
            for s in scores:
                idx = int(s * 10)
                if idx >= 10:
                    idx = 9
                if idx < 0:
                    idx = 0
                bins[idx] += 1
            return bins

        front_bins = calculate_bins(front_scores)
        back_bins = calculate_bins(back_scores)

        # 3. Tendencia Diaria (Volumen por fecha y nodos)
        daily_rows = await pool.fetch(
            """
            SELECT 
                TO_CHAR(timestamp, 'YYYY-MM-DD') as day,
                COUNT(*) FILTER (WHERE node = 'process_front') as front_count,
                COUNT(*) FILTER (WHERE node = 'process_back') as back_count,
                COUNT(*) FILTER (WHERE node = 'handle_unsupported') as unsupported_count,
                COUNT(*) FILTER (WHERE is_photocopy = TRUE) as photocopy_count,
                COUNT(*) as total_count
            FROM validation_logs
            GROUP BY day
            ORDER BY day ASC
            """
        )

        daily_predictions = [
            {
                "date": r["day"],
                "front": r["front_count"],
                "back": r["back_count"],
                "unsupported": r["unsupported_count"],
                "photocopy": r["photocopy_count"],
                "total": r["total_count"],
            }
            for r in daily_rows
        ]

        # 4. Latencias de ejecución (AWS Lambda y Gemini)
        latency_rows = await pool.fetch(
            """
            SELECT 
                TO_CHAR(timestamp, 'YYYY-MM-DD HH24:MI:SS') as time_str,
                latency_aws_ms,
                latency_gemini_ms
            FROM validation_logs
            WHERE latency_aws_ms IS NOT NULL OR latency_gemini_ms IS NOT NULL
            ORDER BY timestamp ASC
            LIMIT 50
            """
        )

        latency_history = [
            {
                "timestamp": r["time_str"],
                "aws": r["latency_aws_ms"],
                "gemini": r["latency_gemini_ms"],
            }
            for r in latency_rows
        ]

        # Promedios de latencias
        avg_latencies = await pool.fetchrow(
            """
            SELECT 
                ROUND(AVG(latency_aws_ms)) as avg_aws,
                ROUND(AVG(latency_gemini_ms)) as avg_gemini
            FROM validation_logs
            """
        )

        # 5. Historial detallado de logs
        history_rows = await pool.fetch(
            """
            SELECT 
                TO_CHAR(timestamp, 'YYYY-MM-DD HH24:MI:SS') as time_str,
                phone,
                node,
                lambda_score::float as score,
                is_photocopy,
                whatsapp_message_id
            FROM validation_logs
            ORDER BY timestamp DESC
            LIMIT 100
            """
        )

        history_data = [
            {
                "timestamp": r["time_str"],
                "phone": r["phone"],
                "node": r["node"],
                "score": r["score"],
                "is_photocopy": r["is_photocopy"],
                "message_id": r["whatsapp_message_id"],
            }
            for r in history_rows
        ]

        return {
            "kpis": {
                "total_validations": total_events,
                "predicted_real": predicted_real,
                "predicted_photocopy": predicted_photocopy,
                "real_percentage": real_percentage,
                "photocopy_percentage": photocopy_percentage,
            },
            "score_distribution": {
                "front": front_bins,
                "back": back_bins,
            },
            "daily_predictions": daily_predictions,
            "execution_times": {
                "avg_aws": avg_latencies["avg_aws"] if avg_latencies and avg_latencies["avg_aws"] else 0,
                "avg_gemini": avg_latencies["avg_gemini"] if avg_latencies and avg_latencies["avg_gemini"] else 0,
                "history": latency_history,
            },
            "history": history_data,
        }

    except Exception as exc:
        logger.exception("Error al consultar las métricas")
        return {"error": str(exc)}
