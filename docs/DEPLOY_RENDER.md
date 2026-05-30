# Deploy en Render

## 1. Subir el repo a GitHub

```bash
git init
git add .
git commit -m "Backend WhatsApp -> deteccion de fraude"
git branch -M main
git remote add origin https://github.com/<tu-usuario>/<repo>.git
git push -u origin main
```

> El `.gitignore` ya excluye `.env` y `.venv` — tus secretos no se suben.

## 2. Crear el Web Service

1. [dashboard.render.com](https://dashboard.render.com) → **New → Web Service** → conecta el repo.
2. Configuración:
   - **Runtime:** Python 3
   - **Build Command:**
     ```
     pip install uv && uv sync
     ```
   - **Start Command:**
     ```
     uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT
     ```
   - **Instance Type:** Free (suficiente para la prueba)

## 3. Variables de entorno (Environment)

Agrega en Render → **Environment** las mismas del `.env`:

```
WHATSAPP_PHONE_NUMBER_ID
WHATSAPP_ACCESS_TOKEN
WHATSAPP_VERIFY_TOKEN
WHATSAPP_API_VERSION = v22.0
WHATSAPP_APP_SECRET            (opcional)
FRAUD_API_URL = https://6v39g0i9ga.execute-api.us-east-1.amazonaws.com/upload-image
DATABASE_URL                  (Transaction pooler de Supabase, puerto 6543)
```

> **Importante (Supabase):** usa la cadena del **Transaction pooler** (host `*.pooler.supabase.com`,
> puerto `6543`). La conexión directa (5432) suele fallar en Render por IPv6.

## 4. Verificar el deploy

- En los logs debe aparecer: `DB lista: pool creado y tabla whatsapp_sessions verificada.`
- Abre `https://<tu-app>.onrender.com/` → debe responder `{"status":"ok"}`.
- Si faltan variables, los logs avisan: `Faltan variables de entorno: ...`.

## 5. Conectar el webhook en Meta

Sigue [META_SETUP.md](META_SETUP.md) paso 4 usando la URL `https://<tu-app>.onrender.com/webhook`.

## 6. Prueba end-to-end

Desde tu WhatsApp (número en la allowed list):
1. Escribe **"hola"** → el bot pide la **frontal**.
2. Envía la foto frontal → el bot confirma y pide la **trasera**.
3. Envía la foto trasera → el bot devuelve el **resultado consolidado**.

Verifica en los logs de Render: descarga de media OK, respuesta del Lambda, y la fila en
`whatsapp_sessions` en Supabase (Table Editor).

## Notas

- **Cold start:** el plan Free duerme tras inactividad; el primer mensaje puede tardar ~30-50s.
- **Token Meta:** el temporal expira en 24h; usa el permanente para pruebas largas.
