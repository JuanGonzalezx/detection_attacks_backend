# CLAUDE.md — Contexto del proyecto

Backend orquestador que conecta **WhatsApp Cloud API** con un **Lambda de AWS (Rekognition)**
para un proyecto de doctorado sobre **detección de fraude en documentos de identidad (cédulas)**.

El usuario (Juan David) construye/opera este orquestador. Un **amigo es dueño del lado AWS**
(Lambda + Rekognition + S3) y de la cuenta de WhatsApp Business/Developer.

Estado: **funcionando end-to-end en producción** (Render) a 2026-05-30.

---

## Qué hace

Guía a un usuario por WhatsApp para que envíe su cédula **imagen por imagen** (frontal → trasera),
descarga cada foto de Meta, la manda al Lambda, y devuelve el resultado por WhatsApp.

### Flujo conversacional (máquina de estados por teléfono)

| Estado | Entrada | Acción |
|---|---|---|
| (sin sesión) | texto | Crea sesión `AWAITING_FRONT`, saluda y pide la **frontal** |
| `AWAITING_FRONT` | imagen | Descarga → Lambda → si OK guarda y avanza a `AWAITING_BACK` y pide la **trasera**; si error, pide **reenviar la frontal** (no avanza) |
| `AWAITING_BACK` | imagen | Descarga → Lambda → si OK guarda, marca `DONE` y devuelve **resultado consolidado**; si error, pide **reenviar la trasera** |
| `DONE` | cualquiera | Avisa que ya procesó; sugiere `reiniciar` |
| cualquiera | `reiniciar`/`reset`/`empezar`/`nuevo` | Borra sesión y vuelve a `AWAITING_FRONT` |

Estado persistido en Supabase (tabla `whatsapp_sessions`), así sobrevive reinicios de Render.

---

## Stack y estructura

- **FastAPI + uvicorn**, gestionado con **uv**. HTTP async con `httpx`. DB con `asyncpg`.
- **Supabase Postgres** para el estado. **Render** para el deploy.

```
app/
  main.py                 # FastAPI + lifespan (init/close pool DB); health en GET /
  config.py               # Settings desde env (.env local / vars de Render)
  db.py                   # pool asyncpg (statement_cache_size=0 por el pooler) + crea tabla al arrancar
  routes/webhook.py       # GET /webhook (verificación Meta) + POST /webhook (mensajes); dedup en memoria; siempre 200
  services/whatsapp.py    # send_text_message() + download_media() (2 pasos Graph API)
  services/fraud_api.py   # call_fraud_api(bytes) -> POST {"image": base64}; reintenta 1 vez ante 5xx/timeout
  services/sessions.py    # CRUD del estado (get/start/save_front/save_back/reset)
  services/flow.py        # orquestación: handle_text() / handle_image() + _summarize()
docs/
  META_SETUP.md           # configurar Meta/WhatsApp + webhook
  DEPLOY_RENDER.md        # desplegar en Render
render.yaml               # blueprint de Render (build/start + env vars sync:false)
```

`whatsapp_sessions`: `phone PK, state, front_result jsonb, back_result jsonb, updated_at`.
Se crea sola al arrancar (`SCHEMA` en `app/db.py`).

---

## Contrato del Lambda (verificado empíricamente)

Endpoint del amigo: `https://6v39g0i9ga.execute-api.us-east-1.amazonaws.com/upload-image`

- **Request:** `POST application/json` con `{"image": "<base64 de la imagen>"}`.
  El campo es **`image`** (inglés), NO `imagen`. Multipart o `imagen` fallan.
- **Response (OK):** `{"labels": [{Name, Confidence, Instances:[{BoundingBox}], ...}], "s3_key": "...", "s3_url": "https://presentation-attacks.s3.amazonaws.com/..."}`.
  → **El Lambda YA guarda el original en S3** (bucket `presentation-attacks`); el backend NO necesita boto3.
- Hoy **sin API key**.
- **Caveat:** a veces devuelve **HTTP 500** (visto en la frontal con rostro; posible cold start o bug del lado frontal).
  El backend reintenta 1 vez y, si persiste, pide reenviar esa misma cara sin avanzar.
- `_summarize()` ya contempla campos futuros (`cedula`/`documentNumber`, `nombre`/`name`, `fraudScore`/`score`)
  para cuando el Lambda devuelva cédula + score + coordenadas.

---

## Configuración / credenciales

Variables de entorno (ver `.env.example`). **Los secretos viven solo en Render y en `.env` local (gitignored)** — no en el repo.

| Variable | Notas |
|---|---|
| `WHATSAPP_PHONE_NUMBER_ID` | `990076807518216` (número "Formas GYM", +57 318 3795292) |
| `WHATSAPP_ACCESS_TOKEN` | **Secreto.** Actual es token USER que **expira** → migrar al permanente de System User (META_SETUP.md paso 3) |
| `WHATSAPP_VERIFY_TOKEN` | `cedula_fraude_2026_xyz` (mismo valor en Meta y en el backend) |
| `WHATSAPP_API_VERSION` | `v25.0` |
| `WHATSAPP_APP_SECRET` | opcional; si se llena, valida la firma `X-Hub-Signature-256` |
| `FRAUD_API_URL` | endpoint del Lambda (arriba) |
| `DATABASE_URL` | **Secreto (contraseña).** Supabase **Transaction pooler**, región `aws-1-us-west-2`, puerto `6543`. El `#` de la contraseña va escapado como `%23` |

### Notas críticas de despliegue (lecciones aprendidas)
- **Supabase:** usar la cadena del **pooler** (`*.pooler.supabase.com:6543`), NO la directa
  (`db.*.supabase.co:5432`, que es IPv6-only y falla en Render con `getaddrinfo failed`).
  Región de este proyecto: `aws-1-us-west-2`. Usuario del pooler: `postgres.<project-ref>`.
- **Webhook de Meta:** la Callback URL debe terminar en **`/webhook`**
  (`https://<app>.onrender.com/webhook`). Apuntar a la raíz `/` hace que la verificación falle.
- **Suscribir el campo `messages`** en Meta o el webhook valida pero no llegan mensajes.
- En **modo dev** de Meta solo responde a números en la *allowed list*.
- **Render free** duerme por inactividad → primer request con cold start ~30-50s.

---

## Desarrollo local

```bash
uv sync
cp .env.example .env        # llenar valores reales
uv run uvicorn app.main:app --reload --port 8000
# Para exponer a Meta en local: ngrok http 8000
```

## Deploy (Render)

Push a `main` → Render redesplega solo (servicio `detection-attacks-whatsapp`).
Build: `pip install uv && uv sync` · Start: `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
Repo remoto usa SSH (`git@github.com:JuanGonzalezx/detection_attacks_backend.git`) → el push se hace
desde la terminal del usuario (no desde el entorno de Claude).

---

## Pendientes / próximos pasos

- [ ] Migrar `WHATSAPP_ACCESS_TOKEN` al **permanente (System User)** para que no expire.
- [ ] El amigo: revisar **CloudWatch** del Lambda para el **HTTP 500 de la frontal** (rostro / cold start).
- [ ] Cuando el Lambda devuelva **cédula + score + coordenadas + qué lado es**, ajustar el mensaje final
      (la base ya está en `_summarize`).
- [ ] (Opcional) dedup de mensajes en memoria → mover a DB/Redis si Render escala a >1 instancia.
