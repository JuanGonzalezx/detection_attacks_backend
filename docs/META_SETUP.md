# Configuración Meta / WhatsApp Cloud API

Como tu amigo ya tiene la cuenta de Business + Developer y el número, te saltas la creación de la app.
Solo necesitas **recolectar credenciales** y, al final, **configurar el webhook** apuntando a Render.

## 1. Recolectar credenciales (pásamelas para llenar el `.env`)

| Dato | Dónde sacarlo |
|---|---|
| `WHATSAPP_PHONE_NUMBER_ID` | App → **WhatsApp → API Setup** → campo *"From Phone Number ID"* (es un ID numérico, NO el número visible) |
| `WHATSAPP_ACCESS_TOKEN` | Para la 1ª prueba sirve el **token temporal de 24h** que aparece en API Setup. Para algo estable, ver paso 3. |
| `WHATSAPP_APP_SECRET` (opcional) | **App Settings → Basic → App Secret** (botón *Show*) |

El `WHATSAPP_VERIFY_TOKEN` **lo inventas tú** (ej. `cedula_fraude_2026_xyz`). Tiene que ser el mismo
valor que pongas en el `.env`/Render y en la pantalla de configuración del webhook de Meta.

## 2. Habilitar tu número para recibir respuestas (modo desarrollo)

En modo dev, WhatsApp solo responde a números en la lista permitida.
- App → **WhatsApp → API Setup** → sección *"To"* → **Add phone number** → agrega tu propio número
  (el que usarás para probar) y verifícalo con el código que llega por WhatsApp.

## 3. (Opcional) Token permanente — para pruebas de varios días

El token de 24h expira. Para uno que no expire:
1. **Business Settings → System Users → Add** → tipo **Admin**.
2. Asignar a ese system user la app y los permisos `whatsapp_business_messaging` + `whatsapp_business_management`.
3. **Generate New Token** → seleccionar la app → *never expires* → copiar. Ese es tu `WHATSAPP_ACCESS_TOKEN`.

## 4. Configurar el Webhook (DESPUÉS de desplegar en Render)

Una vez tengas la URL pública (Render o ngrok):
1. App → **WhatsApp → Configuration → Webhook → Edit**.
2. **Callback URL:** `https://<tu-app>.onrender.com/webhook`
3. **Verify Token:** el mismo valor de `WHATSAPP_VERIFY_TOKEN`.
4. Click **Verify and Save** → Meta hace un GET a `/webhook`; si el token coincide, queda en verde.
5. En **Webhook fields** → **Subscribe** al campo **`messages`**.

## 5. Validar envío (curl rápido, opcional)

```bash
curl -X POST "https://graph.facebook.com/v22.0/<PHONE_NUMBER_ID>/messages" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"messaging_product":"whatsapp","to":"<tu_numero_E164>","type":"text","text":{"body":"Hola desde Cloud API"}}'
```
`<tu_numero_E164>` = número con código de país sin `+`, ej. `573001112233`.

## Troubleshooting

| Error | Causa / solución |
|---|---|
| "Recipient phone number not in allowed list" | Falta agregar tu número en la allowed list (paso 2). |
| "Phone number is not registered" | Falta el `POST /register` del número en API Setup. |
| El webhook no verifica (no queda en verde) | El `Verify Token` de Meta ≠ `WHATSAPP_VERIFY_TOKEN` del backend, o la URL no es pública/accesible. |
| Recibo el mensaje pero el bot no responde | Token expirado (24h), o tu número no está en la allowed list, o revisa logs de Render. |
