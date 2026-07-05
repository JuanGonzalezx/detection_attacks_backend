"""App FastAPI: ciclo de vida (init/close DB) + rutas."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import close_db, init_db
from app.routes.webhook import router as webhook_router
from app.routes.metrics import router as metrics_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = settings.missing_required()
    if missing:
        logger.warning("Faltan variables de entorno: %s", ", ".join(missing))
    await init_db()
    yield
    await close_db()


app = FastAPI(title="Deteccion de fraude - WhatsApp orquestador", lifespan=lifespan)

# Configurar middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, restringir a los dominios del frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)
app.include_router(metrics_router)


@app.get("/")
async def health() -> dict:
    return {"status": "ok", "service": "whatsapp-fraud-orchestrator"}

