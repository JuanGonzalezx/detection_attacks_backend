# Orquestador WhatsApp → Detección de fraude en cédulas

Backend que conecta **WhatsApp Cloud API** con el **Lambda de Rekognition** del proyecto de doctorado.
Guía al usuario para enviar la cédula **imagen por imagen** (frontal → trasera), descarga cada foto de
Meta, la manda al Lambda y devuelve el resultado por WhatsApp.

- **Stack:** FastAPI + uvicorn (gestionado con `uv`)
- **Estado por usuario:** Supabase Postgres (tabla `whatsapp_sessions`, creada sola al arrancar)
- **Deploy:** Render

## Flujo de la conversación

| Estado | Entrada del usuario | Acción del bot |
|---|---|---|
| (sin sesión) | texto | Crea sesión, pide la **frontal** |
| `AWAITING_FRONT` | imagen | Descarga → Lambda → guarda → pide la **trasera** |
| `AWAITING_BACK` | imagen | Descarga → Lambda → guarda → **resultado consolidado** |
| cualquiera | `reiniciar` | Borra sesión y vuelve a pedir la frontal |

## Correr en local

```bash
uv sync
cp .env.example .env        # y llena las variables (ver abajo)
uv run uvicorn app.main:app --reload --port 8000
```

- Health check: `GET http://localhost:8000/` → `{"status":"ok"}`
- Para que Meta llegue a tu máquina: `ngrok http 8000` y usa esa URL pública como webhook.

## Variables de entorno

Ver [.env.example](.env.example). Resumen:

| Variable | Qué es |
|---|---|
| `WHATSAPP_PHONE_NUMBER_ID` | ID numérico del número (API Setup) |
| `WHATSAPP_ACCESS_TOKEN` | Token de acceso (temporal 24h o permanente) |
| `WHATSAPP_VERIFY_TOKEN` | Secreto que inventas; igual en Meta y aquí |
| `WHATSAPP_API_VERSION` | `v22.0` |
| `WHATSAPP_APP_SECRET` | (opcional) valida la firma del webhook |
| `FRAUD_API_URL` | Endpoint del Lambda |
| `DATABASE_URL` | Cadena del **Transaction pooler** de Supabase (puerto 6543) |

## Contrato del Lambda (verificado)

```
POST {FRAUD_API_URL}
Content-Type: application/json
{ "image": "<base64 de la imagen>" }
```

El campo es **`image`** (en inglés), no `imagen`. Responde JSON con lo que detecte Rekognition.

## Documentación

- [docs/META_SETUP.md](docs/META_SETUP.md) — configurar Meta / WhatsApp + webhook
- [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md) — desplegar en Render
